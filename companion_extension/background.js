/**
 * OWI Companion - Background Service Worker (Manifest V3)
 * Secure loopback network bridge and extension lifecycle manager.
 *
 * Security & Isolation Guarantees:
 * - Content scripts NEVER call fetch() directly across origins.
 * - Scoped companion token is stored in chrome.storage.local configured strictly with
 *   chrome.storage.local.setAccessLevel({ accessLevel: 'TRUSTED_CONTEXTS' }).
 *   Content scripts (untrusted contexts) CANNOT access or read chrome.storage.local.
 * - Persistent across browser restarts (unlike session storage).
 * - Migrates legacy session / local storage tokens into trusted storage.local.
 * - Fails closed (STORAGE_SECURITY_ERROR) if trusted storage cannot be guaranteed.
 * - Content-script progress (owi_capture_state) and diagnostics are bridged via runtime messages.
 * - Only fixed loopback endpoints (127.0.0.1 / localhost) are permitted; arbitrary URLs are rejected.
 * - Serialized ingest payload size is strictly bounded to 2 MB (MAX_INGEST_PAYLOAD_BYTES).
 * - Diagnostics batch size is strictly bounded to 50 items / 100 KB.
 * - Validates sender origin (extension popup or web.whatsapp.com tab only).
 */

const MAX_INGEST_PAYLOAD_BYTES = 2 * 1024 * 1024; // 2 MB genuine serialized limit
const MAX_DIAGNOSTICS_COUNT = 50;
const MAX_DIAGNOSTICS_PAYLOAD_BYTES = 100 * 1024; // 100 KB limit
const MAX_MEDIA_DIRECT_BYTES = 5 * 1024 * 1024; // 5 MB serialized base64 limit
const MAX_MEDIA_CHUNK_BYTES = 2 * 1024 * 1024; // 2 MB chunk serialized base64 limit

let trustedStorageConfigured = false;
let trustedStorageError = null;
let pendingDownload = null;
let lastCompletedDownloadResult = null;

