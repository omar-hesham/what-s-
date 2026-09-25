/**
 * OWI WhatsApp Web Content Script v3.1
 * User-initiated bulk capture companion for Omar WhatsApp Intelligence (OWI).
 *
 * Enforces:
 * - Content scripts never call fetch() across origin boundaries
 * - All loopback ingest and diagnostic requests are bridged via background.js
 * - Truthful completion: final state is complete only if traversal reached bounds and all chunks were acknowledged
 * - Zero-message results never post empty payloads to backend
 * - Responsive cancellation checks before and during chunk posting
 */

(function () {
  let isCaptureRunning = false;
  let cancelRequested = false;

  let lastKnownState = { status: "idle" };

  async function updateCaptureState(stateObj) {
    lastKnownState = stateObj;
    if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.sendMessage) {
      try {
        await new Promise((resolve) => {
          chrome.runtime.sendMessage(
            { action: "bridge_set_capture_state", state: stateObj },
            () => resolve()
          );
        });
      } catch (e) {}
    }
  }

  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    // 1. Get Live State
    if (request.action === "get_capture_state") {
      sendResponse(lastKnownState || { status: "idle" });
      return true;
    }

    // 2. Cancel Bulk Capture
    if (request.action === "cancel_bulk_capture") {
      cancelRequested = true;
      sendResponse({ status: "cancelling" });
      return true;
    }

    // 3. Start Bulk Capture
    if (request.action === "start_bulk_capture") {
      if (isCaptureRunning) {
        sendResponse({ status: "already_running" });
        return true;
      }

      isCaptureRunning = true;
      cancelRequested = false;

      const config = request.config || {};
      const mode = config.mode || "visible_to_newest";
      const fromDate = config.fromDate || null;
      const toDate = config.toDate || null;
      const dateOrder = config.dateOrder || "DD/MM/YYYY";
      const chunkSize = Math.min(Math.max(config.chunkSize || 50, 1), 100);

      sendResponse({ status: "started" });

      (async () => {
        const sessionId = "bulk_" + Date.now();

        await updateCaptureState({
          status: "running",
          sessionId,
          mode,
          stage: "initializing",
          messagesScanned: 0,
          messagesIngested: 0,
          startTime: Date.now()
        });

        try {
          const container = OWIBulkCaptureEngine.findScrollContainer(document);

          const result = await OWIBulkCaptureEngine.runBulkCapture({
            container,
            doc: document,
            mode,
            fromDate,
            toDate,
            dateOrder,
            checkCancelled: () => cancelRequested,
            onProgress: async (prog) => {
              await updateCaptureState({
                status: "running",
                sessionId,
                mode,
                stage: prog.stage,
                messagesScanned: prog.messagesCollected,
                oldestDate: prog.oldestDateReached || null
              });
            }
          });

          // Zero-message capture handling: NEVER send empty messages to /ingest
          if (!result.messages || result.messages.length === 0) {
            await updateCaptureState({
              status: "finished",
              sessionId,
              mode,
              completenessStatus: "partial",
              partialReason: result.partialReason || "zero_messages_captured",
              chatTitle: result.chatTitle,
              totalScanned: result.totalScanned || 0,
              totalExtracted: 0,
              messagesIngested: 0,
              duplicatesSkipped: 0,
              finishedAt: Date.now()
            });
            await OWIDiagnosticLogger.flushToBackend();
            return;
          }

          // Chunked ingestion via background bridge
          const chunks = OWIBulkCaptureEngine.chunkArray(result.messages, chunkSize);
          let ingestedCount = 0;
          let duplicatesSkipped = 0;
          let acknowledgedChunks = 0;
          let chunkFailed = false;

          for (let i = 0; i < chunks.length; i++) {
            if (cancelRequested) {
              result.completenessStatus = "partial";
              result.partialReason = "cancelled_by_user";
              break;
            }

            const isLast = i === chunks.length - 1;
            const postRes = await OWIBulkCaptureEngine.postChunkWithRetry({
              chatTitle: result.chatTitle,
              chunk: chunks[i],
              chunkIndex: i,
              totalChunks: chunks.length,
              isLastChunk: isLast,
              completenessStatus: result.completenessStatus,
              partialReason: result.partialReason,
              sessionId,
              dateOrder
            });

            if (postRes && postRes.success) {
              acknowledgedChunks++;
              ingestedCount += postRes.data.messages_ingested || 0;
              duplicatesSkipped += postRes.data.duplicates_skipped || 0;
            } else {
              chunkFailed = true;
              result.completenessStatus = "partial";
              result.partialReason = postRes?.partialReason || "chunk_ingest_failed";
              await OWIDiagnosticLogger.log(
                "ingest_chunk",
                "CHUNK_POST_FAILED",
                chunks[i].length,
                result.partialReason
              );
              break;
            }

            await updateCaptureState({
              status: "running",
              sessionId,
              mode,
              stage: "ingesting",
              currentChunk: i + 1,
              totalChunks: chunks.length,
              messagesScanned: result.messages.length,
              messagesIngested: ingestedCount
            });
          }

          // Final completeness state determination
          let finalCompleteness = "complete";
          let finalReason = null;

          if (result.completenessStatus !== "complete") {
            finalCompleteness = "partial";
            finalReason = result.partialReason;
          } else if (chunkFailed || acknowledgedChunks < chunks.length) {
            finalCompleteness = "partial";
            finalReason = result.partialReason || "chunk_ingest_failed";
          }

          const finalState = {
            status: "finished",
            sessionId,
            mode,
            completenessStatus: finalCompleteness,
            partialReason: finalReason,
            chatTitle: result.chatTitle,
            totalScanned: result.totalScanned,
            totalExtracted: result.messages.length,
            messagesIngested: ingestedCount,
            duplicatesSkipped,
            finishedAt: Date.now()
          };

          await updateCaptureState(finalState);
          await OWIDiagnosticLogger.flushToBackend();
        } catch (err) {
          await OWIDiagnosticLogger.log("summary", "PARTIAL", 0, "traversal_stalled");
          await updateCaptureState({
            status: "error",
            sessionId,
            completenessStatus: "partial",
            partialReason: "traversal_stalled"
          });
        } finally {
          isCaptureRunning = false;
          cancelRequested = false;
        }
      })();

      return true;
    }

    // 4. Legacy Active Chat Parser
    if (request.action === "capture_active_chat") {
      (async () => {
        try {
          const chatTitle = OWIBulkCaptureEngine.extractChatTitle(document);
          const container = OWIBulkCaptureEngine.findScrollContainer(document) || document;
          const msgNodes = container.querySelectorAll("div[data-id], .message-in, .message-out");
          const collected = [];

          for (const el of msgNodes) {
            const item = OWIBulkCaptureEngine.parseMessageNode(el, chatTitle, "DD/MM/YYYY");
            if (item) collected.push(item);
          }

          sendResponse({
            chat_title: chatTitle,
            messages: collected
          });
        } catch (err) {
          sendResponse({ error: "failed", messages: [] });
        }
      })();
      return true;
    }
  });
})();
