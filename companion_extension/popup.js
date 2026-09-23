// OWI Companion Popup Script v2.0
// Supports secure 6-digit pairing and rich message ingestion with timestamps and media

const DEFAULT_BACKEND = "http://127.0.0.1:8765";

document.addEventListener("DOMContentLoaded", async () => {
  const connBadge = document.getElementById("conn-badge");
  const pairSection = document.getElementById("pair-section");
  const captureSection = document.getElementById("capture-section");
  const statusBox = document.getElementById("status-box");
  const backendInput = document.getElementById("backend-url");
  const pairCodeInput = document.getElementById("pair-code");
  const pairBtn = document.getElementById("pair-btn");
  const captureBtn = document.getElementById("capture-btn");
  const openAppBtn = document.getElementById("open-app-btn");
  const unpairBtn = document.getElementById("unpair-btn");

  function showStatus(text, type = "info") {
    statusBox.style.display = "block";
    statusBox.className = `status-msg status-${type}`;
    statusBox.innerText = text;
  }

  // Load saved state
  const state = await chrome.storage.local.get(["owi_token", "owi_backend_url"]);
  const backendUrl = state.owi_backend_url || DEFAULT_BACKEND;
  backendInput.value = backendUrl;

  if (state.owi_token) {
    connBadge.innerText = "🟢 متصل وآمن";
    connBadge.className = "badge badge-connected";
    pairSection.style.display = "none";
    captureSection.style.display = "block";
  } else {
    connBadge.innerText = "غير مقترن";
    connBadge.className = "badge badge-disconnected";
    pairSection.style.display = "block";
    captureSection.style.display = "none";
  }

  // Pair Action
  pairBtn.addEventListener("click", async () => {
    const code = pairCodeInput.value.trim();
    const serverUrl = backendInput.value.trim() || DEFAULT_BACKEND;
    if (!code || code.length !== 6) {
      showStatus("يرجى إدخال رمز اقتران صحيح مكوّن من 6 أرقام.", "error");
      return;
    }

    showStatus("جارٍ التحقق من الرمز والاقتران...", "info");
    try {
      const res = await fetch(`${serverUrl}/api/companion/pairing/pair`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: code, device_name: "Browser Extension" })
      });
      const data = await res.json();
      if (res.ok && data.status === "paired" && data.token) {
        await chrome.storage.local.set({
          owi_token: data.token,
          owi_backend_url: serverUrl
        });
        connBadge.innerText = "🟢 متصل وآمن";
        connBadge.className = "badge badge-connected";
        pairSection.style.display = "none";
        captureSection.style.display = "block";
        showStatus("✓ تم الاقتران بنجاح! الإضافة جاهزة لالتقاط المحادثات.", "success");
      } else {
        showStatus(`فشل الاقتران: ${data.detail || "رمز غير صالح أو منتهي الصلاحية"}`, "error");
      }
    } catch (err) {
      showStatus(`تعذر الاتصال بالخادم على ${serverUrl}. تأكد من تشغيل تطبيق OWI.`, "error");
    }
  });

  // Unpair Action
  unpairBtn.addEventListener("click", async () => {
    await chrome.storage.local.remove(["owi_token"]);
    connBadge.innerText = "غير مقترن";
    connBadge.className = "badge badge-disconnected";
    pairSection.style.display = "block";
    captureSection.style.display = "none";
    showStatus("تم إلغاء الاقتران.", "info");
  });

  // Open App Action
  openAppBtn.addEventListener("click", async () => {
    const st = await chrome.storage.local.get(["owi_backend_url"]);
    chrome.tabs.create({ url: st.owi_backend_url || DEFAULT_BACKEND });
  });

  // Capture Active WhatsApp Chat Action
  captureBtn.addEventListener("click", async () => {
    showStatus("جارٍ فحص تبويب واتساب ويب واستخراج الرسائل...", "info");
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab || !tab.url || !tab.url.includes("web.whatsapp.com")) {
        showStatus("يرجى فتح واتساب ويب (web.whatsapp.com) والمحادثة المطلوبة أولاً.", "error");
        return;
      }

      chrome.tabs.sendMessage(tab.id, { action: "capture_active_chat" }, async (response) => {
        if (chrome.runtime.lastError) {
          showStatus("يرجى تحديث صفحة واتساب ويب ثم المحاولة مرة أخرى.", "error");
          return;
        }

        if (!response || !response.messages || response.messages.length === 0) {
          showStatus("لم يتم العثور على رسائل مرئية في المحادثة المفتوحة حالياً.", "error");
          return;
        }

        const creds = await chrome.storage.local.get(["owi_token", "owi_backend_url"]);
        const token = creds.owi_token;
        const sUrl = creds.owi_backend_url || DEFAULT_BACKEND;

        showStatus(`تم جمع ${response.messages.length} رسالة. جارٍ الحفظ في OWI...`, "info");

        try {
          const postRes = await fetch(`${sUrl}/api/companion/ingest`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "Authorization": `Bearer ${token}`
            },
            body: JSON.stringify({
              chat_title: response.chat_title || "WhatsApp Web Conversation",
              messages: response.messages
            })
          });

          const postData = await postRes.json();
          if (postRes.ok) {
            showStatus(
              `✓ نجاح! تم استيعاب ${postData.messages_ingested} رسالة بنجاح في محادثة "${postData.conversation_title}".`,
              "success"
            );
          } else {
            showStatus(`خطأ من الخادم: ${postData.detail || "تعذر الاستيعاب"}`, "error");
          }
        } catch (postErr) {
          showStatus(`تعذر إرسال البيانات إلى ${sUrl}: ${postErr.message}`, "error");
        }
      });
    } catch (e) {
      showStatus("حدث خطأ: " + e.message, "error");
    }
  });
});
