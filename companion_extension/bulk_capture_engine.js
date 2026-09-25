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

  function isOlderMessagesText(text) {
    if (!text || typeof text !== "string") return false;
    const trimmed = text.trim();
    return (
      /get older messages/i.test(trimmed) ||
      /click here to get older messages/i.test(trimmed) ||
      /تحميل الرسائل السابقة/i.test(trimmed) ||
      /الحصول على الرسائل السابقة/i.test(trimmed) ||
      /رسائل أقدم/i.test(trimmed)
    );
  }

  /**
   * Detect visible "Click here to get older messages from your phone" control in WhatsApp Web UI.
   * Selects the actual interactive button (or closest actionable ancestor), never a broad ancestor div.
   */
  function findOlderMessagesButton(container, doc = (typeof document !== "undefined" ? document : null)) {
    const roots = [container, doc].filter(r => r && typeof r.querySelectorAll === "function");
    for (const root of roots) {
      // 0. If root itself is the actionable button
      const rootText = (root.innerText || root.textContent || "").trim();
      const rootRole = typeof root.getAttribute === "function" ? root.getAttribute("role") : null;
      const rootTag = (root.tagName || "").toUpperCase();
      if ((rootTag === "BUTTON" || rootRole === "button") && isOlderMessagesText(rootText)) {
        return root;
      }

      // 1. Check explicit interactive buttons or role="button" elements
      const actionableCandidates = root.querySelectorAll("button, [role='button']");
      for (const el of actionableCandidates) {
        const text = (el.innerText || el.textContent || "").trim();
        if (isOlderMessagesText(text)) {
          return el;
        }
      }

      // 2. Check text elements (span, p, a) containing the phrase and find their closest actionable ancestor
      const textCandidates = root.querySelectorAll("span, p, a");
      for (const el of textCandidates) {
        const text = (el.innerText || el.textContent || "").trim();
        if (isOlderMessagesText(text)) {
          if (typeof el.closest === "function") {
            const btn = el.closest("button, [role='button'], [tabindex='0']");
            if (btn) return btn;
          }
          const role = typeof el.getAttribute === "function" ? el.getAttribute("role") : null;
          const tagName = (el.tagName || "").toUpperCase();
          if (tagName === "BUTTON" || role === "button") {
            return el;
          }
        }
      }
    }
    return null;
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

  const UNSUPPORTED_EXTENSIONS = new Set([
    ".exe", ".bat", ".cmd", ".sh", ".bin", ".msi", ".dll", ".com", ".vbs", ".ps1", ".scr", ".pif"
  ]);

  function getExtension(filename) {
    if (!filename) return "";
    const idx = filename.lastIndexOf(".");
    return idx !== -1 ? filename.substring(idx).toLowerCase() : "";
  }

  function sliceIntoChunks(uint8Array, chunkSize = 256 * 1024) {
    if (!uint8Array) return [];
    const chunks = [];
    for (let i = 0; i < uint8Array.byteLength; i += chunkSize) {
      chunks.push(uint8Array.subarray(i, Math.min(i + chunkSize, uint8Array.byteLength)));
    }
    return chunks;
  }

  function uint8ArrayToBase64(uint8) {
    if (!uint8 || uint8.byteLength === 0) return "";
    let binary = "";
    const len = uint8.byteLength;
    const chunkSize = 0x8000;
    for (let i = 0; i < len; i += chunkSize) {
      binary += String.fromCharCode.apply(null, uint8.subarray(i, Math.min(i + chunkSize, len)));
    }
    return btoa(binary);
  }

  async function calculateSha256(buffer) {
    if (typeof crypto !== "undefined" && crypto.subtle && typeof crypto.subtle.digest === "function") {
      try {
        const hashBuffer = await crypto.subtle.digest("SHA-256", buffer);
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        return hashArray.map((b) => b.toString(16).padStart(2, "0")).join("");
      } catch (e) {}
    }
    return null;
  }

  /**
   * Helper to find download button inside an element or near it
   */
  function findDownloadControl(container) {
    if (!container || typeof container.querySelector !== "function") return null;
    return (
      container.querySelector("[data-testid='download'], [data-icon='download'], [data-testid='audio-download'], button[aria-label*='download' i], button[aria-label*='تحميل' i], a[download]") ||
      null
    );
  }

  /**
   * Detect all attachments on a message element (audio, video, document, image, other).
   * Supports multiple attachments per message and identifies preview/thumbnail vs downloadable original.
   */
  function detectMessageAttachments(el, chatTitle) {
    if (!el || (typeof el.querySelector !== "function" && typeof el.querySelectorAll !== "function")) return [];
    const attachments = [];

    // 1. Audio / Voice Note Detection
    const audioNodes = el.querySelectorAll ? el.querySelectorAll("audio, [data-testid='audio-player'], [data-testid='ptt-waveform'], span[data-icon='ptt-play'], span[data-icon='audio-play']") : [];
    if (audioNodes && audioNodes.length > 0) {
      for (let i = 0; i < audioNodes.length; i++) {
        const aNode = audioNodes[i];
        if (aNode.tagName !== "AUDIO" && aNode.closest && aNode.closest("audio, [data-testid='audio-player']")) {
          continue;
        }
        const audioEl = aNode.tagName === "AUDIO" ? aNode : (aNode.querySelector ? aNode.querySelector("audio") : null);
        const blobUrl = audioEl && audioEl.src && audioEl.src.startsWith("blob:") ? audioEl.src : null;
        const dlBtn = findDownloadControl(aNode.parentElement || aNode);

        let initialStatus = "unavailable";
        if (blobUrl) {
          initialStatus = "available";
        } else if (dlBtn) {
          initialStatus = "unavailable";
        }

        attachments.push({
          id: `att_audio_${attachments.length + 1}`,
          file_type: "audio",
          file_name: `voice_note_${attachments.length + 1}.ogg`,
          mime_type: "audio/ogg",
          blob_url: blobUrl,
          is_thumbnail_only: false,
          download_el: dlBtn,
          container_el: aNode,
          attachment_status: initialStatus
        });
      }
    }

    // 2. Video Detection
    const videoNodes = el.querySelectorAll ? el.querySelectorAll("video, [data-testid='video-content'], [data-testid='media-video']") : [];
    if (videoNodes && videoNodes.length > 0) {
      for (let i = 0; i < videoNodes.length; i++) {
        const vNode = videoNodes[i];
        if (vNode.tagName !== "VIDEO" && vNode.closest && vNode.closest("video, [data-testid='video-content']")) {
          continue;
        }
        const vidEl = vNode.tagName === "VIDEO" ? vNode : (vNode.querySelector ? vNode.querySelector("video") : null);
        const blobUrl = vidEl && vidEl.src && vidEl.src.startsWith("blob:") ? vidEl.src : null;
        const dlBtn = findDownloadControl(vNode.parentElement || vNode);

        let isThumbOnly = false;
        let initialStatus = "unavailable";
        if (blobUrl) {
          initialStatus = "available";
        } else if (vNode.querySelector && vNode.querySelector("img[src]")) {
          isThumbOnly = true;
          initialStatus = "preview-only";
        }

        attachments.push({
          id: `att_video_${attachments.length + 1}`,
          file_type: "video",
          file_name: `whatsapp_video_${attachments.length + 1}.mp4`,
          mime_type: "video/mp4",
          blob_url: blobUrl,
          is_thumbnail_only: isThumbOnly,
          download_el: dlBtn,
          container_el: vNode,
          attachment_status: initialStatus
        });
      }
    }

    // 3. Document Detection
    const docNodes = el.querySelectorAll ? el.querySelectorAll("[data-testid='document-thumb'], [data-icon='document'], span[title*='.'], div[title*='.']") : [];
    if (docNodes && docNodes.length > 0) {
      for (let i = 0; i < docNodes.length; i++) {
        const dNode = docNodes[i];
        const titleAttr = (typeof dNode.getAttribute === "function" ? dNode.getAttribute("title") : null) || dNode.innerText || "";
        const cleanTitle = titleAttr.trim();

        const isDocThumb = (typeof dNode.getAttribute === "function" && dNode.getAttribute("data-testid") === "document-thumb");
        const hasDocExt = /\.(pdf|docx?|xlsx?|pptx?|txt|zip|rar|csv|json|xml|html?|tar|gz|7z)$/i.test(cleanTitle);

        if (isDocThumb || hasDocExt) {
          const docName = hasDocExt ? cleanTitle : (cleanTitle || `document_${attachments.length + 1}.pdf`);
          const dlBtn = findDownloadControl(dNode.parentElement || dNode);
          const anchor = dNode.tagName === "A" ? dNode : (dNode.querySelector ? dNode.querySelector("a[href^='blob:']") : null);
          const blobUrl = anchor && anchor.href && anchor.href.startsWith("blob:") ? anchor.href : null;

          let initialStatus = "unavailable";
          if (UNSUPPORTED_EXTENSIONS.has(getExtension(docName))) {
            initialStatus = "unsupported";
          } else if (blobUrl) {
            initialStatus = "available";
          } else if (dlBtn) {
            initialStatus = "unavailable";
          }

          let mimeType = "application/octet-stream";
          if (docName.endsWith(".pdf")) mimeType = "application/pdf";
          else if (docName.endsWith(".docx")) mimeType = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
          else if (docName.endsWith(".xlsx")) mimeType = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
          else if (docName.endsWith(".zip")) mimeType = "application/zip";
          else if (docName.endsWith(".txt")) mimeType = "text/plain";

          attachments.push({
            id: `att_doc_${attachments.length + 1}`,
            file_type: "document",
            file_name: docName,
            mime_type: mimeType,
            blob_url: blobUrl,
            is_thumbnail_only: false,
            download_el: dlBtn,
            container_el: dNode,
            attachment_status: initialStatus
          });
        }
      }
    }

    // 4. Image Detection (excluding emoji, avatars, SVG)
    const imgNodes = el.querySelectorAll ? el.querySelectorAll("img[src]") : [];
    if (imgNodes && imgNodes.length > 0) {
      for (let i = 0; i < imgNodes.length; i++) {
        const img = imgNodes[i];
        const src = img.src || (typeof img.getAttribute === "function" ? img.getAttribute("src") : "") || "";
        if (!src || src.includes("data:image/svg+xml")) continue;
        if (typeof img.getAttribute === "function" && img.getAttribute("data-testid") === "status-image") continue;
        if (src.includes("/emoji/") || src.includes("emoji")) continue;
        if (img.classList && img.classList.contains("emojitext")) continue;
        if (typeof img.getAttribute === "function" && img.getAttribute("alt") === "emoji") continue;

        if (img.closest && (img.closest("video, [data-testid='video-content'], [data-testid='document-thumb']"))) {
          continue;
        }

        const dlBtn = findDownloadControl(img.parentElement || img);
        const isBlob = src.startsWith("blob:");
        const isDataUri = src.startsWith("data:image/");

        let isThumbOnly = false;
        let initialStatus = "unavailable";

        if (isDataUri) {
          isThumbOnly = true;
          initialStatus = "preview-only";
        } else if (img.classList && (img.classList.contains("thumbnail") || img.classList.contains("preview") || (typeof img.getAttribute === "function" && img.getAttribute("data-thumb") === "true"))) {
          isThumbOnly = true;
          initialStatus = "preview-only";
        } else if (dlBtn) {
          isThumbOnly = true;
          initialStatus = isBlob ? "preview-only" : "unavailable";
        } else if (isBlob) {
          if (typeof img.getAttribute === "function" && (img.getAttribute("data-preview") === "true" || img.getAttribute("data-thumb") === "true")) {
            isThumbOnly = true;
            initialStatus = "preview-only";
          } else {
            initialStatus = "available";
          }
        } else if (src.startsWith("http")) {
          initialStatus = "available";
        }

        attachments.push({
          id: `att_img_${attachments.length + 1}`,
          file_type: "image",
          file_name: `whatsapp_image_${attachments.length + 1}.jpg`,
          mime_type: "image/jpeg",
          blob_url: isBlob ? src : (isDataUri ? src : null),
          is_thumbnail_only: isThumbOnly,
          download_el: dlBtn,
          container_el: img,
          attachment_status: initialStatus
        });
      }
    }

    return attachments;
  }

  /**
   * Captures original bytes of an attachment while DOM is mounted.
   * Truthfully distinguishes saved-original, preview-only, unavailable, expired, too-large, unsupported, failed.
   */
  async function captureAttachmentOriginalBytes(att, {
    maxBytes = 50 * 1024 * 1024,
    timeoutMs = 3000,
    checkCancelled = () => false,
    fetchFn = (typeof fetch !== "undefined" ? fetch : null)
  } = {}) {
    if (checkCancelled()) {
      return { status: "failed", error: "cancelled" };
    }

    if (UNSUPPORTED_EXTENSIONS.has(getExtension(att.file_name))) {
      return { status: "unsupported", file_name: att.file_name };
    }

    let targetUrl = att.blob_url;

    // Activate visible page download control if exposed and no direct blob is ready
    if (!targetUrl && att.download_el && typeof att.download_el.click === "function") {
      try {
        att.download_el.click();
        const start = Date.now();
        while (Date.now() - start < timeoutMs) {
          if (checkCancelled()) return { status: "failed", error: "cancelled" };
          await sleep(250);
          if (att.container_el && typeof att.container_el.querySelector === "function") {
            const elWithSrc = att.container_el.querySelector("video[src^='blob:'], audio[src^='blob:'], img[src^='blob:'], a[href^='blob:']");
            if (elWithSrc) {
              targetUrl = elWithSrc.src || elWithSrc.href;
              if (targetUrl && targetUrl.startsWith("blob:")) break;
            }
          }
        }
      } catch (e) {
        return { status: "failed", file_name: att.file_name, error: e.message };
      }
    }

    if (!targetUrl) {
      if (att.is_thumbnail_only) {
        return { status: "preview-only", file_name: att.file_name };
      }
      return { status: "unavailable", file_name: att.file_name };
    }

    // Handle data: URIs (e.g. preview data URL)
    if (targetUrl.startsWith("data:")) {
      try {
        const parts = targetUrl.split(",");
        const meta = parts[0] || "";
        const rawBase64 = parts[1] || "";
        const mimeMatch = meta.match(/:(.*?);/);
        const mime = mimeMatch ? mimeMatch[1] : att.mime_type;
        const binaryStr = atob(rawBase64);
        const len = binaryStr.length;
        if (len > maxBytes) {
          return { status: "too-large", file_size: len, file_name: att.file_name };
        }
        const uint8 = new Uint8Array(len);
        for (let i = 0; i < len; i++) {
          uint8[i] = binaryStr.charCodeAt(i);
        }
        const sha = await calculateSha256(uint8.buffer);
        const finalStatus = (att.provenance === "full_original" && !att.is_thumbnail_only) ? "saved-original" : "preview-only";
        return {
          status: finalStatus,
          bytes: uint8,
          file_size: len,
          sha256: sha,
          file_name: att.file_name,
          file_type: att.file_type,
          mime_type: mime
        };
      } catch (e) {
        return { status: "failed", file_name: att.file_name, error: e.message };
      }
    }

    // Handle blob: or http: URLs
    if (fetchFn) {
      try {
        const res = await fetchFn(targetUrl);
        if (!res.ok) {
          return { status: "expired", file_name: att.file_name };
        }
        const blob = await res.blob();
        if (blob.size === 0) {
          return { status: "unavailable", file_name: att.file_name };
        }
        if (blob.size > maxBytes) {
          return { status: "too-large", file_size: blob.size, file_name: att.file_name };
        }
        const arrayBuf = await blob.arrayBuffer();
        const uint8 = new Uint8Array(arrayBuf);
        const sha = await calculateSha256(arrayBuf);
        const finalStatus = att.is_thumbnail_only ? "preview-only" : "saved-original";
        return {
          status: finalStatus,
          bytes: uint8,
          file_size: blob.size,
          sha256: sha,
          file_name: att.file_name,
          file_type: att.file_type,
          mime_type: blob.type || att.mime_type
        };
      } catch (err) {
        return { status: "expired", file_name: att.file_name, error: err.message };
      }
    }

    return { status: "unavailable", file_name: att.file_name };
  }

  /**
   * Upload captured media bytes separately from 50-message JSON ingest chunks.
   * Direct upload for <= 2MB, chunked session for larger files.
   * Cleans up in-memory bytes immediately after transfer.
   */
  async function uploadCapturedMediaItem({
    attachment,
    attachmentPosition = null,
    conversationId = null,
    messageId = null,
    platformMsgId = null,
    messageKey = null,
    sessionId = null,
    confirmTargetMerge = false,
    chatTitle = null,
    bridgeSender = null,
    maxDirectBytes = 2 * 1024 * 1024,
    chunkSize = 512 * 1024
  }) {
    if (!attachment || !attachment.bytes) {
      return { success: false, status: attachment?.attachment_status || "unavailable" };
    }

    // P0 3: Never upload or promote a preview / thumbnail into saved-original!
    if (attachment.attachment_status !== "saved-original") {
      return { success: false, status: attachment.attachment_status };
    }

    const sender = bridgeSender || (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.sendMessage ?
      (p) => new Promise((resolve) => {
        chrome.runtime.sendMessage(p, (resp) => resolve(resp || { success: false }));
      }) : null);

    if (!sender) {
      return { success: false, status: "failed", error: "No runtime bridge available" };
    }

    const bytes = attachment.bytes;
    const fileSize = attachment.file_size || bytes.byteLength;

    if (fileSize <= maxDirectBytes) {
      const b64 = uint8ArrayToBase64(bytes);
      const res = await sender({
        action: "bridge_media_upload",
        conversationId,
        messageId,
        platformMsgId,
        messageKey: messageKey || platformMsgId,
        sessionId,
        attachmentPosition,
        confirmTargetMerge,
        chatTitle,
        fileName: attachment.file_name,
        fileType: attachment.file_type,
        mimeType: attachment.mime_type,
        mediaBase64: b64,
        sha256: attachment.sha256,
        attachmentStatus: attachment.attachment_status
      });

      attachment.bytes = null;

      if (res && res.success) {
        attachment.attachment_status = "saved-original";
        return { success: true, status: "saved-original", data: res.data };
      } else {
        attachment.attachment_status = "failed";
        return { success: false, status: "failed", error: res?.error || "Direct upload failed" };
      }
    }

    // Chunked session upload for larger media (> 2MB)
    // P0 2: Distinct upload session ID for each attachment
    const uploadSessionId = "media_upload_" + Date.now() + "_" + Math.random().toString(36).substring(2, 9);
    const chunks = sliceIntoChunks(bytes, chunkSize);

    const startRes = await sender({
      action: "bridge_media_session_start",
      sessionId: uploadSessionId,
      captureSessionId: sessionId,
      capture_session_id: sessionId,
      conversationId,
      messageId,
      platformMsgId,
      messageKey: messageKey || platformMsgId,
      attachmentPosition,
      confirmTargetMerge,
      chatTitle,
      fileName: attachment.file_name,
      fileType: attachment.file_type,
      mimeType: attachment.mime_type,
      totalBytes: fileSize,
      totalChunks: chunks.length,
      sha256: attachment.sha256,
      attachmentStatus: attachment.attachment_status
    });

    if (!startRes || !startRes.success) {
      attachment.bytes = null;
      attachment.attachment_status = "failed";
      return { success: false, status: "failed", error: startRes?.error || "Session start failed" };
    }

    for (let cIdx = 0; cIdx < chunks.length; cIdx++) {
      const chunkB64 = uint8ArrayToBase64(chunks[cIdx]);
      const chunkRes = await sender({
        action: "bridge_media_session_chunk",
        sessionId: uploadSessionId,
        chunkIndex: cIdx,
        chunkBase64: chunkB64
      });

      if (!chunkRes || !chunkRes.success) {
        attachment.bytes = null;
        attachment.attachment_status = "failed";
        return { success: false, status: "failed", error: chunkRes?.error || `Chunk ${cIdx} failed` };
      }
    }

    const finishRes = await sender({
      action: "bridge_media_session_finish",
      sessionId: uploadSessionId
    });

    attachment.bytes = null;

    if (finishRes && finishRes.success) {
      attachment.attachment_status = "saved-original";
      return { success: true, status: "saved-original", data: finishRes.data };
    } else {
      attachment.attachment_status = "failed";
      return { success: false, status: "failed", error: finishRes?.error || "Session finish failed" };
    }
  }

  /**
   * Parse a single message DOM node into a structured message object with rich attachments.
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
    let attachmentStatus = "none";

    const detectedAttachments = detectMessageAttachments(el, chatTitle);

    if (detectedAttachments && detectedAttachments.length > 0) {
      hasMedia = true;
      const primary = detectedAttachments[0];
      mediaType = primary.file_type === "audio" ? "voice" : primary.file_type;
      mediaFilename = primary.file_name;
      attachmentStatus = primary.attachment_status || "available";

      if (!textContent) {
        if (mediaType === "voice" || mediaType === "audio") {
          textContent = "<voice message attached>";
        } else if (mediaType === "image") {
          textContent = "<image attached>";
        } else if (mediaType === "video") {
          textContent = "<video attached>";
        } else if (mediaType === "document") {
          textContent = `<document: ${mediaFilename}>`;
        } else {
          textContent = `<attachment: ${mediaFilename}>`;
        }
      }
    } else {
      // Legacy fallback inspection
      const imgEl = el.querySelector("img[src]:not([alt='']):not([data-testid='status-image'])");
      if (imgEl && imgEl.src && !imgEl.src.includes("data:image/svg+xml")) {
        mediaType = "image";
        mediaFilename = "whatsapp_image.jpg";
        hasMedia = true;
        attachmentStatus = "available";
        if (!textContent) textContent = "<image attached>";
      }

      const audioEl = el.querySelector("audio, [data-testid='audio-player']");
      if (audioEl) {
        mediaType = "voice";
        mediaFilename = "whatsapp_voice_note.ogg";
        hasMedia = true;
        attachmentStatus = "available";
        if (!textContent) textContent = "<voice message attached>";
      }

      const docEl = el.querySelector("[data-testid='document-thumb'], span[title*='.pdf'], span[title*='.doc']");
      if (docEl) {
        mediaType = "document";
        const docName = docEl.getAttribute("title") || docEl.innerText?.trim() || "document.pdf";
        mediaFilename = docName;
        hasMedia = true;
        attachmentStatus = "available";
        if (!textContent) textContent = `<document: ${docName}>`;
      }
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
      media_filename: mediaFilename,
      attachment_status: attachmentStatus,
      attachments: detectedAttachments
    };
  }

  async function scanCurrentDOMMessages(container, chatTitle, dateOrder, messageMap, options = {}) {
    const {
      captureMedia = false,
      onMediaCaptured = null,
      bridgeSender = null,
      targetConversationId = null,
      confirmTargetMerge = false,
      sessionId = null,
      fetchFn = (typeof fetch !== "undefined" ? fetch : null),
      checkCancelled = () => false
    } = options;

    const msgNodes = container.querySelectorAll("div[data-id], .message-in, .message-out");
    let newlyFound = 0;
    for (const node of msgNodes) {
      const item = parseMessageNode(node, chatTitle, dateOrder);
      if (item && item.key && !messageMap.has(item.key)) {
        if (captureMedia && item.has_media && item.attachments && item.attachments.length > 0) {
          for (let attIdx = 0; attIdx < item.attachments.length; attIdx++) {
            const att = item.attachments[attIdx];
            const captured = await captureAttachmentOriginalBytes(att, { checkCancelled, fetchFn });
            att.attachment_status = captured.status;
            att.sha256 = captured.sha256 || null;
            att.file_size = captured.file_size || 0;
            if (captured.status === "saved-original" && captured.bytes) {
              att.bytes = captured.bytes;
              await uploadCapturedMediaItem({
                attachment: att,
                attachmentPosition: attIdx + 1,
                conversationId: targetConversationId,
                confirmTargetMerge,
                platformMsgId: item.platform_msg_id,
                messageKey: item.key,
                sessionId,
                chatTitle,
                bridgeSender
              });
            }
            if (typeof onMediaCaptured === "function") {
              onMediaCaptured(att);
            }
          }
          item.attachment_status = item.attachments[0].attachment_status;
        }
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
    sessionId = null,
    targetConversationId = null,
    confirmTargetMerge = false,
    captureMedia = false,
    bridgeSender = null,
    onProgress = () => {},
    checkCancelled = () => false,
    fetchFn = (typeof fetch !== "undefined" ? fetch : null),
    maxScrollAttempts = 350,
    scrollDelayMs = 400
  }) {
    const initialChatTitle = extractChatTitle(doc);
    const messageMap = new Map();
    const captureSessionId = sessionId || ("bulk_" + Date.now() + "_" + Math.random().toString(36).substring(2, 8));
    let completenessStatus = "complete";
    let partialReason = null;

    const attachmentStats = {
      totalDetected: 0,
      savedOriginal: 0,
      previewOnly: 0,
      unavailable: 0,
      expired: 0,
      tooLarge: 0,
      failed: 0,
      unsupported: 0
    };

    const scanOpts = {
      captureMedia,
      targetConversationId,
      confirmTargetMerge,
      sessionId: captureSessionId,
      chatTitle: initialChatTitle,
      bridgeSender,
      checkCancelled,
      fetchFn,
      onMediaCaptured: (att) => {
        attachmentStats.totalDetected++;
        const s = att.attachment_status;
        if (s === "saved-original") attachmentStats.savedOriginal++;
        else if (s === "preview-only") attachmentStats.previewOnly++;
        else if (s === "unavailable") attachmentStats.unavailable++;
        else if (s === "expired") attachmentStats.expired++;
        else if (s === "too-large") attachmentStats.tooLarge++;
        else if (s === "unsupported") attachmentStats.unsupported++;
        else if (s === "failed") attachmentStats.failed++;
      }
    };

    if (!container) {
      await DiagLogger.log("init", "ERR_SELECTOR", 0, "first_visible_anchor_not_found");
      return {
        chatTitle: initialChatTitle,
        messages: [],
        completenessStatus: "partial",
        partialReason: "first_visible_anchor_not_found",
        totalScanned: 0,
        attachmentStats: { ...attachmentStats }
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
          totalScanned: 0,
          attachmentStats: { ...attachmentStats }
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
          if (captureMedia && item.has_media && item.attachments && item.attachments.length > 0) {
            for (let attIdx = 0; attIdx < item.attachments.length; attIdx++) {
              const att = item.attachments[attIdx];
              const captured = await captureAttachmentOriginalBytes(att, { checkCancelled, fetchFn });
              att.attachment_status = captured.status;
              att.sha256 = captured.sha256 || null;
              att.file_size = captured.file_size || 0;
              if (captured.status === "saved-original" && captured.bytes) {
                att.bytes = captured.bytes;
                await uploadCapturedMediaItem({
                  attachment: att,
                  attachmentPosition: attIdx + 1,
                  conversationId: targetConversationId,
                  confirmTargetMerge,
                  platformMsgId: item.platform_msg_id,
                  messageKey: item.key,
                  sessionId: captureSessionId,
                  chatTitle: initialChatTitle,
                  bridgeSender
                });
              }
              scanOpts.onMediaCaptured(att);
            }
            item.attachment_status = item.attachments[0].attachment_status;
          }
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

        await scanCurrentDOMMessages(container, initialChatTitle, dateOrder, messageMap, scanOpts);
        onProgress({
          stage: "scrolling_down",
          messagesCollected: messageMap.size,
          attachmentStats: { ...attachmentStats },
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

      await scanCurrentDOMMessages(container, initialChatTitle, dateOrder, messageMap, scanOpts);

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
      let totalOlderBtnClicks = 0;
      const MAX_TOTAL_OLDER_CLICKS = 30;

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

        let newlyAdded = await scanCurrentDOMMessages(container, initialChatTitle, dateOrder, messageMap, scanOpts);
        oldestDate = getOldestDate();

        // P0 4: WhatsApp Web live UI has visible button 'Click here to get older messages from your phone.'
        // Date-range traversal must detect and activate this control repeatedly with bounded attempts/time.
        let olderBtn = findOlderMessagesButton(container, doc);
        let olderClicksThisCycle = 0;
        const maxOlderClicksPerCycle = 10;
        let consecutiveZeroYieldClicks = 0;

        while (
          olderBtn &&
          (oldestDate === null || oldestDate > fromTimestamp) &&
          olderClicksThisCycle < maxOlderClicksPerCycle &&
          totalOlderBtnClicks < MAX_TOTAL_OLDER_CLICKS
        ) {
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

          try {
            if (typeof olderBtn.click === "function") {
              olderBtn.click();
              olderClicksThisCycle++;
              totalOlderBtnClicks++;
            }
            await DiagLogger.log("scroll_up", "STEP", messageMap.size, "clicked_older_messages_button");
          } catch (e) {
            // click failed
            break;
          }

          // Bounded wait for new rows to mount in DOM
          let waitStep = 0;
          let addedInClick = 0;
          while (waitStep < 10) {
            await sleep(Math.min(scrollDelayMs, 300));
            if (checkCancelled()) {
              completenessStatus = "partial";
              partialReason = "cancelled_by_user";
              break;
            }
            if (extractChatTitle(doc) !== initialChatTitle) {
              completenessStatus = "partial";
              partialReason = "chat_navigation_detected";
              break;
            }
            container.scrollTop = 0;
            const addedNow = await scanCurrentDOMMessages(container, initialChatTitle, dateOrder, messageMap, scanOpts);
            if (addedNow > 0) {
              addedInClick += addedNow;
              newlyAdded += addedNow;
              break;
            }
            waitStep++;
          }

          if (completenessStatus === "partial") break;

          if (addedInClick === 0) {
            consecutiveZeroYieldClicks++;
            if (consecutiveZeroYieldClicks >= 2) {
              break;
            }
          } else {
            consecutiveZeroYieldClicks = 0;
          }

          oldestDate = getOldestDate();

          onProgress({
            stage: "scrolling_up",
            messagesCollected: messageMap.size,
            attachmentStats: { ...attachmentStats },
            oldestDateReached: oldestDate ? new Date(oldestDate).toISOString() : null
          });

          // Check if button reappeared after click (or remained)
          olderBtn = findOlderMessagesButton(container, doc);
        }

        const olderBtnStillPresent = Boolean(findOlderMessagesButton(container, doc));

        if (container.scrollTop === 0 && container.scrollHeight === prevScrollHeight && newlyAdded === 0 && !olderBtnStillPresent) {
          topExhaustedCount++;
        } else if (newlyAdded > 0) {
          topExhaustedCount = 0;
        } else {
          topExhaustedCount = 0;
        }

        scrollUpSteps++;

        onProgress({
          stage: "scrolling_up",
          messagesCollected: messageMap.size,
          attachmentStats: { ...attachmentStats },
          oldestDateReached: oldestDate ? new Date(oldestDate).toISOString() : null
        });
      }

      // P0 4: Never claim complete just because scrollTop reached 0 while the older-message control remains
      const unexhaustedOlderBtn = findOlderMessagesButton(container, doc);
      if (unexhaustedOlderBtn && (oldestDate === null || oldestDate > fromTimestamp)) {
        if (completenessStatus === "complete") {
          completenessStatus = "partial";
          partialReason = "older_messages_button_unexhausted";
          await DiagLogger.log("scroll_up", "PARTIAL", messageMap.size, "older_messages_button_unexhausted");
        }
      } else if (topExhaustedCount >= 3 && oldestDate !== null && oldestDate > fromTimestamp) {
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

          await scanCurrentDOMMessages(container, initialChatTitle, dateOrder, messageMap, scanOpts);
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
            messagesCollected: messageMap.size,
            attachmentStats: { ...attachmentStats }
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
      totalScanned: allCollected.length,
      attachmentStats: { ...attachmentStats }
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
    targetConversationId = null,
    confirmTargetMerge = false,
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
      targetConversationId: targetConversationId || null,
      confirmTargetMerge: Boolean(confirmTargetMerge),
      chunk: chunk.map((m) => ({
        sender: m.sender,
        text: m.text,
        timestamp: m.timestamp,
        is_outgoing: m.is_outgoing,
        platform_msg_id: m.platform_msg_id || m.key,
        has_media: m.has_media,
        media_type: m.media_type,
        media_filename: m.media_filename,
        attachment_status: m.attachment_status || "none",
        attachments: m.attachments ? m.attachments.map((a, aIdx) => ({
          file_name: a.file_name,
          file_type: a.file_type,
          mime_type: a.mime_type,
          file_size: a.file_size || 0,
          sha256: a.sha256 || null,
          attachment_position: a.attachment_position || (aIdx + 1),
          attachment_status: a.attachment_status || "none"
        })) : []
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
    findOlderMessagesButton,
    extractChatTitle,
    parseMessageNode,
    detectMessageAttachments,
    sliceIntoChunks,
    uint8ArrayToBase64,
    calculateSha256,
    captureAttachmentOriginalBytes,
    uploadCapturedMediaItem,
    scanCurrentDOMMessages,
    runBulkCapture,
    postChunkWithRetry
  };
});