function setupDownloadsListener(downloadsApi = (typeof chrome !== "undefined" ? chrome.downloads : null)) {
  if (!downloadsApi) return;
  if (downloadsApi.onCreated && typeof downloadsApi.onCreated.addListener === "function") {
    downloadsApi.onCreated.addListener((item) => {
      if (!pendingDownload) return;
      if (pendingDownload.concurrentConflict) return;

      const itemTime = item.startTime ? new Date(item.startTime).getTime() : Date.now();
      // Strict: Reject pre-existing download that started before arming
      if (itemTime < pendingDownload.armedTime - 50) {
        return; // Pre-existing download from before arming
      }

      // Ignore unrelated download created from another site
      if (item.referrer && !item.referrer.includes("whatsapp.com") && item.url && !item.url.startsWith("blob:") && !item.url.includes("whatsapp.com")) {
        return;
      }

      // If another download is created concurrently while armed for single-flight capture: fail safely
      if (pendingDownload.downloadId && pendingDownload.downloadId !== item.id) {
        pendingDownload.concurrentConflict = true;
        pendingDownload.complete({
          success: false,
          error_code: "CONCURRENT_DOWNLOAD_CONFLICT",
          error: "Multiple concurrent downloads detected while awaiting single-flight capture"
        });
        return;
      }

      pendingDownload.downloadId = item.id;
      pendingDownload.initialFilename = item.filename;
      pendingDownload.url = item.url;
      pendingDownload.referrer = item.referrer;
      pendingDownload.mime = item.mime;
    });
  }

  if (downloadsApi.onChanged && typeof downloadsApi.onChanged.addListener === "function") {
    downloadsApi.onChanged.addListener((delta) => {
      if (!pendingDownload) return;
      if (pendingDownload.concurrentConflict) return;

      // STRICT: Require onCreated to have established the downloadId!
      // Under NO circumstances adopt delta.id if onCreated has not matched!
      if (!pendingDownload.downloadId || delta.id !== pendingDownload.downloadId) {
        return;
      }

      if (delta.state) {
        if (delta.state.current === "complete") {
          const finalizeDownload = (item) => {
            if (!pendingDownload) return;
            if (!item || !item.filename) {
              pendingDownload.complete({ success: false, error_code: "DOWNLOAD_NOT_FOUND", error: "Download record not found" });
              return;
            }
            if (item.state && item.state !== "complete") {
              pendingDownload.complete({ success: false, error_code: "DOWNLOAD_INCOMPLETE", error: "Download not complete" });
              return;
            }

            // Correlate origin if referrer or url available
            if (item.referrer && !item.referrer.includes("whatsapp.com") && item.url && !item.url.startsWith("blob:") && !item.url.includes("whatsapp.com")) {
              pendingDownload.complete({
                success: false,
                error_code: "CORRELATION_ORIGIN_MISMATCH",
                error: "Download did not originate from WhatsApp Web"
              });
              return;
            }

            const fname = (item.filename || "").split(/[\\/]/).pop().toLowerCase();
            const ext = fname.includes(".") ? ("." + fname.split(".").pop()) : "";
            const mime = (item.mime || "").toLowerCase();

            // Correlate expected type
            if (pendingDownload.expectedType) {
              const t = pendingDownload.expectedType.toLowerCase();
              if (t === "audio" || t === "voice") {
                const audioExts = [".ogg", ".opus", ".mp3", ".wav", ".m4a", ".aac", ".webm"];
                const isAudio = audioExts.includes(ext) || mime.startsWith("audio/");
                if (ext && !isAudio) {
                  pendingDownload.complete({
                    success: false,
                    error_code: "CORRELATION_TYPE_MISMATCH",
                    error: `Downloaded file (${fname}) does not match expected audio attachment`
                  });
                  return;
                }
              } else if (t === "image") {
                const imageExts = [".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"];
                const isImage = imageExts.includes(ext) || mime.startsWith("image/");
                if (ext && !isImage) {
                  pendingDownload.complete({
                    success: false,
                    error_code: "CORRELATION_TYPE_MISMATCH",
                    error: `Downloaded file (${fname}) does not match expected image attachment`
                  });
                  return;
                }
              } else if (t === "video") {
                const videoExts = [".mp4", ".webm", ".3gp", ".mov", ".avi", ".mkv"];
                const isVideo = videoExts.includes(ext) || mime.startsWith("video/");
                if (ext && !isVideo) {
                  pendingDownload.complete({
                    success: false,
                    error_code: "CORRELATION_TYPE_MISMATCH",
                    error: `Downloaded file (${fname}) does not match expected video attachment`
                  });
                  return;
                }
              }
            }

            // Correlate expected filename
            if (pendingDownload.expectedFilename) {
              const cleanExpected = pendingDownload.expectedFilename.trim().toLowerCase();
              const expectedBase = cleanExpected.replace(/\.[^/.]+$/, "");
              const expectedExt = cleanExpected.includes(".") ? ("." + cleanExpected.split(".").pop()) : "";
              if (expectedExt && ext && expectedExt !== ext) {
                pendingDownload.complete({
                  success: false,
                  error_code: "CORRELATION_FILENAME_MISMATCH",
                  error: `Downloaded file extension (${ext}) does not match expected (${expectedExt})`
                });
                return;
              }
              if (expectedBase && !["voice", "audio", "document", "whatsapp", "file"].includes(expectedBase)) {
                const downloadedBase = fname.replace(/\.[^/.]+$/, "").replace(/\s*\(\d+\)$/, "");
                const isVoice = (pendingDownload.expectedType === "voice" || pendingDownload.expectedType === "audio");
                if (!isVoice && downloadedBase && downloadedBase !== expectedBase && !downloadedBase.startsWith(expectedBase) && !expectedBase.startsWith(downloadedBase)) {
                  pendingDownload.complete({
                    success: false,
                    error_code: "CORRELATION_FILENAME_MISMATCH",
                    error: `Downloaded file name (${fname}) does not match expected (${cleanExpected})`
                  });
                  return;
                }
              }
            }

            pendingDownload.complete({
              success: true,
              downloadPath: item.filename,
              fileSize: item.fileSize || item.totalBytes || 0,
              mime: item.mime || null
            });
          };

          if (typeof downloadsApi.search === "function") {
            downloadsApi.search({ id: delta.id }, (results) => {
              const item = results && results[0];
              finalizeDownload(item);
            });
          } else {
            finalizeDownload({
              filename: delta.filename?.current || pendingDownload.initialFilename || "downloaded_file",
              state: "complete",
              fileSize: 0
            });
          }
        } else if (delta.state.current === "interrupted") {
          pendingDownload.complete({
            success: false,
            error_code: "DOWNLOAD_INTERRUPTED",
            error: delta.error?.current || "Download interrupted"
          });
        }
      }
    });
  }
}


