// OWI Content Script on web.whatsapp.com
// Collects user-initiated visible messages without scraping credentials or automated background crawling.

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "capture_visible") {
    try {
      // Find chat title header
      const headerEl = document.querySelector("header [title]");
      const chatTitle = headerEl ? headerEl.getAttribute("title") : "WhatsApp Web Chat";

      // Select message rows visible in DOM
      const msgContainers = document.querySelectorAll("[data-id], .message-in, .message-out");
      const messages = [];

      msgContainers.forEach((el) => {
        const textEl = el.querySelector(".selectable-text, .copyable-text");
        if (textEl && textEl.innerText.trim()) {
          const isOut = el.classList.contains("message-out");
          messages.push({
            sender: isOut ? "Omar" : chatTitle,
            text: textEl.innerText.trim(),
            timestamp: new Date().toISOString(),
            has_media: !!el.querySelector("audio, img, video"),
          });
        }
      });

      sendResponse({
        chat_title: chatTitle,
        messages: messages.slice(-50), // Last 50 visible messages
      });
    } catch (e) {
      sendResponse({ error: e.message });
    }
  }
  return true;
});
