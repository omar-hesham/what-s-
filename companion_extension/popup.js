/**
 * OWI Companion Popup Script v3.0
 * Handles 6-digit pairing, bulk capture configuration (Mode A & B, Egypt date order),
 * live progress monitoring, cancellation, and redacted diagnostic logs viewing.
 */

const DEFAULT_BACKEND = "http://127.0.0.1:8765";

document.addEventListener("DOMContentLoaded", async () => {
  const connBadge = document.getElementById("conn-badge");
  const pairSection = document.getElementById("pair-section");
  const captureSection = document.getElementById("capture-section");
  const statusBox = document.getElementById("status-box");
  const backendInput = document.getElementById("backend-url");
  const pairCodeInput = document.getElementById("pair-code");
  const pairBtn = document.getElementById("pair-btn");
  const openAppBtn = document.getElementById("open-app-btn");
  const unpairBtn = document.getElementById("unpair-btn");

  const modeVisible = document.getElementById("mode-visible");
  const modeRange = document.getElementById("mode-range");
  const rangeInputs = document.getElementById("range-inputs");
  const fromDatetimeInput = document.getElementById("from-datetime");
  const toDatetimeInput = document.getElementById("to-datetime");
  const dateOrderSelect = document.getElementById("date-order-select");

  const configControls = document.getElementById("config-controls");
  const startBulkBtn = document.getElementById("start-bulk-btn");
  const activeProgressCard = document.getElementById("active-progress-card");
  const progressStageTxt = document.getElementById("progress-stage-txt");
  const progressStatsTxt = document.getElementById("progress-stats-txt");
  const cancelCaptureBtn = document.getElementById("cancel-capture-btn");
  const summaryCard = document.getElementById("summary-card");

  const toggleDiagBtn = document.getElementById("toggle-diag-btn");
  const diagPanel = document.getElementById("diag-panel");
  const diagContent = document.getElementById("diag-content");
  const copyDiagBtn = document.getElementById("copy-diag-btn");
  const clearDiagBtn = document.getElementById("clear-diag-btn");

  let pollTimer = null;

  function showStatus(text, type = "info") {
    statusBox.style.display = "block";
    statusBox.className = `status-msg status-${type}`;
    statusBox.innerText = text;
  }

  function hideStatus() {
    statusBox.style.display = "none";
  }

  // Set default datetime values for date range (last 7 days to now)
  const now = new Date();
  const sevenDaysAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000);
  const toIsoLocal = (d) => {
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };
  fromDatetimeInput.value = toIsoLocal(sevenDaysAgo);
  toDatetimeInput.value = toIsoLocal(now);

  // Toggle Mode Radios
  modeVisible.addEventListener("change", () => {
    rangeInputs.style.display = "none";
  });
  modeRange.addEventListener("change", () => {
    rangeInputs.style.display = "block";
  });

  // Diagnostics Panel Toggle
  async function refreshDiagnosticsView() {
    const logs = await OWIDiagnosticLogger.getStoredLogs();
    if (!logs || !logs.length) {
      diagContent.innerText = "لا توجد سجلات بعد.";
    } else {
      diagContent.innerText = JSON.stringify(logs, null, 2);
    }
  }

  toggleDiagBtn.addEventListener("click", async () => {
    if (diagPanel.style.display === "none") {
      await refreshDiagnosticsView();
      diagPanel.style.display = "block";
    } else {
      diagPanel.style.display = "none";
    }
  });

  copyDiagBtn.addEventListener("click", async () => {
    const logs = await OWIDiagnosticLogger.getStoredLogs();
    await navigator.clipboard.writeText(JSON.stringify(logs, null, 2));
    copyDiagBtn.innerText = "✓ تم النسخ";
    setTimeout(() => { copyDiagBtn.innerText = "نسخ"; }, 1500);
  });

  clearDiagBtn.addEventListener("click", async () => {
    await OWIDiagnosticLogger.clearLogs();
    await refreshDiagnosticsView();
  });

  // Ensure trusted storage access level
  if (chrome.storage && chrome.storage.local && typeof chrome.storage.local.setAccessLevel === "function") {
    try {
      await chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });
    } catch (e) {}
  }

  // Load Saved Pairing State from trusted storage.local (survives browser restart)
  let localState = await chrome.storage.local.get(["owi_token", "owi_backend_url"]);
  let token = localState.owi_token || null;

  // Migration: Check if token was previously in session storage
  if (!token && chrome.storage && chrome.storage.session) {
    try {
      const sessionState = await chrome.storage.session.get(["owi_token"]);
      if (sessionState && sessionState.owi_token) {
        token = sessionState.owi_token;
        await chrome.storage.local.set({ owi_token: token });
        await chrome.storage.session.remove(["owi_token"]);
      }
    } catch (e) {}
  }

  const backendUrl = localState.owi_backend_url || DEFAULT_BACKEND;
  backendInput.value = backendUrl;

  if (token) {
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

  // Pairing Action
  pairBtn.addEventListener("click", async () => {
    const code = pairCodeInput.value.trim();
    const serverUrl = backendInput.value.trim() || DEFAULT_BACKEND;
    if (!code || code.length !== 6) {
      showStatus("يرجى إدخال رمز اقتران صحيح مكوّن من 6 أرقام.", "error");
      return;
    }

    showStatus("جارٍ التحقق من الرمز والاقتران...", "info");
    await OWIDiagnosticLogger.log("pairing", "PAIRING_ATTEMPT", 0, "Validating 6-digit code");

    try {
      const res = await fetch(`${serverUrl}/api/companion/pairing/pair`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: code, device_name: "Browser Extension" })
      });
      const data = await res.json();
      if (res.ok && data.status === "paired" && data.token) {
        if (chrome.storage && chrome.storage.local && typeof chrome.storage.local.setAccessLevel === "function") {
          try {
            await chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });
          } catch (e) {}
        }
        await chrome.storage.local.set({
          owi_token: data.token,
          owi_backend_url: serverUrl
        });
        if (chrome.storage && chrome.storage.session) {
          await chrome.storage.session.remove(["owi_token"]);
        }
        await OWIDiagnosticLogger.log("pairing", "SUCCESS", 0, "ok");
        connBadge.innerText = "🟢 متصل وآمن";
        connBadge.className = "badge badge-connected";
        pairSection.style.display = "none";
        captureSection.style.display = "block";
        await loadAvailableTargets();
        showStatus("✓ تم الاقتران بنجاح! الإضافة جاهزة لالتقاط المحادثات.", "success");
      } else {
        await OWIDiagnosticLogger.log("pairing", "ERR_AUTH", 0, "auth_rejected");
        showStatus(`فشل الاقتران: ${data.detail || "رمز غير صالح أو منتهي الصلاحية"}`, "error");
      }
    } catch (err) {
      await OWIDiagnosticLogger.log("pairing", "ERR_NETWORK", 0, "backend_unreachable");
      showStatus(`تعذر الاتصال بالخادم على ${serverUrl}. تأكد من تشغيل تطبيق OWI.`, "error");
    }
  });

  // Unpair Action
  unpairBtn.addEventListener("click", async () => {
    if (chrome.storage && chrome.storage.local) {
      await chrome.storage.local.remove(["owi_token"]);
    }
    if (chrome.storage && chrome.storage.session) {
      await chrome.storage.session.remove(["owi_token"]);
    }
    await OWIDiagnosticLogger.log("pairing", "UNPAIRED", 0, "ok");
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

  const targetSelect = document.getElementById("target-conversation-select");
  const importedTargetWarning = document.getElementById("imported-target-warning");
  const confirmMergeCheck = document.getElementById("confirm-merge-check");
  const activeChatIndicator = document.getElementById("active-chat-indicator");
  const activeChatTitleTxt = document.getElementById("active-chat-title-txt");

  const INVALID_CHAT_TITLES = new Set([
    "profile details",
    "تفاصيل الملف الشخصي",
    "معلومات جهة الاتصال",
    "contact info",
    "معلومات المجموعة",
    "group info"
  ]);

  function isInvalidTitle(title) {
    if (!title || typeof title !== "string") return true;
    const norm = title.trim().toLowerCase();
    if (INVALID_CHAT_TITLES.has(norm)) return true;
    if (norm.startsWith("profile details") || norm.startsWith("تفاصيل الملف الشخصي")) return true;
    return false;
  }

  function isMatchingChatTitle(t1, t2) {
    if (!t1 || !t2) return false;
    const n1 = t1.trim().toLowerCase();
    const n2 = t2.trim().toLowerCase();
    if (n1 === n2) return true;

    // Strict: Reject match if one is a group and the other is not
    const groupIndicators = ["group", "مجموعة"];
    const isG1 = groupIndicators.some((gi) => n1.includes(gi));
    const isG2 = groupIndicators.some((gi) => n2.includes(gi));
    if (isG1 !== isG2) return false;

    function extractArchiveNameSegment(titleStr) {
      let s = titleStr.trim().toLowerCase();
      s = s.replace(/\(.*?\)\s*$/, "").trim();
      s = s.replace(/\s*[-–—]\s*(?:\d{2,4}\s*)?(?:export|archive|تصدير|أرشيف|backup|نسخة).*$/i, "").trim();
      s = s.replace(/\s*[-–—]\s*(?:export|archive|تصدير|أرشيف|backup|نسخة)(?:\s*\d{2,4})?.*$/i, "").trim();
      const prefixes = [
        "whatsapp chat with ", "whatsapp chat - ", "whatsapp chat ",
        "chat with ", "imported archive ", "archive with ", "archive - ", "archive ",
        "whatsapp web ",
        "محادثة مع ", "محادثة ", "دردشة مع ", "دردشة ", "رسائل مع ", "رسائل ",
        "أرشيف محادثة مع ", "أرشيف محادثة ", "أرشيف دردشة مع ", "أرشيف دردشة ", "أرشيف "
      ];
      for (const pfx of prefixes) {
        if (s.startsWith(pfx)) {
          s = s.substring(pfx.length).trim();
          break;
        }
      }
      s = s.replace(/\(.*?\)\s*$/, "").trim();
      s = s.replace(/\s*[-–—]\s*(?:\d{2,4}\s*)?(?:export|archive|تصدير|أرشيف|backup|نسخة).*$/i, "").trim();
      return s;
    }

    const seg1 = extractArchiveNameSegment(t1);
    const seg2 = extractArchiveNameSegment(t2);

    if (seg1 && seg1 === n2) return true;
    if (seg2 && seg2 === n1) return true;
    if (seg1 && seg2 && seg1 === seg2 && (seg1 !== n1 || seg2 !== n2)) return true;

    return false;
  }


  async function getActiveWhatsAppChatTitle() {
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab || !tab.url || !tab.url.includes("web.whatsapp.com")) {
        return null;
      }
      return new Promise((resolve) => {
        chrome.tabs.sendMessage(tab.id, { action: "get_active_chat_title" }, (resp) => {
          if (chrome.runtime.lastError || !resp || !resp.success) {
            resolve(null);
          } else {
            resolve(resp.chatTitle);
          }
        });
      });
    } catch (e) {
      return null;
    }
  }

  async function loadAvailableTargets() {
    if (!targetSelect) return;
    try {
      const activeChatTitle = await getActiveWhatsAppChatTitle();
      if (activeChatTitle && activeChatIndicator && activeChatTitleTxt) {
        activeChatTitleTxt.innerText = `"${activeChatTitle}"`;
        activeChatIndicator.style.display = "block";
      }

      const res = await new Promise((resolve) => {
        chrome.runtime.sendMessage({ action: "bridge_get_targets" }, (r) => {
          resolve(r || { success: false });
        });
      });
      if (res && res.success && Array.isArray(res.targets)) {
        targetSelect.innerHTML = '<option value="new">-- إنشاء محادثة رفيق جديدة (تلقائي) --</option>';
        let matchedTarget = null;

        for (const t of res.targets) {
          const opt = document.createElement("option");
          opt.value = t.id;
          opt.dataset.sourceType = t.source_type;
          opt.dataset.msgCount = t.message_count;
          opt.dataset.chatTitle = t.title;

          const isMatch = activeChatTitle && isMatchingChatTitle(t.title, activeChatTitle);

          if (isMatch && !matchedTarget) {
            matchedTarget = t;
            opt.selected = true;
            opt.innerText = `⭐️ [#${t.id}] ${t.title} (${t.message_count} رسالة - ${t.source_type}) [مطابق لمحادثة واتساب الحالية]`;
          } else {
            opt.innerText = `[#${t.id}] ${t.title} (${t.message_count} رسالة - ${t.source_type})`;
          }
          targetSelect.appendChild(opt);
        }

        if (matchedTarget) {
          const isImported = matchedTarget.source_type && matchedTarget.source_type !== "companion";
          if (importedTargetWarning) {
            importedTargetWarning.style.display = isImported ? "block" : "none";
          }
        }
      }
    } catch (e) {}
  }

  if (targetSelect) {
    targetSelect.addEventListener("change", () => {
      const selectedOpt = targetSelect.selectedIndex >= 0 ? targetSelect.options[targetSelect.selectedIndex] : null;
      const isImported = selectedOpt && selectedOpt.dataset.sourceType && selectedOpt.dataset.sourceType !== "companion" && selectedOpt.value !== "new";
      if (importedTargetWarning) {
        importedTargetWarning.style.display = isImported ? "block" : "none";
      }
      if (confirmMergeCheck && !isImported) {
        confirmMergeCheck.checked = false;
      }
    });
  }

  // Check Current Capture State (Handles popup reopening during long capture)
  async function syncCaptureUI() {
    const st = await chrome.storage.local.get(["owi_capture_state"]);
    const cap = st.owi_capture_state;
    if (!cap) return;

    if (cap.status === "running") {
      configControls.style.display = "none";
      activeProgressCard.style.display = "block";
      summaryCard.style.display = "none";

      const stageLabels = {
        initializing: "جارٍ فحص المحادثة...",
        scrolling_up: "جارٍ التمرير لأعلى لتحميل الرسائل الأقدم...",
        scrolling_down: "جارٍ التمرير لأسفل لجمع الرسائل...",
        ingesting: "جارٍ استيعاب الدفعات في خادم OWI..."
      };

      progressStageTxt.innerText = stageLabels[cap.stage] || cap.stage || "جارٍ الالتقاط...";
      let statsStr = `تم فحص: ${cap.messagesScanned || 0} رسالة | تم استيعاب: ${cap.messagesIngested || 0}`;
      if (cap.attachmentStats) {
        const a = cap.attachmentStats;
        statsStr += `\nالمرفقات: ${a.savedOriginal || 0} أصلي محفوظ | ${a.previewOnly || 0} معاينة | ${a.unavailable || 0} غير متوفر`;
      }
      progressStatsTxt.innerText = statsStr;

      if (!pollTimer) {
        pollTimer = setInterval(syncCaptureUI, 600);
      }
    } else if (cap.status === "finished") {
      configControls.style.display = "block";
      activeProgressCard.style.display = "none";
      summaryCard.style.display = "block";

      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }

      let attBreakdown = "";
      if (cap.attachmentStats) {
        const a = cap.attachmentStats;
        attBreakdown = `\nالمرفقات: ${a.savedOriginal || 0} أصل محفوظ، ${a.previewOnly || 0} معاينة فقط، ${a.unavailable || 0} غير متوفر، ${a.expired || 0} منتهي، ${a.tooLarge || 0} كبير جداً، ${a.unsupported || 0} غير مدعوم، ${a.failed || 0} فشل.`;
      }

      if (cap.completenessStatus === "complete") {
        summaryCard.className = "status-msg status-success";
        summaryCard.innerText = `✓ اكتمل الالتقاط بالكامل!\nتم استيعاب ${cap.messagesIngested} رسالة بنجاح في محادثة "${cap.chatTitle}". (تخطي ${cap.duplicatesSkipped || 0} مكررة).${attBreakdown}`;
      } else {
        const reasonLabels = {
          history_exhausted_before_from_bound: "انتهت سجلات المحادثة قبل الوصول لتاريخ البداية المطلوب",
          history_exhausted_before_to_bound: "انتهت سجلات المحادثة قبل الوصول لتاريخ النهاية المطلوب",
          scroll_attempts_exhausted: "تم بلوغ الحد الأقصى لعدد محاولات التمرير دون الوصول لكامل النطاق",
          traversal_stalled: "توقف التمرير التلقائي بسبب عدم استجابة واجهة المحادثة",
          cancelled_by_user: "تم الإلغاء بواسطة المستخدم",
          chat_navigation_detected: "تم الانتقال لمحادثة أخرى أثناء الالتقاط",
          first_visible_anchor_not_found: "تعذر تحديد نقطة البداية المرئية الحالية في المحادثة",
          zero_messages_captured: "لم يتم العثور على أي رسائل مطابقة في المحادثة",
          unparseable_timestamp_present: "تم رصد رسائل بتواريخ غير قابلة للتحقق فاستُبعدت حفظاً للدقة",
          chunk_ingest_failed: "فشل استيعاب دفعة من الرسائل في الخادم"
        };
        const rText = reasonLabels[cap.partialReason] || cap.partialReason || "سبب غير محدد";
        summaryCard.className = "status-msg status-warning";
        summaryCard.innerText = `⚠️ تم التقاط جزئي!\nتم استيعاب ${cap.messagesIngested || 0} رسالة. السبب: ${rText}.${attBreakdown}`;
      }
    } else if (cap.status === "error") {
      configControls.style.display = "block";
      activeProgressCard.style.display = "none";
      summaryCard.style.display = "block";
      summaryCard.className = "status-msg status-error";
      summaryCard.innerText = "فشل الالتقاط: تعذر إكمال العملية بشكل سليم.";

      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    }
  }

  await syncCaptureUI();
  if (token) {
    await loadAvailableTargets();
  }

  // Start Bulk Capture Action
  startBulkBtn.addEventListener("click", async () => {
    hideStatus();
    summaryCard.style.display = "none";

    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.url || !tab.url.includes("web.whatsapp.com")) {
      showStatus("يرجى فتح واتساب ويب (web.whatsapp.com) والمحادثة المطلوبة أولاً.", "error");
      return;
    }

    // Verify active WhatsApp tab & query chat title
    const activeChatTitle = await getActiveWhatsAppChatTitle();
    if (!activeChatTitle || isInvalidTitle(activeChatTitle)) {
      showStatus(
        `خطأ: تعذر التعرف على محادثة واتساب صالحة (العنوان المرصود: "${activeChatTitle || "غير محدد"}"). يرجى فتح محادثة WhatsApp المطلوبة والتأكد من عدم فتح تفاصيل الملف الشخصي (Profile details).`,
        "error"
      );
      return;
    }

    const selectedTargetVal = targetSelect ? targetSelect.value : "new";
    const selectedOpt = targetSelect && targetSelect.selectedIndex >= 0 ? targetSelect.options[targetSelect.selectedIndex] : null;
    const isImported = selectedOpt && selectedOpt.dataset.sourceType && selectedOpt.dataset.sourceType !== "companion" && selectedTargetVal !== "new";

    // Validate target title vs active chat title
    if (selectedTargetVal !== "new" && selectedOpt && selectedOpt.dataset.chatTitle) {
      if (!isMatchingChatTitle(selectedOpt.dataset.chatTitle, activeChatTitle)) {
        showStatus(
          `خطأ في التطابق: محادثة واتساب المفتوحة حالياً ("${activeChatTitle}") لا تطابق المحادثة المحددة كوجهة ("${selectedOpt.dataset.chatTitle}"). يرجى فتح محادثة "${selectedOpt.dataset.chatTitle}" في واتساب ويب أولاً منعاً لخلط الرسائل.`,
          "error"
        );
        return;
      }
    }

    if (isImported && (!confirmMergeCheck || !confirmMergeCheck.checked)) {
      showStatus("يرجى تأكيد رغبتك في الدمج مع المحادثة المستوردة قبل البدء.", "error");
      return;
    }

    const targetConversationId = selectedTargetVal !== "new" ? Number(selectedTargetVal) : null;
    const confirmTargetMerge = Boolean(confirmMergeCheck && confirmMergeCheck.checked);

    const mode = modeRange.checked ? "date_range" : "visible_to_newest";
    let fromDate = null;
    let toDate = null;

    if (mode === "date_range") {
      fromDate = fromDatetimeInput.value;
      toDate = toDatetimeInput.value;
      if (!fromDate || !toDate) {
        showStatus("يرجى تحديد تاريخ البداية والنهاية للنطاق الزمني.", "error");
        return;
      }
      if (new Date(fromDate) > new Date(toDate)) {
        showStatus("تاريخ البداية يجب أن يكون قبل تاريخ النهاية.", "error");
        return;
      }
    }

    const dateOrder = dateOrderSelect.value || "DD/MM/YYYY";

    // Switch UI to running state immediately
    configControls.style.display = "none";
    activeProgressCard.style.display = "block";
    progressStageTxt.innerText = "جارٍ بدء الالتقاط الشامل...";
    progressStatsTxt.innerText = "تم فحص: 0 رسالة | تم استيعاب: 0";

    chrome.tabs.sendMessage(
      tab.id,
      {
        action: "start_bulk_capture",
        config: {
          mode,
          fromDate,
          toDate,
          dateOrder,
          targetConversationId,
          confirmTargetMerge,
          captureMedia: true,
          chunkSize: 50
        }
      },
      (response) => {
        if (chrome.runtime.lastError) {
          configControls.style.display = "block";
          activeProgressCard.style.display = "none";
          showStatus("يرجى تحديث صفحة واتساب ويب ثم المحاولة مرة أخرى.", "error");
          return;
        }
        if (!pollTimer) {
          pollTimer = setInterval(syncCaptureUI, 600);
        }
      }
    );
  });

  // Cancel Capture Action
  cancelCaptureBtn.addEventListener("click", async () => {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab && tab.id) {
      chrome.tabs.sendMessage(tab.id, { action: "cancel_bulk_capture" });
    }
    progressStageTxt.innerText = "جارٍ إيقاف الالتقاط وحفظ الرسائل المستلمة...";
  });
});
