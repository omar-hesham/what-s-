/**
 * OWI Companion - Diagnostic Logger
 * Structured, bounded diagnostic logger ensuring privacy:
 * - Strictly enforces allowlisted stages, codes, and static reason details
 * - Completely rejects arbitrary strings, chat titles, message text, and tokens
 * - Stores rolling buffer of recent events in chrome.storage.local
 * - Dispatches backend flushes through the background service worker bridge
 */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.OWIDiagnosticLogger = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  const MAX_LOG_ENTRIES = 150;
  const STORAGE_KEY = "owi_diagnostic_logs";

  const ALLOWED_STAGES = [
    "init", "pairing", "scroll_up", "scroll_down", "ingest_chunk", "cancel", "summary", "general"
  ];

  const ALLOWED_CODES = [
    "START", "STEP", "SUCCESS", "PARTIAL", "CANCELLED",
    "BOUND_REACHED", "TOP_REACHED", "BOTTOM_REACHED",
    "CHUNK_INGESTED", "CHUNK_POST_SUCCESS", "CHUNK_POST_FAILED",
    "ERR_NETWORK", "ERR_AUTH", "ERR_PAYLOAD", "ERR_SELECTOR",
    "ERR_TIMEOUT", "ERR_STALL", "ERR_PARSE", "UNPAIRED", "INFO"
  ];

  const ALLOWED_STATIC_DETAILS = [
    "history_exhausted_before_from_bound",
    "history_exhausted_before_to_bound",
    "scroll_attempts_exhausted",
    "traversal_stalled",
    "cancelled_by_user",
    "chat_navigation_detected",
    "first_visible_anchor_not_found",
    "zero_messages_captured",
    "unparseable_timestamp_present",
    "unverified_timestamps_present",
    "chunk_ingest_failed",
    "payload_too_large",
    "backend_unreachable",
    "older_messages_button_unexhausted",
    "clicked_older_messages_button",
    "auth_rejected",
    "ok"
  ];

  function sanitizeStage(stage) {
    if (!stage || typeof stage !== "string") return "general";
    const clean = stage.trim().toLowerCase();
    return ALLOWED_STAGES.includes(clean) ? clean : "general";
  }

  function sanitizeCode(code) {
    if (!code || typeof code !== "string") return "INFO";
    const clean = code.trim().toUpperCase();
    return ALLOWED_CODES.includes(clean) ? clean : "INFO";
  }

  function sanitizeDetail(detail) {
    if (!detail || typeof detail !== "string") return null;
    const clean = detail.trim().toLowerCase();
    return ALLOWED_STATIC_DETAILS.includes(clean) ? clean : null;
  }

  function createLogEntry(stage, code, count = 0, details = null) {
    return {
      timestamp: new Date().toISOString(),
      stage: sanitizeStage(stage),
      code: sanitizeCode(code),
      count: typeof count === "number" && count >= 0 ? count : 0,
      details: sanitizeDetail(details)
    };
  }

  async function getStoredLogs() {
    if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
      try {
        const data = await chrome.storage.local.get([STORAGE_KEY]);
        return Array.isArray(data[STORAGE_KEY]) ? data[STORAGE_KEY] : [];
      } catch (err) {
        // Direct storage.local access restricted in content scripts
      }
    }
    if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.sendMessage) {
      try {
        return await new Promise((resolve) => {
          chrome.runtime.sendMessage({ action: "bridge_get_diagnostics" }, (res) => {
            if (chrome.runtime.lastError || !res || !Array.isArray(res.logs)) {
              resolve([]);
            } else {
              resolve(res.logs);
            }
          });
        });
      } catch (e) {}
    }
    return [];
  }

  async function appendLog(entry) {
    const sanitized = {
      timestamp: entry.timestamp || new Date().toISOString(),
      stage: sanitizeStage(entry.stage),
      code: sanitizeCode(entry.code),
      count: typeof entry.count === "number" && entry.count >= 0 ? entry.count : 0,
      details: sanitizeDetail(entry.details)
    };

    let savedDirectly = false;
    if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
      try {
        const data = await chrome.storage.local.get([STORAGE_KEY]);
        const logs = Array.isArray(data[STORAGE_KEY]) ? data[STORAGE_KEY] : [];
        logs.push(sanitized);
        const trimmed = logs.length > MAX_LOG_ENTRIES ? logs.slice(-MAX_LOG_ENTRIES) : logs;
        await chrome.storage.local.set({ [STORAGE_KEY]: trimmed });
        savedDirectly = true;
      } catch (err) {
        // Direct access denied in content script
        savedDirectly = false;
      }
    }

    if (!savedDirectly && typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.sendMessage) {
      try {
        await new Promise((resolve) => {
          chrome.runtime.sendMessage({ action: "bridge_log_diagnostic", entry: sanitized }, () => resolve());
        });
      } catch (err) {}
    }
    return sanitized;
  }

  async function log(stage, code, count = 0, details = null) {
    const entry = createLogEntry(stage, code, count, details);
    return await appendLog(entry);
  }

  async function clearLogs() {
    let clearedDirectly = false;
    if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
      try {
        await chrome.storage.local.remove([STORAGE_KEY]);
        clearedDirectly = true;
      } catch (err) {}
    }
    if (!clearedDirectly && typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.sendMessage) {
      try {
        await new Promise((resolve) => {
          chrome.runtime.sendMessage({ action: "bridge_clear_diagnostics" }, () => resolve());
        });
      } catch (err) {}
    }
  }

  async function flushToBackend(bridgeSender = null) {
    const logs = await getStoredLogs();
    if (!logs.length) return true;

    const payload = { action: "bridge_diagnostics", entries: logs.slice(-50) };

    if (typeof bridgeSender === "function") {
      const res = await bridgeSender(payload);
      return Boolean(res && res.success);
    }

    if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.sendMessage) {
      return new Promise((resolve) => {
        chrome.runtime.sendMessage(payload, (res) => {
          if (chrome.runtime.lastError || !res || !res.success) {
            resolve(false);
          } else {
            resolve(true);
          }
        });
      });
    }
    return false;
  }

  return {
    ALLOWED_STAGES,
    ALLOWED_CODES,
    ALLOWED_STATIC_DETAILS,
    sanitizeStage,
    sanitizeCode,
    sanitizeDetail,
    createLogEntry,
    getStoredLogs,
    appendLog,
    log,
    clearLogs,
    flushToBackend
  };
});