if (typeof chrome !== "undefined" && chrome.downloads) {
  setupDownloadsListener(chrome.downloads);
}

async function ensureTrustedStorage(storageLocal) {
  if (trustedStorageConfigured) return true;
  if (!storageLocal) {
    trustedStorageError = "Storage API not available";
    return false;
  }
  if (typeof storageLocal.setAccessLevel !== "function") {
    trustedStorageError = "chrome.storage.local.setAccessLevel is not supported";
    return false;
  }
  try {
    await storageLocal.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });
    trustedStorageConfigured = true;
    trustedStorageError = null;
    return true;
  } catch (err) {
    trustedStorageError = err?.message || "Failed to configure TRUSTED_CONTEXTS";
    trustedStorageConfigured = false;
    return false;
  }
}

// In extension runtime, configure trusted storage immediately on worker load
if (typeof chrome !== "undefined" && chrome.storage) {
  if (chrome.storage.local && typeof chrome.storage.local.setAccessLevel === "function") {
    chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" })
      .then(() => { trustedStorageConfigured = true; })
      .catch((e) => {
        trustedStorageConfigured = false;
        trustedStorageError = e?.message || "Storage error";
      });
  }
  if (chrome.storage.session && typeof chrome.storage.session.setAccessLevel === "function") {
    chrome.storage.session.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" }).catch(() => {});
  }
}

function isAllowedLoopbackUrl(urlStr) {
  if (!urlStr || typeof urlStr !== "string") return false;
  try {
    const u = new URL(urlStr);
    return (u.hostname === "127.0.0.1" || u.hostname === "localhost") && u.protocol === "http:";
  } catch (e) {
    return false;
  }
}

function isValidSender(sender) {
  if (!sender) return false;
  // Extension's own pages (popup)
  if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.id) {
    if (sender.id === chrome.runtime.id && sender.url && sender.url.startsWith(`chrome-extension://${chrome.runtime.id}/`)) {
      return true;
    }
  } else if (sender.id && sender.url && sender.url.startsWith(`chrome-extension://${sender.id}/`)) {
    return true;
  }
  // WhatsApp Web tab
  if (sender.tab && sender.tab.url && sender.tab.url.startsWith("https://web.whatsapp.com/")) {
    return true;
  }
  return false;
}

function calculateByteLength(str) {
  if (typeof Buffer !== "undefined") {
    return Buffer.byteLength(str, "utf8");
  }
  if (typeof TextEncoder !== "undefined") {
    return new TextEncoder().encode(str).length;
  }
  return str.length;
}

async function getStoredTokenAndUrl(storageLocal, storageSession) {
  let token = null;
  let backendUrl = "http://127.0.0.1:8765";

  if (storageLocal && typeof storageLocal.get === "function") {
    const localStore = await storageLocal.get(["owi_token", "owi_backend_url"]);
    if (localStore) {
      if (localStore.owi_token) token = localStore.owi_token;
      if (localStore.owi_backend_url) backendUrl = localStore.owi_backend_url;
    }
  }

  // Token migration: If token was in session storage (from previous version), migrate to trusted storage.local
  if (!token && storageSession && typeof storageSession.get === "function") {
    try {
      const sessStore = await storageSession.get(["owi_token", "owi_backend_url"]);
      if (sessStore && sessStore.owi_token) {
        token = sessStore.owi_token;
        if (sessStore.owi_backend_url) backendUrl = sessStore.owi_backend_url;
        if (storageLocal && typeof storageLocal.set === "function") {
          await storageLocal.set({
            owi_token: token,
            owi_backend_url: backendUrl
          });
        }
        if (typeof storageSession.remove === "function") {
          await storageSession.remove(["owi_token"]);
        }
      }
    } catch (e) {}
  }

  return { token, backendUrl };
}

let inMemoryCaptureState = null;

