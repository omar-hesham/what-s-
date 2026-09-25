/**
 * OWI Companion - Bulk Capture Engine
 * Core engine for virtualized WhatsApp Web DOM traversal, message extraction,
 * date bounds filtering, cancellation, chunked ingestion, and completeness tracking.
 * Routes all loopback ingestion and diagnostics through the background service worker bridge.
 */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    const dateParser = require("./date_parser.js");
    const diagLogger = require("./diagnostic_logger.js");
    module.exports = factory(dateParser, diagLogger);
  } else {
    root.OWIBulkCaptureEngine = factory(root.OWIDateParser, root.OWIDiagnosticLogger);
  }
})(typeof self !== "undefined" ? self : this, function (DateParser, DiagLogger) {

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function chunkArray(items, size = 50) {
    const chunks = [];
    for (let i = 0; i < items.length; i += size) {
      chunks.push(items.slice(i, i + size));
    }
    return chunks;
  }

  function generateSyntheticId(sender, timestampIso, text) {
    const raw = `${sender || ""}|${timestampIso || ""}|${(text || "").slice(0, 100)}`;
    let hash = 0;
    for (let i = 0; i < raw.length; i++) {
      hash = ((hash << 5) - hash + raw.charCodeAt(i)) | 0;
    }
    return `synth_${Math.abs(hash).toString(16)}`;
  }

  /**
   * Filter messages strictly within [fromDate, toDate].
   * Unparseable timestamps are NEVER included; their presence is tracked to mark overall status partial.
   */
  function filterMessagesByDateRange(messages, fromDate, toDate) {
    const fromTime = fromDate ? new Date(fromDate).getTime() : -Infinity;
    const toTime = toDate ? new Date(toDate).getTime() : Infinity;

    let unparseableCount = 0;
    const filtered = [];

    for (const m of messages) {
      if (!m.parsed_date) {
        unparseableCount++;
        continue;
      }
      const t = m.parsed_date.getTime();
      if (t >= fromTime && t <= toTime) {
        filtered.push(m);
      }
    }

    return {
      filtered,
      unparseableCount
    };
  }

  /**
   * Find the scrollable container holding WhatsApp chat messages.
   */
  function findScrollContainer(doc = (typeof document !== "undefined" ? document : null)) {
    if (!doc) return null;

    const msg = doc.querySelector("div[data-id], .message-in, .message-out");
    if (msg) {
      let cur = msg.parentElement;
      while (cur && cur !== doc.body) {
        const style = (typeof window !== "undefined" && window.getComputedStyle) ? window.getComputedStyle(cur) : null;
        if (style && (style.overflowY === "auto" || style.overflowY === "scroll") && cur.scrollHeight > cur.clientHeight) {
          return cur;
        }
        cur = cur.parentElement;
      }
    }

    return (
      doc.querySelector("div[data-testid='conversation-panel-messages']") ||
      doc.querySelector("#main div[tabindex='0']") ||
      doc.querySelector("#main .copyable-area")?.parentElement ||
      doc.querySelector("[data-testid='conversation-panel-body']")
    );
  }

  /**
   * Extract chat title from header.
   */
  function extractChatTitle(doc = (typeof document !== "undefined" ? document : null)) {
    if (!doc) return "WhatsApp Web Conversation";
    const headerTitleEl = doc.querySelector(
      "header [data-testid='conversation-info-header'] span[dir='auto'], header [title], header span[dir='auto']"
    );
    if (headerTitleEl) {
      const attrTitle = typeof headerTitleEl.getAttribute === "function" ? headerTitleEl.getAttribute("title") : null;
      return attrTitle || headerTitleEl.innerText?.trim() || "WhatsApp Web Conversation";
    }
    return "WhatsApp Web Conversation";
  }

  /**
   * Parse a single message DOM node into a structured message object.
   */
  function parseMessageNode(el, chatTitle, dateOrder = "DD/MM/YYYY") {
    const isOutgoing = el.classList?.contains("message-out") || el.getAttribute("data-id")?.startsWith("true_");
    const platformMsgId = el.getAttribute("data-id") || null;

    const textEl = el.querySelector(".selectable-text, .copyable-text");
    const prePlainAttr = textEl
      ? textEl.getAttribute("data-pre-plain-text")
      : el.querySelector("[data-pre-plain-text]")?.getAttribute("data-pre-plain-text");

    let senderName = isOutgoing ? "You" : chatTitle;
    let rawTimestamp = null;

    if (prePlainAttr) {
      const match = prePlainAttr.match(/\[(.*?)\]\s*(.*?):\s*$/);
      if (match) {
        rawTimestamp = match[1].trim();
        senderName = isOutgoing ? "You" : match[2].trim() || chatTitle;
      }
    } else {
      const timeSpan = el.querySelector("[data-testid='msg-meta'] span, span[dir='auto']");
      if (timeSpan && timeSpan.innerText) {
        rawTimestamp = timeSpan.innerText.trim();
      }
    }

    let textContent = textEl ? textEl.innerText.trim() : "";

    let parsedDate = null;
    let isoTimestamp = null;
    if (rawTimestamp) {
      const p = DateParser.parseWhatsAppTimestamp(rawTimestamp, { dateOrder });
      if (p) {
        parsedDate = p.date;
        isoTimestamp = p.iso;
      }
    }

    let mediaType = "text";
    let mediaFilename = null;
    let hasMedia = false;

    const imgEl = el.querySelector("img[src]:not([alt='']):not([data-testid='status-image'])");
    if (imgEl && imgEl.src && !imgEl.src.includes("data:image/svg+xml")) {
      mediaType = "image";
      mediaFilename = "whatsapp_image.jpg";
      hasMedia = true;
      if (!textContent) textContent = "<image attached>";
    }

    const audioEl = el.querySelector("audio, [data-testid='audio-player']");
    if (audioEl) {
      mediaType = "voice";
      mediaFilename = "whatsapp_voice_note.ogg";
      hasMedia = true;
      if (!textContent) textContent = "<voice message attached>";
    }

    const docEl = el.querySelector("[data-testid='document-thumb'], span[title*='.pdf'], span[title*='.doc']");
    if (docEl) {
      mediaType = "document";
      const docName = docEl.getAttribute("title") || docEl.innerText?.trim() || "document.pdf";
      mediaFilename = docName;
      hasMedia = true;
      if (!textContent) textContent = `<document: ${docName}>`;
    }

    const msgKey = platformMsgId || generateSyntheticId(senderName, isoTimestamp, textContent);

    return {
      key: msgKey,
      platform_msg_id: platformMsgId,
      is_outgoing: isOutgoing,
      sender: senderName,
      text: textContent || `[${mediaType}]`,
      raw_timestamp: rawTimestamp,
      timestamp: isoTimestamp,
      parsed_date: parsedDate,
      has_media: hasMedia,
      media_type: mediaType,
      media_filename: mediaFilename
    };
  }

  function scanCurrentDOMMessages(container, chatTitle, dateOrder, messageMap) {
    const msgNodes = container.querySelectorAll("div[data-id], .message-in, .message-out");
    let newlyFound = 0;
    for (const node of msgNodes) {
      const item = parseMessageNode(node, chatTitle, dateOrder);
      if (item && item.key && !messageMap.has(item.key)) {
        messageMap.set(item.key, item);
        newlyFound++;
      }
    }
    return newlyFound;
  }

  /**
   * Execute bulk traversal based on user configuration.
   */
  async function runBulkCapture({
    container,
    doc = document,
    mode = "visible_to_newest",
    fromDate = null,
    toDate = null,
    dateOrder = "DD/MM/YYYY",
    onProgress = () => {},
    checkCancelled = () => false,
    maxScrollAttempts = 350,
    scrollDelayMs = 400
  }) {
    const initialChatTitle = extractChatTitle(doc);
    const messageMap = new Map();
    let completenessStatus = "complete";
    let partialReason = null;

    if (!container) {
      await DiagLogger.log("init", "ERR_SELECTOR", 0, "first_visible_anchor_not_found");
      return {
        chatTitle: initialChatTitle,
        messages: [],
        completenessStatus: "partial",
        partialReason: "first_visible_anchor_not_found",
        totalScanned: 0
      };
    }

    await DiagLogger.log("init", "START", 0, "ok");

    // Mode A: Visible to Newest
    if (mode === "visible_to_newest") {
      const containerRect = container.getBoundingClientRect();
      const allMsgs = container.querySelectorAll("div[data-id], .message-in, .message-out");
      let startItem = null;

      // Find first visible message in viewport
      for (const node of allMsgs) {
        const r = node.getBoundingClientRect();
        if (r.bottom >= containerRect.top + 5) {
          startItem = parseMessageNode(node, initialChatTitle, dateOrder);
          break;
        }
      }

      // If first visible anchor cannot be resolved, DO NOT include earlier rows and claim success
      if (!startItem) {
        await DiagLogger.log("scroll_down", "ERR_SELECTOR", 0, "first_visible_anchor_not_found");
        return {
          chatTitle: initialChatTitle,
          messages: [],
          completenessStatus: "partial",
          partialReason: "first_visible_anchor_not_found",
          totalScanned: 0
        };
      }

      // Collect initial visible messages from startItem downwards
      let foundStart = false;
      for (const node of allMsgs) {
        const item = parseMessageNode(node, initialChatTitle, dateOrder);
        if (!foundStart && item.key === startItem.key) {
          foundStart = true;
        }
        if (foundStart && item.key) {
          messageMap.set(item.key, item);
        }
      }

      // Stepwise scroll down to newest message
      let noChangeCount = 0;
      let lastScrollTop = -1;
      let bottomReached = false;

      for (let step = 0; step < maxScrollAttempts; step++) {
        if (checkCancelled()) {
          completenessStatus = "partial";
          partialReason = "cancelled_by_user";
          await DiagLogger.log("scroll_down", "CANCELLED", messageMap.size, "cancelled_by_user");
          break;
        }

        if (extractChatTitle(doc) !== initialChatTitle) {
          completenessStatus = "partial";
          partialReason = "chat_navigation_detected";
          await DiagLogger.log("scroll_down", "PARTIAL", messageMap.size, "chat_navigation_detected");
          break;
        }

        const isAtBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 10;
        if (isAtBottom && container.scrollTop === lastScrollTop) {
          noChangeCount++;
          if (noChangeCount >= 2) {
            bottomReached = true;
            break;
          }
        } else {
          noChangeCount = 0;
        }

        lastScrollTop = container.scrollTop;
        container.scrollTop = Math.min(container.scrollHeight, container.scrollTop + container.clientHeight * 0.75);
        await sleep(scrollDelayMs);

        scanCurrentDOMMessages(container, initialChatTitle, dateOrder, messageMap);
        onProgress({
          stage: "scrolling_down",
          messagesCollected: messageMap.size,
          isAtBottom
        });
      }

      if (!bottomReached && completenessStatus === "complete") {
        completenessStatus = "partial";
        partialReason = "scroll_attempts_exhausted";
        await DiagLogger.log("scroll_down", "PARTIAL", messageMap.size, "scroll_attempts_exhausted");
      }
    }

    // Mode B: Date Range (Inclusive FROM - TO)
    else if (mode === "date_range") {
      const fromTimestamp = fromDate ? new Date(fromDate).getTime() : -Infinity;
      const toTimestamp = toDate ? new Date(toDate).getTime() : Infinity;

      scanCurrentDOMMessages(container, initialChatTitle, dateOrder, messageMap);

      function getOldestDate() {
        let oldest = Infinity;
        for (const item of messageMap.values()) {
          if (item.parsed_date) {
            const t = item.parsed_date.getTime();
            if (t < oldest) oldest = t;
          }
        }
        return oldest === Infinity ? null : oldest;
      }

      function getNewestDate() {
        let newest = -Infinity;
        for (const item of messageMap.values()) {
          if (item.parsed_date) {
            const t = item.parsed_date.getTime();
            if (t > newest) newest = t;
          }
        }
        return newest === -Infinity ? null : newest;
      }

      // Upward traversal
      let oldestDate = getOldestDate();
      let topExhaustedCount = 0;
      let scrollUpSteps = 0;

      while ((oldestDate === null || oldestDate > fromTimestamp) && topExhaustedCount < 3 && scrollUpSteps < maxScrollAttempts) {
        if (checkCancelled()) {
          completenessStatus = "partial";
          partialReason = "cancelled_by_user";
          await DiagLogger.log("scroll_up", "CANCELLED", messageMap.size, "cancelled_by_user");
          break;
        }

        if (extractChatTitle(doc) !== initialChatTitle) {
          completenessStatus = "partial";
          partialReason = "chat_navigation_detected";
          await DiagLogger.log("scroll_up", "PARTIAL", messageMap.size, "chat_navigation_detected");
          break;
        }

        const prevScrollHeight = container.scrollHeight;
        container.scrollTop = 0;
        await sleep(scrollDelayMs + 200);

        const newlyAdded = scanCurrentDOMMessages(container, initialChatTitle, dateOrder, messageMap);
        oldestDate = getOldestDate();

        if (container.scrollTop === 0 && container.scrollHeight === prevScrollHeight && newlyAdded === 0) {
          topExhaustedCount++;
        } else {
          topExhaustedCount = 0;
        }

        scrollUpSteps++;

        onProgress({
          stage: "scrolling_up",
          messagesCollected: messageMap.size,
          oldestDateReached: oldestDate ? new Date(oldestDate).toISOString() : null
        });
      }

      if (topExhaustedCount >= 3 && oldestDate !== null && oldestDate > fromTimestamp) {
        if (completenessStatus === "complete") {
          completenessStatus = "partial";
          partialReason = "history_exhausted_before_from_bound";
          await DiagLogger.log("scroll_up", "PARTIAL", messageMap.size, "history_exhausted_before_from_bound");
        }
      } else if (scrollUpSteps >= maxScrollAttempts && oldestDate !== null && oldestDate > fromTimestamp) {
        if (completenessStatus === "complete") {
          completenessStatus = "partial";
          partialReason = "scroll_attempts_exhausted";
        }
      }

      // Downward traversal
      if (completenessStatus !== "partial" || partialReason === "history_exhausted_before_from_bound") {
        let bottomExhaustedCount = 0;
        let lastScroll = -1;
        let scrollDownSteps = 0;
        let newestDate = getNewestDate();

        while ((newestDate === null || newestDate < toTimestamp) && bottomExhaustedCount < 2 && scrollDownSteps < maxScrollAttempts) {
          if (checkCancelled()) {
            completenessStatus = "partial";
            partialReason = "cancelled_by_user";
            break;
          }

          scanCurrentDOMMessages(container, initialChatTitle, dateOrder, messageMap);
          newestDate = getNewestDate();

          const isAtBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 10;
          if (isAtBottom && container.scrollTop === lastScroll) {
            bottomExhaustedCount++;
            if (bottomExhaustedCount >= 2) break;
          } else {
            bottomExhaustedCount = 0;
          }

          lastScroll = container.scrollTop;
          container.scrollTop = Math.min(container.scrollHeight, container.scrollTop + container.clientHeight * 0.75);
          await sleep(scrollDelayMs);

          scrollDownSteps++;

          onProgress({
            stage: "scrolling_down",
            messagesCollected: messageMap.size
          });
        }

        if (bottomExhaustedCount >= 2 && newestDate !== null && newestDate < toTimestamp) {
          if (completenessStatus === "complete") {
            completenessStatus = "partial";
            partialReason = "history_exhausted_before_to_bound";
          }
        } else if (scrollDownSteps >= maxScrollAttempts && newestDate !== null && newestDate < toTimestamp) {
          if (completenessStatus === "complete") {
            completenessStatus = "partial";
            partialReason = "scroll_attempts_exhausted";
          }
        }
      }
    }

    let allCollected = Array.from(messageMap.values());
    let finalMessages = allCollected;

    if (mode === "visible_to_newest") {
      // Preserve all messages, but if any timestamp is unparseable/unverified, mark capture partial
      const hasUnverified = allCollected.some((m) => !m.parsed_date);
      if (hasUnverified && completenessStatus === "complete") {
        completenessStatus = "partial";
        partialReason = "unverified_timestamps_present";
      }
    } else if (mode === "date_range") {
      const { filtered, unparseableCount } = filterMessagesByDateRange(allCollected, fromDate, toDate);
      finalMessages = filtered;

      // If unparseable timestamps were encountered, mark partial honestly
      if (unparseableCount > 0 && completenessStatus === "complete") {
        completenessStatus = "partial";
        partialReason = "unparseable_timestamp_present";
      }
    }

    // Zero messages captured must be marked partial
    if (finalMessages.length === 0) {
      completenessStatus = "partial";
      partialReason = partialReason || "zero_messages_captured";
    }

    await DiagLogger.log(
      "summary",
      completenessStatus === "complete" ? "SUCCESS" : "PARTIAL",
      finalMessages.length,
      partialReason || "ok"
    );

    return {
      chatTitle: initialChatTitle,
      messages: finalMessages,
      completenessStatus,
      partialReason,
      totalScanned: allCollected.length
    };
  }

  /**
   * Post a bounded chunk of messages through the background service worker bridge with retries.
   */
  async function postChunkWithRetry({
    chatTitle,
    chunk,
    chunkIndex,
    totalChunks,
    isLastChunk,
    completenessStatus = "complete",
    partialReason = null,
    sessionId = null,
    dateOrder = "DD/MM/YYYY",
    maxRetries = 3,
    bridgeSender = null
  }) {
    let lastError = null;

    const payload = {
      action: "bridge_ingest_chunk",
      chatTitle,
      sessionId,
      chunkIndex,
      totalChunks,
      isLastChunk,
      completenessStatus,
      partialReason,
      dateOrder,
      chunk: chunk.map((m) => ({
        sender: m.sender,
        text: m.text,
        timestamp: m.timestamp,
        is_outgoing: m.is_outgoing,
        platform_msg_id: m.platform_msg_id,
        has_media: m.has_media,
        media_type: m.media_type,
        media_filename: m.media_filename
      }))
    };

    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        let res = null;

        if (typeof bridgeSender === "function") {
          res = await bridgeSender(payload);
        } else if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.sendMessage) {
          res = await new Promise((resolve) => {
            chrome.runtime.sendMessage(payload, (resp) => {
              if (chrome.runtime.lastError) {
                resolve({ success: false, error_code: "RUNTIME_ERROR", error: chrome.runtime.lastError.message });
              } else {
                resolve(resp || { success: false, error_code: "EMPTY_RESPONSE" });
              }
            });
          });
        } else {
          return { success: false, error_code: "NO_BRIDGE", error: "No runtime bridge available" };
        }

        if (res && res.success) {
          return res;
        } else {
          lastError = new Error(res?.error || res?.error_code || "Bridge error");
          if (res?.error_code === "PAYLOAD_TOO_LARGE" || res?.error_code === "UNAUTHORIZED_SENDER" || res?.error_code === "DISALLOWED_ENDPOINT") {
            return {
              success: false,
              error_code: res.error_code,
              error: res.error,
              partialReason: res.error_code === "PAYLOAD_TOO_LARGE" ? "payload_too_large" : "chunk_ingest_failed"
            };
          }
        }
      } catch (err) {
        lastError = err;
      }

      if (attempt < maxRetries) {
        await sleep(attempt * 400);
      }
    }

    return { success: false, error_code: "CHUNK_FAILED", error: lastError?.message || "Failed after retries" };
  }

  return {
    sleep,
    chunkArray,
    generateSyntheticId,
    filterMessagesByDateRange,
    findScrollContainer,
    extractChatTitle,
    parseMessageNode,
    scanCurrentDOMMessages,
    runBulkCapture,
    postChunkWithRetry
  };
});
