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

  const INVALID_CHAT_TITLES = new Set([
    "profile details",
    "تفاصيل الملف الشخصي",
    "معلومات جهة الاتصال",
    "contact info",
    "معلومات المجموعة",
    "group info"
  ]);

  function isInvalidChatTitle(title) {
    if (!title || typeof title !== "string") return true;
    const normalized = title.trim().toLowerCase();
    if (INVALID_CHAT_TITLES.has(normalized)) return true;
    if (normalized.startsWith("profile details") || normalized.startsWith("تفاصيل الملف الشخصي")) return true;
    return false;
  }

  /**
   * Extract chat title from header, strictly rejecting UI controls like "Profile details".
   */
  function extractChatTitle(doc = (typeof document !== "undefined" ? document : null)) {
    if (!doc) return "WhatsApp Web Conversation";

    // 1. Primary: Specific title elements in conversation header
    const specificSelectors = [
      "header[data-testid='conversation-header'] [data-testid='conversation-info-header-chat-title']",
      "[data-testid='conversation-info-header-chat-title']",
      "header [data-testid='conversation-info-header'] span[dir='auto']",
      "header [data-testid='conversation-info-header']",
      "#main header [data-testid='conversation-info-header-chat-title']",
      "#main header span[dir='auto']",
      "header span[dir='auto']"
    ];

    for (const sel of specificSelectors) {
      if (typeof doc.querySelector !== "function") continue;
      const el = doc.querySelector(sel);
      if (el) {
        const titleAttr = typeof el.getAttribute === "function" ? el.getAttribute("title") : null;
        const text = (el.innerText || el.textContent || "").trim();
        const cand = (titleAttr && !isInvalidChatTitle(titleAttr)) ? titleAttr.trim() : (text && !isInvalidChatTitle(text) ? text : null);
        if (cand) return cand;
      }
    }

    // 2. Fallback: all header elements with title attribute, strictly rejecting invalid titles
    if (typeof doc.querySelectorAll === "function") {
      const allTitleEls = doc.querySelectorAll("header [title]");
      for (const el of allTitleEls) {
        const t = el.getAttribute("title");
        if (t && !isInvalidChatTitle(t)) {
          return t.trim();
        }
      }
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
      container.querySelector("[data-testid='download'], [data-icon='download'], [data-testid='audio-download'], button[aria-label*='download' i], button[aria-label*='تحميل' i], button[aria-label*='تنزيل' i], a[download]") ||
      null
    );
  }

  /**
   * Extract clean document filename from document card element.
   * Handles WhatsApp Web title attributes like 'Download "<filename>.docx"' or 'تنزيل "<filename>.docx"'
   */
  function extractDocumentFilename(dNode) {
    if (!dNode) return null;
    let titleAttr = (typeof dNode.getAttribute === "function" ? dNode.getAttribute("title") : null) || "";
    let clean = titleAttr.trim();

    // Check Download "Filename.ext" or تنزيل "Filename.ext" or تحميل "Filename.ext"
    const quoteMatch = clean.match(/(?:download|تنزيل|تحميل)\s+["“](.*?)["”]/i);
    if (quoteMatch && quoteMatch[1]) {
      return quoteMatch[1].trim();
    }

    // Check inner text or child nodes for filename with extension
    if (typeof dNode.querySelectorAll === "function") {
      const candidates = dNode.querySelectorAll("span[title], div[title], span[dir='auto'], span, div");
      for (const el of candidates) {
        const t = (typeof el.getAttribute === "function" && el.getAttribute("title")) || el.innerText || el.textContent || "";
        const trimmed = t.trim();
        const innerQuote = trimmed.match(/(?:download|تنزيل|تحميل)\s+["“](.*?)["”]/i);
        if (innerQuote && innerQuote[1]) return innerQuote[1].trim();
        if (/\.[a-zA-Z0-9]{1,10}$/.test(trimmed)) {
          return trimmed;
        }
      }
    }

    // If clean itself has an extension
    clean = clean.replace(/^["“]|["”]$/g, "");
    if (/\.[a-zA-Z0-9]{1,10}$/.test(clean)) {
      return clean;
    }

    return null;
  }

  /**
   * Automate user-visible context-menu Download action on WhatsApp Web messages.
   * Right-clicking a voice message or document card opens the native message menu containing "Download" / "تنزيل".
   */
  async function triggerContextMenuDownload(targetEl, { doc = (typeof document !== "undefined" ? document : null), timeoutMs = 2500, checkCancelled = () => false } = {}) {
    if (!targetEl) return { success: false, reason: "no_target_element" };

    const rootDoc = doc || (typeof document !== "undefined" ? document : null);
    if (!rootDoc || typeof rootDoc.querySelectorAll !== "function") {
      return { success: false, reason: "no_document_root" };
    }

    try {
      // 0. Ensure targetEl or its interactive button is targeted
      let actionEl = targetEl;
      if (typeof targetEl.querySelector === "function") {
        const playBtn = targetEl.querySelector(
          "button[aria-label*='Play' i], button[aria-label*='voice message' i], button[aria-label*='تشغيل' i], span[data-icon='ptt-status']"
        );
        if (playBtn) actionEl = playBtn;
      }

      // Scroll into view if needed
      if (typeof actionEl.scrollIntoView === "function") {
        try { actionEl.scrollIntoView({ block: "nearest", inline: "nearest" }); } catch (e) {}
      }

      // Close preexisting menu before opening target if needed, no trust of old menu
      const prevMenus = rootDoc.querySelectorAll("div[role='menu'], [role='menu']");
      if (prevMenus && prevMenus.length > 0) {
        if (typeof rootDoc.dispatchEvent === "function") {
          try {
            const escEvt = typeof KeyboardEvent !== "undefined"
              ? new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true, cancelable: true })
              : { type: "keydown", key: "Escape", bubbles: true };
            rootDoc.dispatchEvent(escEvt);
          } catch (e) {}
        }
      }
      const existingMenus = new Set();
      if (prevMenus) {
        for (const m of prevMenus) existingMenus.add(m);
      }

      // 1. Dispatch contextmenu event on actionEl
      let clientX = 0, clientY = 0;
      if (typeof actionEl.getBoundingClientRect === "function") {
        const rect = actionEl.getBoundingClientRect();
        clientX = Math.floor(rect.left + rect.width / 2);
        clientY = Math.floor(rect.top + rect.height / 2);
      }

      if (typeof actionEl.dispatchEvent === "function") {
        const cEvt = typeof MouseEvent !== "undefined"
          ? new MouseEvent("contextmenu", {
              bubbles: true,
              cancelable: true,
              view: typeof window !== "undefined" ? window : null,
              clientX,
              clientY,
              button: 2,
              buttons: 2
            })
          : {
              type: "contextmenu",
              bubbles: true,
              cancelable: true,
              clientX,
              clientY,
              button: 2,
              buttons: 2
            };
        actionEl.dispatchEvent(cEvt);
      }

      function findDownloadInMenu(menuEl) {
        if (!menuEl || typeof menuEl.querySelectorAll !== "function") return null;
        const candidates = menuEl.querySelectorAll(
          "button[role='menuitem'], [role='menuitem'], div[role='button'], button, li[role='button'], div[tabindex='-1']"
        );
        for (const item of candidates) {
          const text = (item.innerText || item.textContent || "").trim().toLowerCase();
          const testid = typeof item.getAttribute === "function" ? (item.getAttribute("data-testid") || "").toLowerCase() : "";
          const ariaLabel = typeof item.getAttribute === "function" ? (item.getAttribute("aria-label") || "").toLowerCase() : "";
          const role = typeof item.getAttribute === "function" ? (item.getAttribute("role") || "").toLowerCase() : "";

          const isDownloadItem = (
            ariaLabel === "download" || ariaLabel.startsWith("download") ||
            ariaLabel === "تنزيل" || ariaLabel.startsWith("تنزيل") ||
            ariaLabel === "تحميل" || ariaLabel.startsWith("تحميل") ||
            text === "download" || text.startsWith("download") ||
            text === "تنزيل" || text.startsWith("تنزيل") ||
            text === "تحميل" || text.startsWith("تحميل") ||
            testid.includes("download") || testid.includes("تنزيل") ||
            (role === "menuitem" && (ariaLabel.includes("download") || ariaLabel.includes("تنزيل") || text.includes("download") || text.includes("تنزيل")))
          );

          if (isDownloadItem) return item;
        }
        return null;
      }

      function clickItem(item) {
        if (typeof item.click === "function") {
          item.click();
        } else if (typeof item.dispatchEvent === "function") {
          const clickEvt = typeof MouseEvent !== "undefined"
            ? new MouseEvent("click", { bubbles: true, cancelable: true })
            : { type: "click", bubbles: true, cancelable: true };
          item.dispatchEvent(clickEvt);
        }
      }

      // 2. Poll for newly opened menu items in document body
      const startTime = Date.now();
      let fallbackClicked = false;

      while (Date.now() - startTime < timeoutMs) {
        if (checkCancelled()) {
          return { success: false, reason: "cancelled_by_user" };
        }
        await sleep(100);

        // Prioritize only newly opened menu element (never trust preexisting menus)
        let targetMenu = null;
        const menuContainers = rootDoc.querySelectorAll("div[role='menu'], [role='menu']");
        if (menuContainers) {
          for (const m of menuContainers) {
            if (!existingMenus.has(m)) {
              targetMenu = m;
              break;
            }
          }
        }

        if (targetMenu) {
          const dlBtn = findDownloadInMenu(targetMenu);
          if (dlBtn) {
            clickItem(dlBtn);
            return { success: true };
          }
        }

        // Controlled fallback: If after 300ms contextmenu event didn't reveal a menu, try hover context menu button.
        // NEVER double-toggle with unconditional click if a menu is already found!
        if (!fallbackClicked && !targetMenu && Date.now() - startTime >= 300) {
          const msgParent = actionEl.closest ? actionEl.closest("div[data-id][data-testid^='conv-msg-'], div[data-id], .message-in, .message-out") : null;
          if (msgParent && typeof msgParent.querySelector === "function") {
            const menuBtn = msgParent.querySelector(
              "button[aria-label*='Context menu' i], button[aria-label*='قائمة السياق' i], [data-testid='down-context'], [data-icon='down-context']"
            );
            if (menuBtn && typeof menuBtn.click === "function") {
              menuBtn.click();
              fallbackClicked = true;
            }
          }
        }
      }

      return { success: false, reason: "download_menu_item_not_found" };
    } catch (e) {
      return { success: false, error: e.message };
    }
  }


  /**
   * Detect all attachments on a message element (audio, video, document, image, other).
   * Supports multiple attachments per message and identifies preview/thumbnail vs downloadable original.
   */
  function detectMessageAttachments(el, chatTitle) {
    if (!el || (typeof el.querySelector !== "function" && typeof el.querySelectorAll !== "function")) return [];
    const attachments = [];

    // 1. Audio / Voice Note Detection
    const voiceSelector = (
      "button[aria-label*='voice message' i], button[aria-label*='رسالة صوتية' i], " +
      "span[aria-label*='voice message' i], span[aria-label*='رسالة صوتية' i], " +
      "[role='slider'][aria-label*='voice' i], [role='slider'][aria-label*='صوتي' i], " +
      "audio, [data-testid='audio-player'], [data-testid='ptt-waveform'], span[data-icon='ptt-play'], span[data-icon='audio-play']"
    );
    const audioNodes = el.querySelectorAll ? el.querySelectorAll(voiceSelector) : [];
    if (audioNodes && audioNodes.length > 0) {
      let primaryNode = audioNodes[0];
      let audioEl = null;
      for (let i = 0; i < audioNodes.length; i++) {
        const aNode = audioNodes[i];
        if (aNode.tagName === "AUDIO") {
          audioEl = aNode;
          primaryNode = aNode;
          break;
        }
        if (aNode.querySelector && aNode.querySelector("audio")) {
          audioEl = aNode.querySelector("audio");
          primaryNode = aNode;
          break;
        }
      }
      const blobUrl = audioEl && audioEl.src && audioEl.src.startsWith("blob:") ? audioEl.src : null;
      const dlBtn = findDownloadControl(el);

      let initialStatus = "unavailable";
      if (blobUrl) {
        initialStatus = "available";
      }

      attachments.push({
        id: `att_audio_${attachments.length + 1}`,
        file_type: "audio",
        file_name: `voice_note_${attachments.length + 1}.ogg`,
        mime_type: "audio/ogg",
        blob_url: blobUrl,
        is_thumbnail_only: false,
        download_el: dlBtn,
        container_el: primaryNode,
        attachment_status: initialStatus,
        diagnostic_reason: !blobUrl ? "voice_note_no_dom_src" : null,
        can_context_download: true
      });
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
    const docNodes = el.querySelectorAll ? el.querySelectorAll("[data-testid='document-thumb'], [data-icon='document'], span[title*='.'], div[title*='.'], div[title*='Download ' i], div[title*='تنزيل ' i], div[title*='تحميل ' i]") : [];
    if (docNodes && docNodes.length > 0) {
      for (let i = 0; i < docNodes.length; i++) {
        const dNode = docNodes[i];
        const isDocThumb = (typeof dNode.getAttribute === "function" && dNode.getAttribute("data-testid") === "document-thumb");
        const docName = extractDocumentFilename(dNode) || (isDocThumb ? `document_${attachments.length + 1}.pdf` : null);

        if (docName) {
          // In WhatsApp Web live DOM, div[data-testid="document-thumb"] is itself clickable!
          const dlBtn = isDocThumb ? dNode : findDownloadControl(dNode.parentElement || dNode);
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
            attachment_status: initialStatus,
            can_context_download: true
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
    fetchFn = (typeof fetch !== "undefined" ? fetch : null),
    bridgeSender = null,
    doc = (typeof document !== "undefined" ? document : null)
  } = {}) {
    if (checkCancelled()) {
      return { status: "failed", error: "cancelled", reason: "cancelled_by_user", stage: "media_acquisition" };
    }

    if (UNSUPPORTED_EXTENSIONS.has(getExtension(att.file_name))) {
      return { status: "unsupported", file_name: att.file_name, reason: "unsupported", stage: "media_acquisition" };
    }

    let targetUrl = att.blob_url;
    let downloadCaptured = false;
    let armed = false;
    let menuReason = null;
    let attemptId = null;

    // Activate visible page download / context menu download if exposed and no direct blob is ready
    if (!targetUrl && bridgeSender) {
      const triggerTarget = att.download_el || att.container_el;
      if (triggerTarget || att.can_context_download) {
        attemptId = `att_attempt_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
        const armTimeout = Math.min(Math.max(timeoutMs || 20000, 15000), 60000);
        try {
          const armRes = await bridgeSender({
            action: "bridge_arm_download_capture",
            attemptId,
            expectedFilename: att.file_name,
            expectedType: att.file_type,
            timeoutMs: armTimeout
          });
          if (!armRes || !armRes.success) {
            return {
              status: "unavailable",
              file_name: att.file_name,
              reason: "arm_failed",
              error: armRes?.error || "arm_failed",
              stage: "media_acquisition"
            };
          }
          armed = true;

          if (checkCancelled()) {
            return { status: "failed", error: "cancelled", reason: "cancelled_by_user", stage: "media_acquisition" };
          }

          let triggered = false;
          // For direct document cards, try clicking the download element first
          if (att.file_type === "document" && att.download_el && typeof att.download_el.click === "function") {
            att.download_el.click();
            triggered = true;
          }

          // Otherwise or fallback: try user-visible context menu Download action (e.g. for voice note)
          if (!triggered && triggerTarget) {
            const menuRes = await triggerContextMenuDownload(triggerTarget, {
              doc,
              timeoutMs: Math.max(3000, Math.min(timeoutMs || 3000, 5000)),
              checkCancelled
            });
            if (menuRes && menuRes.success) {
              triggered = true;
            } else if (menuRes && menuRes.reason) {
              menuReason = menuRes.reason;
            }
          }

          // Direct click fallback if context menu was not successful
          if (!triggered && att.download_el && typeof att.download_el.click === "function") {
            att.download_el.click();
            triggered = true;
          }

          if (checkCancelled()) {
            return { status: "failed", error: "cancelled", reason: "cancelled_by_user", stage: "media_acquisition" };
          }

          if (triggered) {
            const dlRes = await bridgeSender({ action: "bridge_await_download", attemptId });
            if (checkCancelled()) {
              return { status: "failed", error: "cancelled", reason: "cancelled_by_user", stage: "media_acquisition" };
            }
            if (dlRes && dlRes.success && dlRes.downloadPath) {
              downloadCaptured = true;
              return {
                status: "saved-original",
                download_path: dlRes.downloadPath,
                file_size: dlRes.fileSize || 0,
                file_name: att.file_name,
                file_type: att.file_type,
                mime_type: dlRes.mime || att.mime_type,
                stage: "media_acquisition"
              };
            } else {
              menuReason = dlRes?.error_code || dlRes?.error || "download_timeout";
            }
          }
        } catch (e) {
          menuReason = e.message || "download_failed";
        } finally {
          if (!downloadCaptured && armed) {
            try {
              await bridgeSender({ action: "bridge_disarm_download_capture", attemptId });
            } catch (e) {}
          }
        }
      }
    }

    // Voice notes in WhatsApp Web have no DOM audio src or blob when download was not captured
    if (att.file_type === "audio" && !targetUrl) {
      return {
        status: "unavailable",
        file_name: att.file_name,
        reason: menuReason || att.diagnostic_reason || "voice_note_no_dom_src",
        error: menuReason || null,
        stage: "media_acquisition"
      };
    }

    if (!targetUrl) {
      if (att.is_thumbnail_only) {
        return { status: "preview-only", file_name: att.file_name, reason: "thumbnail_only", stage: "media_acquisition" };
      }
      return {
        status: "unavailable",
        file_name: att.file_name,
        reason: menuReason || att.diagnostic_reason || (att.file_type === "document" ? "document_download_untriggered" : "no_target_element"),
        error: menuReason || null,
        stage: "media_acquisition"
      };
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
    if (!attachment) {
      return { success: false, status: "unavailable" };
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

    // Scoped download handoff via background bridge
    if (attachment.download_path) {
      const res = await sender({
        action: "bridge_media_download_handoff",
        downloadPath: attachment.download_path,
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
        sha256: attachment.sha256 || null,
        attachmentStatus: attachment.attachment_status || "saved-original"
      });
      if (res && res.success) {
        attachment.attachment_status = "saved-original";
        return { success: true, status: "saved-original", data: res.data };
      } else {
        attachment.attachment_status = "failed";
        return { success: false, status: "failed", error: res?.error || "Download handoff failed" };
      }
    }

    if (!attachment.bytes) {
      return { success: false, status: attachment?.attachment_status || "unavailable" };
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
   * Find a defensible calendar date for an element without data-pre-plain-text (e.g. media-only message).
   * Inspects preceding date dividers or neighboring dated message rows in the container.
   * Never falls back to the current date.
   */
  function getSeparatorInfoFromNode(node) {
    if (!node) return null;
    // Must not be a message node or contain message content
    if (typeof node.getAttribute === "function") {
      const dataId = node.getAttribute("data-id");
      const testId = node.getAttribute("data-testid") || "";
      if (dataId || testId.startsWith("conv-msg-")) return null;
    }
    if (typeof node.querySelector === "function") {
      if (node.querySelector("div[data-id], [data-testid^='conv-msg-'], .selectable-text, .copyable-text, [data-pre-plain-text], [data-testid='msg-meta']")) {
        return null;
      }
    }

    const text = (node.innerText || node.textContent || "").trim();
    if (!text || text.length > 50) return null;

    const cleaned = DateParser.cleanBidi(text).trim().toLowerCase();

    // 1. Explicit separator or badge attributes
    const testId = typeof node.getAttribute === "function" ? (node.getAttribute("data-testid") || "") : "";
    const role = typeof node.getAttribute === "function" ? (node.getAttribute("role") || "") : "";
    const isExplicit = testId === "date-divider" || testId === "date-badge" || role === "separator" || (node.classList && (node.classList.contains("date-divider") || node.classList.contains("date-badge")));

    // 2. Relative (Today / Yesterday)
    if (cleaned === "today" || cleaned === "اليوم" || cleaned === "yesterday" || cleaned === "أمس") {
      return { type: "relative", text: cleaned, date: DateParser.parseDateDivider(text) };
    }

    // 3. Weekday
    const weekday = DateParser.parseWeekday ? DateParser.parseWeekday(cleaned) : null;
    if (weekday !== null) {
      return { type: "weekday", text: cleaned, weekday };
    }

    // 4. Absolute date
    const words = cleaned.replace(/[,،]/g, " ").split(/\s+/).filter(Boolean);
    if (isExplicit || words.length <= 4) {
      const absDate = DateParser.extractAbsoluteDateFromText(text);
      if (absDate) {
        return { type: "absolute", text: cleaned, date: absDate };
      }
    }

    return null;
  }

  function getDateFromPrePlain(node) {
    if (!node) return null;
    let preAttr = typeof node.getAttribute === "function" ? node.getAttribute("data-pre-plain-text") : null;
    if (!preAttr && typeof node.querySelector === "function") {
      const preEl = node.querySelector("[data-pre-plain-text]");
      if (preEl && typeof preEl.getAttribute === "function") {
        preAttr = preEl.getAttribute("data-pre-plain-text");
      }
    }
    if (preAttr) {
      return DateParser.extractAbsoluteDateFromText(preAttr);
    }
    return null;
  }

  /**
   * Find a defensible calendar date for an element without data-pre-plain-text (e.g. media-only message).
   * Inspects preceding date dividers or neighboring dated message rows across nested wrappers.
   * Resolves within day boundaries without crossing an explicit different day; never falls back to current date.
   */
  function findDefensibleDateForElement(el, container = null) {
    if (!el) return null;
    const root = container || null;

    let datedMsgBefore = null;
    let sepBefore = null;

    // Backward search across nested wrappers
    let curr = el;
    let depth = 0;
    while (curr && curr !== root && depth < 10) {
      let prev = curr.previousElementSibling;
      while (prev) {
        const sep = getSeparatorInfoFromNode(prev);
        if (sep) {
          sepBefore = sep;
          break;
        }
        if (!datedMsgBefore) {
          const d = getDateFromPrePlain(prev);
          if (d) datedMsgBefore = d;
        }
        prev = prev.previousElementSibling;
      }
      if (sepBefore) break;
      curr = curr.parentElement;
      depth++;
    }

    // Forward search across nested wrappers (stopping immediately at any date separator / day boundary)
    let datedMsgAfter = null;
    let sepAfter = null;
    curr = el;
    depth = 0;
    while (curr && curr !== root && depth < 10) {
      let next = curr.nextElementSibling;
      while (next) {
        const sep = getSeparatorInfoFromNode(next);
        if (sep) {
          sepAfter = sep;
          break;
        }
        if (!datedMsgAfter) {
          const d = getDateFromPrePlain(next);
          if (d) {
            datedMsgAfter = d;
            break;
          }
        }
        next = next.nextElementSibling;
      }
      if (sepAfter || datedMsgAfter) break;
      curr = curr.parentElement;
      depth++;
    }

    // 1. Within day boundary: preceding dated message
    if (datedMsgBefore) {
      if (sepBefore && sepBefore.type === "weekday") {
        return DateParser.resolveWeekdayWithAnchor(sepBefore.text, datedMsgBefore);
      }
      return datedMsgBefore;
    }

    // 2. Preceding separator (absolute / relative)
    if (sepBefore && (sepBefore.type === "absolute" || sepBefore.type === "relative")) {
      return sepBefore.date;
    }

    // 3. Within day boundary: following dated message
    if (datedMsgAfter) {
      if (sepBefore && sepBefore.type === "weekday") {
        return DateParser.resolveWeekdayWithAnchor(sepBefore.text, datedMsgAfter);
      }
      if (sepAfter && sepAfter.type === "weekday") {
        return DateParser.resolveWeekdayWithAnchor(sepAfter.text, datedMsgAfter);
      }
      return datedMsgAfter;
    }

    // 4. Bare weekday alone without matching adjacent row in same day group is unresolved
    return null;
  }

  /**
   * Parse a single message DOM node into a structured message object with rich attachments.
   */
  function parseMessageNode(el, chatTitle, dateOrder = "DD/MM/YYYY", container = null) {
    const isOutgoing = el.classList?.contains("message-out") || el.getAttribute("data-id")?.startsWith("true_");
    const platformMsgId = el.getAttribute("data-id") || null;

    const selectableEl = el.querySelector ? el.querySelector(".selectable-text") : null;
    const copyableEl = el.querySelector ? el.querySelector(".copyable-text") : null;
    const textEl = selectableEl || copyableEl;

    // Independent lookup of data-pre-plain-text: check el, descendant, or ancestor of text elements
    let prePlainAttr = (typeof el.getAttribute === "function" && el.getAttribute("data-pre-plain-text")) || null;
    if (!prePlainAttr && typeof el.querySelector === "function") {
      const preEl = el.querySelector("[data-pre-plain-text]");
      if (preEl && typeof preEl.getAttribute === "function") {
        prePlainAttr = preEl.getAttribute("data-pre-plain-text");
      }
    }
    if (!prePlainAttr && textEl && typeof textEl.closest === "function") {
      const anc = textEl.closest("[data-pre-plain-text]");
      if (anc && typeof anc.getAttribute === "function") {
        prePlainAttr = anc.getAttribute("data-pre-plain-text");
      }
    }

    let senderName = isOutgoing ? "You" : chatTitle;
    let rawTimestamp = null;

    if (prePlainAttr) {
      const match = prePlainAttr.match(/\[(.*?)\]\s*(.*?):\s*$/);
      if (match) {
        rawTimestamp = match[1].trim();
        senderName = isOutgoing ? "You" : match[2].trim() || chatTitle;
      }
    } else {
      const timeSpan = el.querySelector ? el.querySelector("[data-testid='msg-meta'] span, [data-testid='msg-meta'], span[dir='auto']") : null;
      if (timeSpan && (timeSpan.innerText || timeSpan.textContent)) {
        rawTimestamp = (timeSpan.innerText || timeSpan.textContent).trim();
      }
    }

    let textContent = "";
    if (selectableEl) {
      textContent = (selectableEl.innerText || selectableEl.textContent || "").trim();
    } else if (copyableEl) {
      textContent = (copyableEl.innerText || copyableEl.textContent || "").trim();
    } else if (textEl) {
      textContent = (textEl.innerText || textEl.textContent || "").trim();
    }

    let parsedDate = null;
    let isoTimestamp = null;
    let timestampProvenance = "unverified";

    if (rawTimestamp) {
      const p = DateParser.parseWhatsAppTimestamp(rawTimestamp, { dateOrder });
      if (p) {
        parsedDate = p.date;
        isoTimestamp = p.iso;
        timestampProvenance = prePlainAttr ? "verified" : "direct_dom";
      } else {
        // Standalone time string (e.g. "3:21 pm" on media-only row): derive date from neighbor or divider
        const defensibleDateStr = findDefensibleDateForElement(el, container);
        if (defensibleDateStr) {
          const combined = DateParser.combineTimeAndDate(rawTimestamp, defensibleDateStr, { dateOrder });
          if (combined) {
            parsedDate = combined.date;
            isoTimestamp = combined.iso;
            timestampProvenance = "derived_neighbor";
          }
        }
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
      const imgEl = el.querySelector ? el.querySelector("img[src]:not([alt='']):not([data-testid='status-image'])") : null;
      if (imgEl && imgEl.src && !imgEl.src.includes("data:image/svg+xml")) {
        mediaType = "image";
        mediaFilename = "whatsapp_image.jpg";
        hasMedia = true;
        attachmentStatus = "available";
        if (!textContent) textContent = "<image attached>";
      }

      const audioEl = el.querySelector ? el.querySelector("audio, [data-testid='audio-player']") : null;
      if (audioEl) {
        mediaType = "voice";
        mediaFilename = "whatsapp_voice_note.ogg";
        hasMedia = true;
        attachmentStatus = "available";
        if (!textContent) textContent = "<voice message attached>";
      }

      const docEl = el.querySelector ? el.querySelector("[data-testid='document-thumb'], span[title*='.pdf'], span[title*='.doc']") : null;
      if (docEl) {
        mediaType = "document";
        const docName = (typeof docEl.getAttribute === "function" ? docEl.getAttribute("title") : null) || docEl.innerText?.trim() || "document.pdf";
        mediaFilename = docName;
        hasMedia = true;
        attachmentStatus = "available";
        if (!textContent) textContent = `<document: ${docName}>`;
      }
    }

    const isSkeleton = !rawTimestamp && !hasMedia && (!textContent || textContent === "[text]" || textContent === "");
    const msgKey = platformMsgId || generateSyntheticId(senderName, isoTimestamp || rawTimestamp, textContent);

    return {
      key: msgKey,
      platform_msg_id: platformMsgId,
      is_outgoing: isOutgoing,
      sender: senderName,
      text: textContent || `[${mediaType}]`,
      raw_timestamp: rawTimestamp,
      timestamp: isoTimestamp,
      parsed_date: parsedDate,
      timestamp_provenance: timestampProvenance,
      has_media: hasMedia,
      media_type: mediaType,
      media_filename: mediaFilename,
      attachment_status: attachmentStatus,
      attachments: detectedAttachments,
      is_skeleton: isSkeleton
    };
  }

  function getCanonicalMessageNodes(container) {
    if (!container || typeof container.querySelectorAll !== "function") return [];
    const rawNodes = container.querySelectorAll("div[data-id][data-testid^='conv-msg-'], div[data-id], .message-in, .message-out");
    const canonical = [];
    const seenIds = new Set();

    for (const node of rawNodes) {
      if (typeof node.closest === "function") {
        const parentMsg = node.closest("div[data-id][data-testid^='conv-msg-'], div[data-id]");
        if (parentMsg && parentMsg !== node) {
          continue;
        }
      } else {
        let p = node.parentElement;
        let hasParentMsg = false;
        while (p && p !== container) {
          if (typeof p.getAttribute === "function" && p.getAttribute("data-id")) {
            hasParentMsg = true;
            break;
          }
          p = p.parentElement;
        }
        if (hasParentMsg) continue;
      }

      const dataId = typeof node.getAttribute === "function" ? node.getAttribute("data-id") : null;
      if (dataId) {
        if (seenIds.has(dataId)) continue;
        seenIds.add(dataId);
      }

      canonical.push(node);
    }

    return canonical;
  }

  async function processItemMedia(item, scanOpts = {}) {
    const {
      captureMedia = false,
      onMediaCaptured = null,
      bridgeSender = null,
      targetConversationId = null,
      confirmTargetMerge = false,
      sessionId = null,
      fetchFn = (typeof fetch !== "undefined" ? fetch : null),
      checkCancelled = () => false,
      doc = (typeof document !== "undefined" ? document : null),
      fromDate = null,
      toDate = null,
      mode = null,
      trackedAttachments = null,
      chatTitle = null,
      existingItem = null
    } = scanOpts;

    if (!captureMedia || !item.has_media || !item.attachments || item.attachments.length === 0) {
      return;
    }

    // DATE-RANGE GATE BEFORE MEDIA ACQUISITION:
    if (mode === "date_range" || fromDate || toDate) {
      const fromTime = fromDate ? new Date(fromDate).getTime() : -Infinity;
      const toTime = toDate ? new Date(toDate).getTime() : Infinity;
      if (!item.parsed_date) {
        return; // Unverified / unparseable timestamp: do not acquire media
      }
      const t = item.parsed_date.getTime();
      if (t < fromTime || t > toTime) {
        return; // Out of range: do not acquire media
      }
    }

    const mediaRetryCounts = scanOpts.mediaRetryCounts || (scanOpts.mediaRetryCounts = new Map());

    for (let attIdx = 0; attIdx < item.attachments.length; attIdx++) {
      if (checkCancelled()) break;
      const att = item.attachments[attIdx];
      const durableKey = `${item.platform_msg_id || item.key}_att_${att.id || attIdx}_${att.file_name}`;

      // 1. Preserve successful perattachment result on later scans:
      if (trackedAttachments && trackedAttachments.get(durableKey) === "saved-original") {
        att.attachment_status = "saved-original";
        if (existingItem && existingItem.attachments) {
          const exAtt = existingItem.attachments.find(a => (a.file_name === att.file_name) || (a.id === att.id));
          if (exAtt && exAtt.attachment_status === "saved-original") {
            att.download_path = exAtt.download_path || att.download_path;
            att.bytes = exAtt.bytes || att.bytes;
            att.sha256 = exAtt.sha256 || att.sha256;
            att.file_size = exAtt.file_size || att.file_size;
            att.reason = exAtt.reason || att.reason;
            att.error = exAtt.error || att.error;
            att.stage = exAtt.stage || att.stage;
          }
        }
        continue;
      }

      // 2. Retry transient unavailable media with bounded count (e.g. max 2 retries)
      const prevRetries = mediaRetryCounts.get(durableKey) || 0;
      if (prevRetries >= 2 && trackedAttachments && trackedAttachments.get(durableKey) === "unavailable") {
        att.attachment_status = "unavailable";
        continue;
      }
      mediaRetryCounts.set(durableKey, prevRetries + 1);

      const captured = await captureAttachmentOriginalBytes(att, { checkCancelled, fetchFn, bridgeSender, doc });
      att.attachment_status = captured.status;
      att.sha256 = captured.sha256 || null;
      att.file_size = captured.file_size || 0;
      att.download_path = captured.download_path || null;
      att.reason = captured.reason || captured.diagnostic_reason || null;
      att.diagnostic_reason = att.reason;
      att.error = captured.error || null;
      att.stage = captured.stage || null;

      if (captured.status === "saved-original" && (captured.bytes || captured.download_path)) {
        if (captured.bytes) att.bytes = captured.bytes;
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
        onMediaCaptured(att, durableKey);
      }

      // Diagnostics emission for media acquisition:
      if (att.reason || att.attachment_status !== "saved-original") {
        try {
          await DiagLogger.log("media_acquisition", att.attachment_status === "saved-original" ? "SUCCESS" : "PARTIAL", attIdx + 1, att.reason || "ok");
        } catch (e) {}
      }

      if (checkCancelled()) break;
    }

    if (item.attachments.length > 0) {
      const anySaved = item.attachments.some(a => a.attachment_status === "saved-original");
      const anyPreview = item.attachments.some(a => a.attachment_status === "preview-only");
      item.attachment_status = anySaved ? "saved-original" : (anyPreview ? "preview-only" : item.attachments[0].attachment_status);
    }
  }

  async function scanCurrentDOMMessages(container, chatTitle, dateOrder, messageMap, options = {}) {
    const msgNodes = getCanonicalMessageNodes(container);
    let newlyFound = 0;

    for (const node of msgNodes) {
      if (options.checkCancelled && options.checkCancelled()) break;

      let item = parseMessageNode(node, chatTitle, dateOrder, container);
      if (!item || !item.key) continue;

      // Unresolved skeleton node: bounded hydration wait by scrolling into view
      const isSkeleton = item.is_skeleton || (!item.parsed_date && !item.has_media && (!item.text || item.text === "[text]"));
      if (isSkeleton && typeof node.scrollIntoView === "function") {
        try { node.scrollIntoView({ block: "nearest", inline: "nearest" }); } catch (e) {}
        await sleep(100);
        const reItem = parseMessageNode(node, chatTitle, dateOrder, container);
        if (reItem && (!reItem.is_skeleton && (reItem.parsed_date || reItem.has_media || (reItem.text && reItem.text !== "[text]")))) {
          item = reItem;
        }
      }

      const existing = messageMap.get(item.key);
      const isExistingSkeleton = existing && (existing.is_skeleton || (!existing.parsed_date && !existing.has_media && (!existing.text || existing.text === "[text]")));
      const isItemHydrated = !item.is_skeleton && (item.parsed_date || item.has_media || (item.text && item.text !== "[text]"));
      const isDateUpgraded = existing && !existing.parsed_date && item.parsed_date;

      if (!existing) {
        await processItemMedia(item, { ...options, existingItem: null });
        messageMap.set(item.key, item);
        newlyFound++;
      } else if (isExistingSkeleton && isItemHydrated) {
        // Hydration retry: update incomplete skeleton with hydrated message, preserving any saved metadata
        await processItemMedia(item, { ...options, existingItem: existing });
        messageMap.set(item.key, item);
        newlyFound++;
      } else if (isDateUpgraded) {
        // Date resolved/upgraded upon further hydration
        await processItemMedia(item, { ...options, existingItem: existing });
        messageMap.set(item.key, item);
        newlyFound++;
      } else if (existing) {
        // Transient unavailable retry with bounded count
        const hasTransientUnavailable = item.attachments && item.attachments.some(a => a.attachment_status === "unavailable");
        if (hasTransientUnavailable) {
          await processItemMedia(item, { ...options, existingItem: existing });
          messageMap.set(item.key, item);
        }
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

    const trackedAttachments = new Map();

    const scanOpts = {
      mode,
      fromDate,
      toDate,
      captureMedia,
      targetConversationId,
      confirmTargetMerge,
      sessionId: captureSessionId,
      chatTitle: initialChatTitle,
      bridgeSender,
      checkCancelled,
      fetchFn,
      doc,
      trackedAttachments,
      onMediaCaptured: (att, durableKey) => {
        const key = durableKey || att.id || att.file_name;
        const prevStatus = trackedAttachments.get(key);
        const newStatus = att.attachment_status;

        function statKey(s) {
          if (s === "saved-original") return "savedOriginal";
          if (s === "preview-only") return "previewOnly";
          if (s === "unavailable") return "unavailable";
          if (s === "expired") return "expired";
          if (s === "too-large") return "tooLarge";
          if (s === "unsupported") return "unsupported";
          if (s === "failed") return "failed";
          return null;
        }

        // Once saved-original, never downgrade
        if (prevStatus === "saved-original" && newStatus !== "saved-original") {
          att.attachment_status = "saved-original";
          return;
        }

        if (prevStatus === newStatus) {
          return;
        }

        if (prevStatus) {
          const oldK = statKey(prevStatus);
          if (oldK && attachmentStats[oldK] > 0) {
            attachmentStats[oldK]--;
          }
        }
        const newK = statKey(newStatus);
        if (newK) {
          attachmentStats[newK]++;
        }
        trackedAttachments.set(key, newStatus);
        attachmentStats.totalDetected = trackedAttachments.size;
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
      const allMsgs = getCanonicalMessageNodes(container);
      let startItem = null;

      // Find first visible message in viewport
      for (const node of allMsgs) {
        const r = node.getBoundingClientRect();
        if (r.bottom >= containerRect.top + 5) {
          startItem = parseMessageNode(node, initialChatTitle, dateOrder, container);
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
        const item = parseMessageNode(node, initialChatTitle, dateOrder, container);
        if (!foundStart && item.key === startItem.key) {
          foundStart = true;
        }
        if (foundStart && item.key) {
          await processItemMedia(item, scanOpts);
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
        if (isAtBottom && (container.scrollTop === lastScrollTop || container.scrollHeight <= container.clientHeight)) {
          noChangeCount++;
          if (noChangeCount >= 2 || container.scrollHeight <= container.clientHeight) {
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
          if (isAtBottom && (container.scrollTop === lastScroll || container.scrollHeight <= container.clientHeight)) {
            bottomExhaustedCount++;
            if (bottomExhaustedCount >= 2 || container.scrollHeight <= container.clientHeight) break;
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

        const isAtBottomNow = container.scrollTop + container.clientHeight >= container.scrollHeight - 10;
        const reachedTrueBottom = isAtBottomNow && (bottomExhaustedCount >= 2 || container.scrollHeight <= container.clientHeight);

        if (reachedTrueBottom) {
          // Reached the physical end of the conversation naturally.
          // When a bound is later than the latest real chat message, reaching the bottom naturally finishes complete.
        } else if (bottomExhaustedCount >= 2 && !isAtBottomNow && newestDate !== null && newestDate < toTimestamp) {
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
          attachment_status: a.attachment_status || "none",
          reason: a.reason || a.diagnostic_reason || null,
          error: a.error || null,
          stage: a.stage || null
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
    INVALID_CHAT_TITLES,
    isInvalidChatTitle,
    extractDocumentFilename,
    findDefensibleDateForElement,
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