async function handleRuntimeMessage(message, sender, sendResponse, injectedDeps = {}) {
  if (!isValidSender(sender)) {
    sendResponse({ success: false, error_code: "UNAUTHORIZED_SENDER", error: "Unauthorized sender" });
    return true;
  }

  // Reject any attempt by caller to inject arbitrary URL or endpoint
  if (message.url || message.endpoint || message.targetUrl) {
    sendResponse({
      success: false,
      error_code: "DISALLOWED_ENDPOINT",
      error: "Runtime message cannot specify arbitrary URL or endpoint"
    });
    return true;
  }

  const storageSession = injectedDeps.storageSession || (typeof chrome !== "undefined" && chrome.storage ? chrome.storage.session : null);
  const storageLocal = injectedDeps.storageLocal || (typeof chrome !== "undefined" && chrome.storage ? chrome.storage.local : null);
  const fetchFn = injectedDeps.fetchFn || (typeof fetch !== "undefined" ? fetch : null);

  // If injectedDeps sets trustedStorageConfigured override for test runner
  if (injectedDeps.trustedStorageConfigured !== undefined) {
    trustedStorageConfigured = injectedDeps.trustedStorageConfigured;
  }

  // 1. Loopback Ingest Bridge
  if (message.action === "bridge_ingest_chunk") {
    try {
      const isSecured = await ensureTrustedStorage(storageLocal);
      if (!isSecured) {
        sendResponse({ success: false, error_code: "STORAGE_SECURITY_ERROR", error: trustedStorageError || "Storage security error" });
        return true;
      }

      const { token, backendUrl } = await getStoredTokenAndUrl(storageLocal, storageSession);

      if (!token) {
        sendResponse({ success: false, error_code: "UNPAIRED", error: "Extension is not paired" });
        return true;
      }

      if (!isAllowedLoopbackUrl(backendUrl)) {
        sendResponse({ success: false, error_code: "INVALID_BACKEND_URL", error: "Disallowed backend origin" });
        return true;
      }

      const chunk = message.chunk;
      if (!Array.isArray(chunk) || chunk.length === 0 || chunk.length > 100) {
        sendResponse({ success: false, error_code: "INVALID_CHUNK", error: "Chunk size invalid or out of bounds (1-100)" });
        return true;
      }

      const payloadObj = {
        chat_title: message.chatTitle,
        session_id: message.sessionId,
        chunk_index: message.chunkIndex,
        total_chunks: message.totalChunks,
        is_last_chunk: message.isLastChunk,
        completeness_status: message.completenessStatus,
        partial_reason: message.partialReason,
        date_order: message.dateOrder,
        target_conversation_id: message.targetConversationId || null,
        confirm_target_merge: Boolean(message.confirmTargetMerge),
        messages: chunk
      };

      const payloadStr = JSON.stringify(payloadObj);
      const payloadBytes = calculateByteLength(payloadStr);

      if (payloadBytes > MAX_INGEST_PAYLOAD_BYTES) {
        sendResponse({
          success: false,
          error_code: "PAYLOAD_TOO_LARGE",
          error: `Ingest payload size (${payloadBytes} bytes) exceeds limit (${MAX_INGEST_PAYLOAD_BYTES} bytes)`
        });
        return true;
      }

      // Fixed loopback target endpoint
      const targetUrl = `${backendUrl}/api/companion/ingest`;

      const res = await fetchFn(targetUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: payloadStr
      });

      if (res.ok) {
        const data = await res.json();
        sendResponse({ success: true, data });
      } else {
        const errData = await res.json().catch(() => ({}));
        sendResponse({
          success: false,
          error_code: (res.status === 401 || res.status === 403) ? "ERR_AUTH" : `HTTP_${res.status}`,
          status: res.status,
          error: errData.detail || "Server error"
        });
      }
    } catch (err) {
      sendResponse({ success: false, error_code: "NETWORK_ERROR", error: "Could not connect to loopback OWI" });
    }
    return true;
  }

  // 2. Loopback Diagnostics Flush Bridge
  if (message.action === "bridge_diagnostics") {
    try {
      const isSecured = await ensureTrustedStorage(storageLocal);
      if (!isSecured) {
        sendResponse({ success: false, error_code: "STORAGE_SECURITY_ERROR", error: trustedStorageError || "Storage security error" });
        return true;
      }

      const { token, backendUrl } = await getStoredTokenAndUrl(storageLocal, storageSession);

      if (!token || !isAllowedLoopbackUrl(backendUrl)) {
        sendResponse({ success: false, error_code: "UNPAIRED" });
        return true;
      }

      let rawEntries = Array.isArray(message.entries) ? message.entries : [];
      if (rawEntries.length === 0 && storageLocal && typeof storageLocal.get === "function") {
        const stored = await storageLocal.get(["owi_diagnostic_logs"]);
        rawEntries = Array.isArray(stored?.owi_diagnostic_logs) ? stored.owi_diagnostic_logs.slice(-50) : [];
      }

      if (rawEntries.length > MAX_DIAGNOSTICS_COUNT) {
        sendResponse({
          success: false,
          error_code: "PAYLOAD_TOO_LARGE",
          error: `Diagnostics batch count (${rawEntries.length}) exceeds maximum (${MAX_DIAGNOSTICS_COUNT})`
        });
        return true;
      }

      const entriesPayload = JSON.stringify({ entries: rawEntries });
      if (calculateByteLength(entriesPayload) > MAX_DIAGNOSTICS_PAYLOAD_BYTES) {
        sendResponse({
          success: false,
          error_code: "PAYLOAD_TOO_LARGE",
          error: `Diagnostics payload size exceeds limit (${MAX_DIAGNOSTICS_PAYLOAD_BYTES} bytes)`
        });
        return true;
      }

      const res = await fetchFn(`${backendUrl}/api/companion/diagnostics`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: entriesPayload
      });

      sendResponse({ success: res.ok });
    } catch (e) {
      sendResponse({ success: false, error_code: "NETWORK_ERROR" });
    }
    return true;
  }

  // 2b. Target Conversations Query Bridge
  if (message.action === "bridge_get_targets") {
    try {
      const isSecured = await ensureTrustedStorage(storageLocal);
      if (!isSecured) {
        sendResponse({ success: false, error_code: "STORAGE_SECURITY_ERROR", error: trustedStorageError || "Storage security error" });
        return true;
      }

      const { token, backendUrl } = await getStoredTokenAndUrl(storageLocal, storageSession);
      if (!token || !isAllowedLoopbackUrl(backendUrl)) {
        sendResponse({ success: false, error_code: "UNPAIRED", error: "Extension is not paired" });
        return true;
      }

      const res = await fetchFn(`${backendUrl}/api/companion/targets`, {
        method: "GET",
        headers: {
          "Authorization": `Bearer ${token}`
        }
      });

      if (res.ok) {
        const data = await res.json();
        sendResponse({ success: true, targets: data.targets || [] });
      } else {
        sendResponse({ success: false, error_code: `HTTP_${res.status}`, status: res.status });
      }
    } catch (e) {
      sendResponse({ success: false, error_code: "NETWORK_ERROR" });
    }
    return true;
  }

  // 2c. Direct Media Upload Bridge
  if (message.action === "bridge_media_upload") {
    try {
      const isSecured = await ensureTrustedStorage(storageLocal);
      if (!isSecured) {
        sendResponse({ success: false, error_code: "STORAGE_SECURITY_ERROR", error: trustedStorageError || "Storage security error" });
        return true;
      }

      const { token, backendUrl } = await getStoredTokenAndUrl(storageLocal, storageSession);
      if (!token || !isAllowedLoopbackUrl(backendUrl)) {
        sendResponse({ success: false, error_code: "UNPAIRED", error: "Extension is not paired" });
        return true;
      }

      const mediaPayload = {
        conversation_id: message.conversationId || null,
        message_id: message.messageId || null,
        platform_msg_id: message.platformMsgId || null,
        message_key: message.messageKey || null,
        session_id: message.sessionId || null,
        attachment_position: message.attachmentPosition || null,
        chat_title: message.chatTitle || null,
        confirm_target_merge: message.confirmTargetMerge || false,
        file_name: message.fileName,
        file_type: message.fileType || "document",
        mime_type: message.mimeType || "application/octet-stream",
        media_base64: message.mediaBase64,
        sha256: message.sha256 || null,
        attachment_status: message.attachmentStatus || "saved-original"
      };

      const payloadStr = JSON.stringify(mediaPayload);
      if (calculateByteLength(payloadStr) > MAX_MEDIA_DIRECT_BYTES) {
        sendResponse({
          success: false,
          error_code: "PAYLOAD_TOO_LARGE",
          error: `Media payload exceeds direct upload limit (${MAX_MEDIA_DIRECT_BYTES} bytes)`
        });
        return true;
      }

      const res = await fetchFn(`${backendUrl}/api/companion/media/upload`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: payloadStr
      });

      if (res.ok) {
        const data = await res.json();
        sendResponse({ success: true, data });
      } else {
        const errData = await res.json().catch(() => ({}));
        sendResponse({
          success: false,
          error_code: `HTTP_${res.status}`,
          status: res.status,
          error: errData.detail || "Server error"
        });
      }
    } catch (e) {
      sendResponse({ success: false, error_code: "NETWORK_ERROR", error: "Could not connect to loopback OWI" });
    }
    return true;
  }

  // 2d. Chunked Media Session Start Bridge
  if (message.action === "bridge_media_session_start") {
    try {
      const isSecured = await ensureTrustedStorage(storageLocal);
      if (!isSecured) {
        sendResponse({ success: false, error_code: "STORAGE_SECURITY_ERROR", error: trustedStorageError || "Storage security error" });
        return true;
      }

      const { token, backendUrl } = await getStoredTokenAndUrl(storageLocal, storageSession);
      if (!token || !isAllowedLoopbackUrl(backendUrl)) {
        sendResponse({ success: false, error_code: "UNPAIRED", error: "Extension is not paired" });
        return true;
      }

      const startPayload = {
        session_id: message.sessionId,
        capture_session_id: message.captureSessionId || message.sessionId || null,
        conversation_id: message.conversationId || null,
        message_id: message.messageId || null,
        platform_msg_id: message.platformMsgId || null,
        message_key: message.messageKey || null,
        attachment_position: message.attachmentPosition || null,
        chat_title: message.chatTitle || null,
        confirm_target_merge: message.confirmTargetMerge || false,
        file_name: message.fileName,
        file_type: message.fileType || "document",
        mime_type: message.mimeType || "application/octet-stream",
        total_bytes: message.totalBytes,
        total_chunks: message.totalChunks,
        sha256: message.sha256 || null,
        attachment_status: message.attachmentStatus || "saved-original"
      };

      const res = await fetchFn(`${backendUrl}/api/companion/media/session/start`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify(startPayload)
      });

      if (res.ok) {
        const data = await res.json();
        sendResponse({ success: true, data });
      } else {
        const errData = await res.json().catch(() => ({}));
        sendResponse({ success: false, error_code: `HTTP_${res.status}`, error: errData.detail || "Server error" });
      }
    } catch (e) {
      sendResponse({ success: false, error_code: "NETWORK_ERROR" });
    }
    return true;
  }

  // 2e. Chunked Media Session Chunk Bridge
  if (message.action === "bridge_media_session_chunk") {
    try {
      const isSecured = await ensureTrustedStorage(storageLocal);
      if (!isSecured) {
        sendResponse({ success: false, error_code: "STORAGE_SECURITY_ERROR", error: trustedStorageError || "Storage security error" });
        return true;
      }

      const { token, backendUrl } = await getStoredTokenAndUrl(storageLocal, storageSession);
      if (!token || !isAllowedLoopbackUrl(backendUrl)) {
        sendResponse({ success: false, error_code: "UNPAIRED", error: "Extension is not paired" });
        return true;
      }

      const chunkPayload = {
        session_id: message.sessionId,
        chunk_index: message.chunkIndex,
        chunk_base64: message.chunkBase64
      };

      const payloadStr = JSON.stringify(chunkPayload);
      if (calculateByteLength(payloadStr) > MAX_MEDIA_CHUNK_BYTES) {
        sendResponse({
          success: false,
          error_code: "PAYLOAD_TOO_LARGE",
          error: `Media chunk size exceeds limit (${MAX_MEDIA_CHUNK_BYTES} bytes)`
        });
        return true;
      }

      const res = await fetchFn(`${backendUrl}/api/companion/media/session/chunk`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: payloadStr
      });

      if (res.ok) {
        const data = await res.json();
        sendResponse({ success: true, data });
      } else {
        const errData = await res.json().catch(() => ({}));
        sendResponse({ success: false, error_code: `HTTP_${res.status}`, error: errData.detail || "Server error" });
      }
    } catch (e) {
      sendResponse({ success: false, error_code: "NETWORK_ERROR" });
    }
    return true;
  }

  // 2f. Chunked Media Session Finish Bridge
  if (message.action === "bridge_media_session_finish") {
    try {
      const isSecured = await ensureTrustedStorage(storageLocal);
      if (!isSecured) {
        sendResponse({ success: false, error_code: "STORAGE_SECURITY_ERROR", error: trustedStorageError || "Storage security error" });
        return true;
      }

      const { token, backendUrl } = await getStoredTokenAndUrl(storageLocal, storageSession);
      if (!token || !isAllowedLoopbackUrl(backendUrl)) {
        sendResponse({ success: false, error_code: "UNPAIRED", error: "Extension is not paired" });
        return true;
      }

      const res = await fetchFn(`${backendUrl}/api/companion/media/session/finish`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({ session_id: message.sessionId })
      });

      if (res.ok) {
        const data = await res.json();
        sendResponse({ success: true, data });
      } else {
        const errData = await res.json().catch(() => ({}));
        sendResponse({ success: false, error_code: `HTTP_${res.status}`, error: errData.detail || "Server error" });
      }
    } catch (e) {
      sendResponse({ success: false, error_code: "NETWORK_ERROR" });
    }
    return true;
  }

  // 2g. Download Capture Arming Bridge
  if (message.action === "bridge_arm_download_capture") {
    lastCompletedDownloadResult = null;
    const timeoutMs = message.timeoutMs || 10000;
    if (pendingDownload && pendingDownload.timer) {
      clearTimeout(pendingDownload.timer);
    }

    const armedTime = Date.now();
    let completeFn = null;
    const promise = new Promise((resolve) => {
      completeFn = (result) => {
        if (pendingDownload && pendingDownload.timer) {
          clearTimeout(pendingDownload.timer);
        }
        lastCompletedDownloadResult = result;
        pendingDownload = null;
        resolve(result);
      };
    });

    const timer = setTimeout(() => {
      if (completeFn) {
        completeFn({ success: false, error_code: "DOWNLOAD_TIMEOUT", error: "Download wait timed out" });
      }
    }, timeoutMs);

    pendingDownload = {
      armedTime,
      expectedFilename: message.expectedFilename || null,
      expectedType: message.expectedType || null,
      timer,
      promise,
      complete: completeFn,
      downloadId: null,
      concurrentConflict: false
    };

    if (injectedDeps.onDownloadArmed) {
      injectedDeps.onDownloadArmed(pendingDownload);
    }
    sendResponse({ success: true, status: "armed" });
    return true;
  }

  // 2h. Download Await Bridge
  if (message.action === "bridge_await_download") {
    if (lastCompletedDownloadResult) {
      const res = lastCompletedDownloadResult;
      lastCompletedDownloadResult = null;
      sendResponse(res);
      return true;
    }
    if (!pendingDownload) {
      sendResponse({ success: false, error_code: "NO_ARMED_DOWNLOAD", error: "No download currently armed" });
      return true;
    }
    pendingDownload.promise.then((result) => {
      lastCompletedDownloadResult = null;
      sendResponse(result);
    });
    return true;
  }

  // 2i. Download Media Handoff Bridge
  if (message.action === "bridge_media_download_handoff") {
    try {
      const isSecured = await ensureTrustedStorage(storageLocal);
      if (!isSecured) {
        sendResponse({ success: false, error_code: "STORAGE_SECURITY_ERROR", error: trustedStorageError || "Storage security error" });
        return true;
      }

      const { token, backendUrl } = await getStoredTokenAndUrl(storageLocal, storageSession);
      if (!token || !isAllowedLoopbackUrl(backendUrl)) {
        sendResponse({ success: false, error_code: "UNPAIRED", error: "Extension is not paired" });
        return true;
      }

      const payload = {
        download_path: message.downloadPath,
        conversation_id: message.conversationId || null,
        message_id: message.messageId || null,
        platform_msg_id: message.platformMsgId || null,
        message_key: message.messageKey || null,
        session_id: message.sessionId || null,
        attachment_position: message.attachmentPosition || null,
        chat_title: message.chatTitle || null,
        confirm_target_merge: Boolean(message.confirmTargetMerge),
        file_name: message.fileName,
        file_type: message.fileType || "document",
        mime_type: message.mimeType || "application/octet-stream",
        sha256: message.sha256 || null,
        attachment_status: message.attachmentStatus || "saved-original"
      };

      const res = await fetchFn(`${backendUrl}/api/companion/media/handoff`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        const data = await res.json();
        sendResponse({ success: true, data });
      } else {
        const errData = await res.json().catch(() => ({}));
        sendResponse({
          success: false,
          error_code: `HTTP_${res.status}`,
          status: res.status,
          error: errData.detail || "Download handoff failed"
        });
      }
    } catch (e) {
      sendResponse({ success: false, error_code: "NETWORK_ERROR", error: "Could not connect to loopback OWI" });
    }
    return true;
  }

  // 3. Capture State Bridge (content script progress without direct storage access)
  if (message.action === "bridge_set_capture_state") {
    try {
      inMemoryCaptureState = message.state;
      if (storageLocal && typeof storageLocal.set === "function") {
        await storageLocal.set({ owi_capture_state: message.state });
      }
      sendResponse({ success: true });
    } catch (e) {
      sendResponse({ success: false, error_code: "STATE_SAVE_FAILED" });
    }
    return true;
  }

  if (message.action === "bridge_get_capture_state") {
    try {
      let state = inMemoryCaptureState;
      if (!state && storageLocal && typeof storageLocal.get === "function") {
        const stored = await storageLocal.get(["owi_capture_state"]);
        state = stored?.owi_capture_state;
      }
      sendResponse({ success: true, state: state || { status: "idle" } });
    } catch (e) {
      sendResponse({ success: false, state: { status: "idle" } });
    }
    return true;
  }

  // 4. Local Diagnostics Logging Bridge (for content script before/during pairing)
  if (message.action === "bridge_log_diagnostic") {
    try {
      if (storageLocal && typeof storageLocal.get === "function") {
        const entry = message.entry;
        const data = await storageLocal.get(["owi_diagnostic_logs"]);
        const logs = Array.isArray(data?.owi_diagnostic_logs) ? data.owi_diagnostic_logs : [];
        logs.push(entry);
        const trimmed = logs.length > 150 ? logs.slice(-150) : logs;
        await storageLocal.set({ owi_diagnostic_logs: trimmed });
      }
      sendResponse({ success: true });
    } catch (e) {
      sendResponse({ success: false });
    }
    return true;
  }

  if (message.action === "bridge_get_diagnostics") {
    try {
      const data = storageLocal && typeof storageLocal.get === "function" ? await storageLocal.get(["owi_diagnostic_logs"]) : {};
      sendResponse({ success: true, logs: Array.isArray(data?.owi_diagnostic_logs) ? data.owi_diagnostic_logs : [] });
    } catch (e) {
      sendResponse({ success: false, logs: [] });
    }
    return true;
  }

  if (message.action === "bridge_clear_diagnostics") {
    try {
      if (storageLocal && typeof storageLocal.remove === "function") {
        await storageLocal.remove(["owi_diagnostic_logs"]);
      }
      sendResponse({ success: true });
    } catch (e) {
      sendResponse({ success: false });
    }
    return true;
  }

  // 5. Pairing Status Query
  if (message.action === "get_pairing_status") {
    const isSecured = await ensureTrustedStorage(storageLocal);
    if (!isSecured) {
      sendResponse({ success: false, error_code: "STORAGE_SECURITY_ERROR", error: trustedStorageError || "Storage security error" });
      return true;
    }
    const { token, backendUrl } = await getStoredTokenAndUrl(storageLocal, storageSession);
    sendResponse({
      success: true,
      paired: Boolean(token),
      backendUrl: backendUrl || "http://127.0.0.1:8765"
    });
    return true;
  }

  // 6. Unpair / Revoke
  if (message.action === "unpair") {
    if (storageLocal && typeof storageLocal.remove === "function") {
      await storageLocal.remove(["owi_token"]);
    }
    if (storageSession && typeof storageSession.remove === "function") {
      await storageSession.remove(["owi_token"]);
    }
    sendResponse({ success: true });
    return true;
  }

  // 7. Status Ping
  if (message.action === "ping") {
    sendResponse({ success: true, status: "alive" });
    return true;
  }
}

if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.onMessage) {
  chrome.runtime.onInstalled.addListener(() => {
    console.log("[OWI Companion] Extension installed/updated.");
  });

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    handleRuntimeMessage(message, sender, sendResponse);
    return true;
  });
}

// Export for node test runner
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    MAX_INGEST_PAYLOAD_BYTES,
    MAX_DIAGNOSTICS_COUNT,
    MAX_DIAGNOSTICS_PAYLOAD_BYTES,
    MAX_MEDIA_DIRECT_BYTES,
    MAX_MEDIA_CHUNK_BYTES,
    isAllowedLoopbackUrl,
    isValidSender,
    calculateByteLength,
    ensureTrustedStorage,
    getStoredTokenAndUrl,
    handleRuntimeMessage,
    handleBridgeMessage: handleRuntimeMessage,
    setupDownloadsListener,
    getPendingDownload: () => pendingDownload
  };
}
