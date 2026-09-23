// OWI WhatsApp Web Content Script v2.0
// Extracts visible messages with genuine timestamps, direction, platform IDs, and accessible media.

async function blobOrSrcToBase64(src) {
  if (!src) return null;
  if (src.startsWith("data:")) {
    const parts = src.split(",");
    return parts.length > 1 ? parts[1] : null;
  }
  try {
    const res = await fetch(src);
    const blob = await res.blob();
    return new Promise((resolve) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        const b64 = reader.result.split(",")[1];
        resolve(b64);
      };
      reader.onerror = () => resolve(null);
      reader.readAsDataURL(blob);
    });
  } catch (e) {
    return null;
  }
}

function parsePrePlainText(prePlain) {
  if (!prePlain) return null;
  // Format is usually: "[10:45 AM, 9/23/2026] Sender: " or "[10:45, 23/9/2026] Sender: "
  const match = prePlain.match(/\[(.*?)\]\s*(.*?):\s*$/);
  if (match) {
    return {
      raw_time: match[1].trim(),
      sender: match[2].trim()
    };
  }
  return null;
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "capture_active_chat") {
    (async () => {
      try {
        // 1. Detect Chat Title
        let chatTitle = "WhatsApp Web Chat";
        const titleEl = document.querySelector("header [data-testid='conversation-info-header'] span[dir='auto'], header [title], header span[dir='auto']");
        if (titleEl) {
          chatTitle = titleEl.getAttribute("title") || titleEl.innerText.trim() || chatTitle;
        }

        // 2. Locate all message rows
        const msgNodes = document.querySelectorAll("div[data-id], .message-in, .message-out");
        const collected = [];

        for (const el of msgNodes) {
          const isOutgoing = el.classList.contains("message-out") || el.getAttribute("data-id")?.startsWith("true_");
          const platformMsgId = el.getAttribute("data-id") || null;

          // Find text content and pre-plain-text attribute
          const textEl = el.querySelector(".selectable-text, .copyable-text");
          const prePlainAttr = textEl ? textEl.getAttribute("data-pre-plain-text") : el.querySelector("[data-pre-plain-text]")?.getAttribute("data-pre-plain-text");

          const parsedPre = parsePrePlainText(prePlainAttr);
          
          let senderName = isOutgoing ? "You" : chatTitle;
          let timestampStr = null;

          if (parsedPre) {
            senderName = isOutgoing ? "You" : (parsedPre.sender || chatTitle);
            timestampStr = parsedPre.raw_time;
          } else {
            // Fallback: look for time span in message meta
            const timeSpan = el.querySelector("[data-testid='msg-meta'] span, span[dir='auto']");
            if (timeSpan && timeSpan.innerText) {
              timestampStr = timeSpan.innerText.trim();
            }
          }

          let textContent = textEl ? textEl.innerText.trim() : "";

          // Check Media Attachments
          let mediaBase64 = null;
          let mediaFilename = null;
          let mediaType = "text";

          const imgEl = el.querySelector("img[src]:not([alt='']):not([data-testid='status-image'])");
          if (imgEl && imgEl.src && !imgEl.src.includes("data:image/svg+xml") && imgEl.naturalWidth > 50) {
            mediaType = "image";
            mediaFilename = "whatsapp_image.jpg";
            mediaBase64 = await blobOrSrcToBase64(imgEl.src);
            if (!textContent) textContent = "<image attached>";
          }

          const audioEl = el.querySelector("audio, [data-testid='audio-player']");
          if (audioEl) {
            mediaType = "voice";
            mediaFilename = "whatsapp_voice_note.ogg";
            if (!textContent) textContent = "<voice message attached>";
          }

          const docEl = el.querySelector("[data-testid='document-thumb'], span[title*='.pdf'], span[title*='.doc']");
          if (docEl) {
            mediaType = "document";
            const docName = docEl.getAttribute("title") || docEl.innerText.trim() || "document.pdf";
            mediaFilename = docName;
            if (!textContent) textContent = `<document: ${docName}>`;
          }

          if (textContent || mediaBase64 || mediaType !== "text") {
            collected.push({
              platform_msg_id: platformMsgId,
              is_outgoing: isOutgoing,
              sender: senderName,
              text: textContent || `[${mediaType}]`,
              timestamp: timestampStr,
              media_base64: mediaBase64,
              media_filename: mediaFilename,
              media_type: mediaType
            });
          }
        }

        sendResponse({
          chat_title: chatTitle,
          messages: collected
        });
      } catch (err) {
        sendResponse({ error: err.message, messages: [] });
      }
    })();
    return true; // Keep channel open for async response
  }
});
