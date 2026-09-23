// OWI Companion Popup Script
const API_URL = "http://127.0.0.1:8765/api/companion/ingest";
const TOKEN = "owi-companion-local-bridge-key-2026";

document.getElementById("open-owi").addEventListener("click", () => {
  chrome.tabs.create({ url: "http://127.0.0.1:8765" });
});

document.getElementById("capture-visible").addEventListener("click", async () => {
  const statusDiv = document.getElementById("status");
  statusDiv.style.display = "block";
  statusDiv.className = "";
  statusDiv.innerText = "جارٍ جمع الرسائل المرئية...";

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab.url || !tab.url.includes("web.whatsapp.com")) {
      statusDiv.className = "status-error";
      statusDiv.innerText = "يرجى فتح تبويب واتساب ويب أولاً.";
      return;
    }

    // Send message to content script to collect visible messages
    chrome.tabs.sendMessage(tab.id, { action: "capture_visible" }, async (response) => {
      if (!response || !response.messages || response.messages.length === 0) {
        statusDiv.className = "status-error";
        statusDiv.innerText = "لم يتم العثور على رسائل في المحادثة الحالية.";
        return;
      }

      // Send to localhost OWI backend
      try {
        const res = await fetch(API_URL, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-OWI-Token": TOKEN,
          },
          body: JSON.stringify({
            chat_title: response.chat_title || "WhatsApp Web Capture",
            messages: response.messages,
          }),
        });

        const data = await res.json();
        if (res.ok) {
          statusDiv.className = "status-success";
          statusDiv.innerText = `✓ تم إرسال ${data.messages_ingested} رسالة بنجاح إلى OWI!`;
        } else {
          statusDiv.className = "status-error";
          statusDiv.innerText = `خطأ في الخادم المحلي: ${data.detail || "فشل الاتصال"}`;
        }
      } catch (err) {
        statusDiv.className = "status-error";
        statusDiv.innerText = "تعذر الاتصال بتطبيق OWI على http://127.0.0.1:8765. تأكد من تشغيل التطبيق.";
      }
    });
  } catch (e) {
    statusDiv.className = "status-error";
    statusDiv.innerText = "خطأ: " + e.message;
  }
});
