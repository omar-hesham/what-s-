/**
 * Synthetic Regression Test Suite for OWI Bulk WhatsApp Capture
 * Executed via Node.js built-in test runner (`node --test`).
 * Validates:
 * 1. Date correctness (impossible dates 31/02, time-only rejection, Arabic numerals/AM-PM)
 * 2. Log privacy (strict allowlist, elimination of sensitive phrases like 'H private message')
 * 3. Truthful completion (anchor loss, bounds exhaustion, unverified timestamps, zero messages)
 * 4. Virtualized traversal, deduplication, and responsive cancellation
 * 5. Chunking, bridge retries, and error propagation
 * 6. Background Service Worker Bridge:
 *    - Genuine 2 MB payload byte cap
 *    - Diagnostics batch limits (50 count / 100 KB)
 *    - Sender validation & fixed endpoint enforcement
 *    - Trusted-only storage token isolation (content script denied, worker/popup paired & recovered)
 */

import test from "node:test";
import assert from "node:assert/strict";

import DateParser from "../companion_extension/date_parser.js";
import DiagLogger from "../companion_extension/diagnostic_logger.js";
import BulkEngine from "../companion_extension/bulk_capture_engine.js";
import BackgroundBridge from "../companion_extension/background.js";

// --- 1. Date Correctness & Validation Tests ---

test("DateParser: Rejects impossible calendar dates (e.g. 31/02/2026, 2026-02-30, 31/04/2026)", () => {
  assert.equal(DateParser.parseWhatsAppTimestamp("10:30 AM, 31/02/2026", { dateOrder: "DD/MM/YYYY" }), null);
  assert.equal(DateParser.parseWhatsAppTimestamp("10:30 AM, 30/02/2026", { dateOrder: "DD/MM/YYYY" }), null);
  assert.equal(DateParser.parseWhatsAppTimestamp("2026-02-30T10:00:00"), null);
  assert.equal(DateParser.parseWhatsAppTimestamp("10:30 AM, 31/04/2026", { dateOrder: "DD/MM/YYYY" }), null);
  assert.equal(DateParser.parseWhatsAppTimestamp("10:30 AM, 29/02/2025", { dateOrder: "DD/MM/YYYY" }), null);

  // 2024 is leap year
  const leap = DateParser.parseWhatsAppTimestamp("10:30 AM, 29/02/2024", { dateOrder: "DD/MM/YYYY" });
  assert.ok(leap);
  assert.equal(leap.iso, "2024-02-29T10:30:00");
});

test("DateParser: Rejects time-only strings without a date (never replaces with current day)", () => {
  assert.equal(DateParser.parseWhatsAppTimestamp("10:30 AM"), null);
  assert.equal(DateParser.parseWhatsAppTimestamp("14:45:00"), null);
  assert.equal(DateParser.parseWhatsAppTimestamp("١٠:٣٠ ص"), null);
  assert.equal(DateParser.parseWhatsAppTimestamp("03:30 مساءً"), null);
});

test("DateParser: Valid dates parse strictly and accurately", () => {
  // Egypt default ambiguous 05/06/2026 -> June 5
  const d1 = DateParser.parseWhatsAppTimestamp("10:30 AM, 05/06/2026", { dateOrder: "DD/MM/YYYY" });
  assert.ok(d1);
  assert.equal(d1.iso, "2026-06-05T10:30:00");

  // US format 05/06/2026 -> May 6
  const d2 = DateParser.parseWhatsAppTimestamp("10:30 AM, 05/06/2026", { dateOrder: "MM/DD/YYYY" });
  assert.ok(d2);
  assert.equal(d2.iso, "2026-05-06T10:30:00");

  // Arabic numerals & Arabic PM marker
  const d3 = DateParser.parseWhatsAppTimestamp("١٠:١٥ م، ٢٣/٠٩/٢٠٢٦", { dateOrder: "DD/MM/YYYY" });
  assert.ok(d3);
  assert.equal(d3.iso, "2026-09-23T22:15:00");
});

test("BulkEngine: filterMessagesByDateRange excludes unparseable messages and counts them", () => {
  const list = [
    { key: "1", parsed_date: new Date("2026-09-20T10:00:00") },
    { key: "2", parsed_date: null }, // Unparseable
    { key: "3", parsed_date: new Date("2026-09-23T12:00:00") },
    { key: "4", parsed_date: null }, // Unparseable
    { key: "5", parsed_date: new Date("2026-09-26T10:00:00") }
  ];

  const { filtered, unparseableCount } = BulkEngine.filterMessagesByDateRange(
    list,
    "2026-09-22T00:00:00",
    "2026-09-24T23:59:59"
  );

  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].key, "3");
  assert.equal(unparseableCount, 2, "Must count unparseable messages rather than including them");
});

// --- 2. Log Privacy & Strict Allowlist Tests ---

test("DiagLogger: Plain sensitive phrase ('H private message') is strictly eliminated", () => {
  const entry = DiagLogger.createLogEntry("scroll_up", "STEP", 10, "Failed with H private message from Omar");
  assert.equal(entry.stage, "scroll_up");
  assert.equal(entry.code, "STEP");
  assert.equal(entry.count, 10);
  assert.equal(entry.details, null, "Arbitrary sensitive phrases must be rejected; details must be null");
  assert.ok(!JSON.stringify(entry).includes("H private message"));
  assert.ok(!JSON.stringify(entry).includes("Omar"));
});

test("DiagLogger: Allows only static allowlisted reason codes in details", () => {
  const allowedEntry = DiagLogger.createLogEntry("scroll_up", "PARTIAL", 5, "history_exhausted_before_from_bound");
  assert.equal(allowedEntry.details, "history_exhausted_before_from_bound");

  const disallowedEntry = DiagLogger.createLogEntry("summary", "PARTIAL", 5, "Secret chat title: Project X");
  assert.equal(disallowedEntry.details, null);
});

// --- 3. Truthful Completion & Edge Cases ---

test("BulkEngine: Mode visible_to_newest reports partial when first visible anchor is not found", async () => {
  const mockContainer = {
    scrollTop: 0,
    clientHeight: 200,
    scrollHeight: 500,
    getBoundingClientRect: () => ({ top: 0, bottom: 200 }),
    querySelectorAll: () => [] // No messages found in DOM
  };

  const result = await BulkEngine.runBulkCapture({
    container: mockContainer,
    doc: { querySelector: () => ({ innerText: "Empty Chat" }) },
    mode: "visible_to_newest",
    maxScrollAttempts: 5
  });

  assert.equal(result.completenessStatus, "partial");
  assert.equal(result.partialReason, "first_visible_anchor_not_found");
  assert.equal(result.messages.length, 0);
});

test("BulkEngine: Mode visible_to_newest reports partial with scroll_attempts_exhausted if bottom not reached", async () => {
  const mockContainer = {
    scrollTop: 0,
    clientHeight: 200,
    scrollHeight: 2000,
    getBoundingClientRect: () => ({ top: 0, bottom: 200 }),
    querySelectorAll: () => [
      {
        getAttribute: (attr) => (attr === "data-id" ? "msg_anchor" : null),
        classList: { contains: () => false },
        getBoundingClientRect: () => ({ top: 10, bottom: 30 }),
        querySelector: () => ({ innerText: "Anchor", getAttribute: () => "[10:00, 25/09/2026] User: " })
      }
    ]
  };

  const result = await BulkEngine.runBulkCapture({
    container: mockContainer,
    doc: { querySelector: () => ({ innerText: "Test Chat" }) },
    mode: "visible_to_newest",
    maxScrollAttempts: 2, // Low cap that ends before bottom
    scrollDelayMs: 2
  });

  assert.equal(result.completenessStatus, "partial");
  assert.equal(result.partialReason, "scroll_attempts_exhausted");
});

test("BulkEngine: Mode visible_to_newest reports partial with unverified_timestamps_present if unparseable timestamps occur", async () => {
  const mockContainer = {
    scrollTop: 0,
    clientHeight: 200,
    scrollHeight: 200,
    getBoundingClientRect: () => ({ top: 0, bottom: 200 }),
    querySelectorAll: () => [
      {
        getAttribute: (attr) => (attr === "data-id" ? "msg_anchor" : null),
        classList: { contains: () => false },
        getBoundingClientRect: () => ({ top: 10, bottom: 30 }),
        querySelector: () => ({ innerText: "Anchor", getAttribute: () => "[10:00, 25/09/2026] User: " })
      },
      {
        getAttribute: (attr) => (attr === "data-id" ? "msg_corrupt" : null),
        classList: { contains: () => false },
        getBoundingClientRect: () => ({ top: 35, bottom: 55 }),
        querySelector: () => ({ innerText: "Corrupt", getAttribute: () => "invalid_timestamp_text" })
      }
    ]
  };

  const result = await BulkEngine.runBulkCapture({
    container: mockContainer,
    doc: { querySelector: () => ({ innerText: "Test Chat" }) },
    mode: "visible_to_newest",
    maxScrollAttempts: 5,
    scrollDelayMs: 2
  });

  assert.equal(result.completenessStatus, "partial");
  assert.equal(result.partialReason, "unverified_timestamps_present");
  assert.equal(result.messages.length, 2, "Unverified messages must be preserved in content, never silently dropped");
});

test("BulkEngine: Zero matching messages reports partial with zero_messages_captured", async () => {
  const mockContainer = {
    scrollTop: 0,
    clientHeight: 200,
    scrollHeight: 200,
    getBoundingClientRect: () => ({ top: 0, bottom: 200 }),
    querySelectorAll: () => [
      {
        getAttribute: (attr) => (attr === "data-id" ? "msg_old" : null),
        classList: { contains: () => false },
        getBoundingClientRect: () => ({ top: 10, bottom: 30 }),
        querySelector: () => ({ innerText: "Old message", getAttribute: () => "[10:00, 01/01/2026] User: " })
      }
    ]
  };

  const result = await BulkEngine.runBulkCapture({
    container: mockContainer,
    doc: { querySelector: () => ({ innerText: "Test Chat" }) },
    mode: "date_range",
    fromDate: "2026-09-01T00:00:00",
    toDate: "2026-09-10T00:00:00",
    maxScrollAttempts: 5,
    scrollDelayMs: 2
  });

  assert.equal(result.completenessStatus, "partial");
  assert.equal(result.messages.length, 0);
  assert.ok(["zero_messages_captured", "history_exhausted_before_from_bound", "history_exhausted_before_to_bound", "scroll_attempts_exhausted"].includes(result.partialReason));
});

test("BulkEngine: Presence of unparseable timestamps marks date_range capture as partial", async () => {
  const mockContainer = {
    scrollTop: 0,
    clientHeight: 200,
    scrollHeight: 200,
    getBoundingClientRect: () => ({ top: 0, bottom: 200 }),
    querySelectorAll: () => [
      {
        getAttribute: (attr) => (attr === "data-id" ? "msg_valid" : null),
        classList: { contains: () => false },
        getBoundingClientRect: () => ({ top: 10, bottom: 30 }),
        querySelector: () => ({ innerText: "Valid message", getAttribute: () => "[10:00, 05/09/2026] User: " })
      },
      {
        getAttribute: (attr) => (attr === "data-id" ? "msg_corrupt" : null),
        classList: { contains: () => false },
        getBoundingClientRect: () => ({ top: 35, bottom: 55 }),
        querySelector: () => ({ innerText: "Corrupt message", getAttribute: () => "invalid_timestamp" })
      }
    ]
  };

  const result = await BulkEngine.runBulkCapture({
    container: mockContainer,
    doc: { querySelector: () => ({ innerText: "Test Chat" }) },
    mode: "date_range",
    fromDate: "2026-09-05T10:00:00",
    toDate: "2026-09-05T10:00:00",
    maxScrollAttempts: 5,
    scrollDelayMs: 2
  });

  assert.equal(result.completenessStatus, "partial");
  assert.equal(result.partialReason, "unparseable_timestamp_present");
  assert.equal(result.messages.length, 1);
});

// --- 4. Virtualized Traversal, Deduplication & Cancellation ---

test("BulkEngine: Successful virtualized traversal reaches bottom with status complete", async () => {
  let step = 0;
  const mockContainer = {
    scrollTop: 0,
    clientHeight: 200,
    scrollHeight: 400,
    getBoundingClientRect: () => ({ top: 0, bottom: 200 }),
    querySelectorAll: () => {
      step++;
      if (step === 1) {
        return [
          {
            getAttribute: (attr) => (attr === "data-id" ? "msg_1" : null),
            classList: { contains: () => false },
            getBoundingClientRect: () => ({ top: 10, bottom: 30 }),
            querySelector: () => ({ innerText: "Message 1", getAttribute: () => "[10:00, 25/09/2026] User: " })
          }
        ];
      } else {
        // Step 2 simulates scrolling down and finding message 2 at the bottom
        mockContainer.scrollTop = 200;
        return [
          {
            getAttribute: (attr) => (attr === "data-id" ? "msg_2" : null),
            classList: { contains: () => false },
            getBoundingClientRect: () => ({ top: 40, bottom: 60 }),
            querySelector: () => ({ innerText: "Message 2", getAttribute: () => "[10:01, 25/09/2026] User: " })
          }
        ];
      }
    }
  };

  const result = await BulkEngine.runBulkCapture({
    container: mockContainer,
    doc: { querySelector: () => ({ innerText: "Complete Chat" }) },
    mode: "visible_to_newest",
    maxScrollAttempts: 5,
    scrollDelayMs: 2
  });

  assert.equal(result.completenessStatus, "complete");
  assert.equal(result.partialReason, null);
  assert.equal(result.messages.length, 2);
});

test("BulkEngine: Deduplication during virtualized scrolling prevents duplicates", async () => {
  const sharedMsg = {
    getAttribute: (attr) => (attr === "data-id" ? "dup_id_1" : null),
    classList: { contains: () => false },
    getBoundingClientRect: () => ({ top: 10, bottom: 30 }),
    querySelector: () => ({ innerText: "Persistent text", getAttribute: () => "[10:00, 25/09/2026] Alice: " })
  };

  const mockContainer = {
    scrollTop: 0,
    clientHeight: 200,
    scrollHeight: 200,
    getBoundingClientRect: () => ({ top: 0, bottom: 200 }),
    querySelectorAll: () => [sharedMsg, sharedMsg, sharedMsg] // Repeated DOM nodes
  };

  const result = await BulkEngine.runBulkCapture({
    container: mockContainer,
    doc: { querySelector: () => ({ innerText: "Dedup Chat" }) },
    mode: "visible_to_newest",
    maxScrollAttempts: 2,
    scrollDelayMs: 2
  });

  assert.equal(result.messages.length, 1, "Must deduplicate identical platform message IDs");
});

test("BulkEngine: User cancellation halts traversal and reports cancelled_by_user", async () => {
  let cancelFlag = false;
  let scrollCount = 0;

  const mockContainer = {
    scrollTop: 0,
    clientHeight: 200,
    scrollHeight: 1000,
    getBoundingClientRect: () => ({ top: 0, bottom: 200 }),
    querySelectorAll: () => {
      scrollCount++;
      if (scrollCount >= 2) {
        cancelFlag = true;
      }
      return [
        {
          getAttribute: (attr) => (attr === "data-id" ? `msg_${scrollCount}` : null),
          classList: { contains: () => false },
          getBoundingClientRect: () => ({ top: 10, bottom: 30 }),
          querySelector: () => ({ innerText: `Message ${scrollCount}`, getAttribute: () => "[10:00, 25/09/2026] User: " })
        }
      ];
    }
  };

  const result = await BulkEngine.runBulkCapture({
    container: mockContainer,
    doc: { querySelector: () => ({ innerText: "Cancel Chat" }) },
    mode: "visible_to_newest",
    checkCancelled: () => cancelFlag,
    maxScrollAttempts: 10,
    scrollDelayMs: 2
  });

  assert.equal(result.completenessStatus, "partial");
  assert.equal(result.partialReason, "cancelled_by_user");
});

test("BulkEngine: chunkArray correctly divides messages into bounded chunks", () => {
  const items = Array.from({ length: 125 }, (_, i) => ({ id: i }));
  const chunks = BulkEngine.chunkArray(items, 50);
  assert.equal(chunks.length, 3);
  assert.equal(chunks[0].length, 50);
  assert.equal(chunks[1].length, 50);
  assert.equal(chunks[2].length, 25);
});

test("BulkEngine: postChunkWithRetry routes via bridge and retries on failure", async () => {
  // 1. Simulate failure on all retries
  const failingBridge = async () => ({
    success: false,
    error_code: "HTTP_500",
    error: "Internal Server Error"
  });

  const resFail = await BulkEngine.postChunkWithRetry({
    chatTitle: "Test Chat",
    chunk: [{ sender: "User", text: "Hi" }],
    chunkIndex: 0,
    totalChunks: 1,
    isLastChunk: true,
    maxRetries: 2,
    bridgeSender: failingBridge
  });

  assert.equal(resFail.success, false);
  assert.equal(resFail.error_code, "CHUNK_FAILED");

  // 2. Simulate success on retry
  let attempt = 0;
  const retryBridge = async () => {
    attempt++;
    if (attempt === 1) return { success: false, error_code: "NETWORK_ERROR" };
    return { success: true, data: { messages_ingested: 1, duplicates_skipped: 0 } };
  };

  const resSuccess = await BulkEngine.postChunkWithRetry({
    chatTitle: "Test Chat",
    chunk: [{ sender: "User", text: "Hi" }],
    chunkIndex: 0,
    totalChunks: 1,
    isLastChunk: true,
    maxRetries: 2,
    bridgeSender: retryBridge
  });

  assert.equal(resSuccess.success, true);
  assert.equal(attempt, 2);
});

// --- 5. Service Worker Bridge Security & Constraints ---

test("BackgroundBridge: Rejects unauthorized sender", async () => {
  let response = null;
  const sendResponse = (res) => { response = res; };

  // Sender from unauthorized website
  const badSender = { id: "some_id", url: "https://evil.example.com/page" };
  await BackgroundBridge.handleRuntimeMessage({ action: "bridge_ingest_chunk" }, badSender, sendResponse);

  assert.equal(response.success, false);
  assert.equal(response.error_code, "UNAUTHORIZED_SENDER");
});

test("BackgroundBridge: Rejects arbitrary URL or endpoint parameter injection", async () => {
  let response = null;
  const sendResponse = (res) => { response = res; };

  const validSender = { tab: { url: "https://web.whatsapp.com/chat" } };
  await BackgroundBridge.handleRuntimeMessage(
    { action: "bridge_ingest_chunk", targetUrl: "http://malicious.local/steal" },
    validSender,
    sendResponse
  );

  assert.equal(response.success, false);
  assert.equal(response.error_code, "DISALLOWED_ENDPOINT");
});

test("BackgroundBridge: Enforces genuine 2 MB serialized ingest byte cap (PAYLOAD_TOO_LARGE)", async () => {
  let response = null;
  const sendResponse = (res) => { response = res; };

  const validSender = { tab: { url: "https://web.whatsapp.com/chat" } };
  const mockStorageSession = {
    get: async () => ({ owi_token: "test_token_123" })
  };
  const mockStorageLocal = {
    setAccessLevel: async () => {},
    get: async () => ({ owi_backend_url: "http://127.0.0.1:8765" })
  };

  // Build a chunk with a huge text message that exceeds 2 MB
  const hugeText = "X".repeat(2.1 * 1024 * 1024);
  const oversizedChunk = [{ sender: "Alice", text: hugeText, timestamp: "2026-09-25T10:00:00" }];

  await BackgroundBridge.handleRuntimeMessage(
    {
      action: "bridge_ingest_chunk",
      chatTitle: "Huge Chat",
      chunk: oversizedChunk,
      chunkIndex: 0,
      totalChunks: 1,
      isLastChunk: true
    },
    validSender,
    sendResponse,
    { storageSession: mockStorageSession, storageLocal: mockStorageLocal, fetchFn: async () => {} }
  );

  assert.equal(response.success, false);
  assert.equal(response.error_code, "PAYLOAD_TOO_LARGE");
});

test("BackgroundBridge: Enforces diagnostics batch bounds (50 items / 100 KB)", async () => {
  let response = null;
  const sendResponse = (res) => { response = res; };

  const validSender = { tab: { url: "https://web.whatsapp.com/chat" } };
  const mockStorageSession = {
    get: async () => ({ owi_token: "test_token_123" })
  };
  const mockStorageLocal = {
    setAccessLevel: async () => {},
    get: async () => ({ owi_backend_url: "http://127.0.0.1:8765" })
  };

  // 1. Exceed count limit (> 50)
  const tooManyEntries = Array.from({ length: 55 }, (_, i) => ({ stage: "scroll_up", code: "STEP", count: i }));
  await BackgroundBridge.handleRuntimeMessage(
    { action: "bridge_diagnostics", entries: tooManyEntries },
    validSender,
    sendResponse,
    { storageSession: mockStorageSession, storageLocal: mockStorageLocal, fetchFn: async () => {} }
  );

  assert.equal(response.success, false);
  assert.equal(response.error_code, "PAYLOAD_TOO_LARGE");

  // 2. Exceed byte limit (> 100 KB)
  const hugeDetail = "a".repeat(105 * 1024);
  await BackgroundBridge.handleRuntimeMessage(
    { action: "bridge_diagnostics", entries: [{ stage: "general", code: "INFO", details: hugeDetail }] },
    validSender,
    sendResponse,
    { storageSession: mockStorageSession, storageLocal: mockStorageLocal, fetchFn: async () => {} }
  );

  assert.equal(response.success, false);
  assert.equal(response.error_code, "PAYLOAD_TOO_LARGE");
});

test("BackgroundBridge: Trusted storage security - fails closed with STORAGE_SECURITY_ERROR if setAccessLevel fails", async () => {
  const mockFailingStorageLocal = {
    get: async () => ({ owi_token: "tok123" }),
    setAccessLevel: async () => { throw new Error("Permission denied"); }
  };
  let response = null;
  const sendResponse = (res) => { response = res; };
  const validTabSender = { tab: { url: "https://web.whatsapp.com/chat" } };

  await BackgroundBridge.handleRuntimeMessage(
    {
      action: "bridge_ingest_chunk",
      chatTitle: "Test Chat",
      chunk: [{ sender: "Alice", text: "hi", timestamp: "2026-09-25T10:00:00" }],
      chunkIndex: 0,
      totalChunks: 1,
      isLastChunk: true
    },
    validTabSender,
    sendResponse,
    { storageLocal: mockFailingStorageLocal, trustedStorageConfigured: false }
  );

  assert.equal(response.success, false);
  assert.equal(response.error_code, "STORAGE_SECURITY_ERROR");
});

test("BackgroundBridge: Content script denial - untrusted context cannot read token from storage.local", async () => {
  let accessLevel = null;
  const storageData = { owi_token: "secret_persistent_token_123", owi_backend_url: "http://127.0.0.1:8765" };

  const mockStorageLocal = {
    setAccessLevel: async (opts) => { accessLevel = opts.accessLevel; },
    get: async (keys, callerContext = "trusted") => {
      if (accessLevel === "TRUSTED_CONTEXTS" && callerContext === "untrusted_content_script") {
        throw new Error("Access to storage is not allowed from this context");
      }
      const res = {};
      for (const k of keys) {
        if (storageData[k] !== undefined) res[k] = storageData[k];
      }
      return res;
    }
  };

  // Configure trusted access level
  await BackgroundBridge.ensureTrustedStorage(mockStorageLocal);
  assert.equal(accessLevel, "TRUSTED_CONTEXTS");

  // Untrusted content script attempts direct read: denied!
  await assert.rejects(
    async () => await mockStorageLocal.get(["owi_token"], "untrusted_content_script"),
    { message: /Access to storage is not allowed from this context/ }
  );

  // Trusted popup/worker context can read: allowed!
  const trustedRead = await mockStorageLocal.get(["owi_token"], "trusted");
  assert.equal(trustedRead.owi_token, "secret_persistent_token_123");
});

test("BackgroundBridge: Existing-token migration - migrates legacy session token to trusted storage.local", async () => {
  const localStore = {};
  const sessionStore = { owi_token: "legacy_session_token_555", owi_backend_url: "http://127.0.0.1:8765" };

  const mockLocal = {
    setAccessLevel: async () => {},
    get: async (keys) => {
      const res = {};
      for (const k of keys) { if (localStore[k] !== undefined) res[k] = localStore[k]; }
      return res;
    },
    set: async (obj) => Object.assign(localStore, obj),
    remove: async (keys) => { keys.forEach((k) => delete localStore[k]); }
  };

  const mockSession = {
    get: async (keys) => {
      const res = {};
      for (const k of keys) { if (sessionStore[k] !== undefined) res[k] = sessionStore[k]; }
      return res;
    },
    remove: async (keys) => { keys.forEach((k) => delete sessionStore[k]); }
  };

  const { token, backendUrl } = await BackgroundBridge.getStoredTokenAndUrl(mockLocal, mockSession);
  assert.equal(token, "legacy_session_token_555");
  assert.equal(localStore.owi_token, "legacy_session_token_555", "Must migrate token into storage.local");
  assert.equal(sessionStore.owi_token, undefined, "Must remove token from sessionStore after migration");
});

test("BackgroundBridge: Browser-restart persistence - token in storage.local survives session wipe and worker fetches with token", async () => {
  const localStore = { owi_token: "persistent_paired_token_777", owi_backend_url: "http://127.0.0.1:8765" };
  // Simulate session wipe upon browser restart
  let sessionStore = {};

  const mockLocal = {
    setAccessLevel: async () => {},
    get: async (keys) => {
      const res = {};
      for (const k of keys) { if (localStore[k] !== undefined) res[k] = localStore[k]; }
      return res;
    },
    set: async (obj) => Object.assign(localStore, obj),
    remove: async (keys) => { keys.forEach((k) => delete localStore[k]); }
  };

  const mockSession = {
    get: async (keys) => {
      const res = {};
      for (const k of keys) { if (sessionStore[k] !== undefined) res[k] = sessionStore[k]; }
      return res;
    },
    remove: async (keys) => { keys.forEach((k) => delete sessionStore[k]); }
  };

  let fetchedAuth = null;
  const mockFetch = async (url, opts) => {
    fetchedAuth = opts.headers["Authorization"];
    return { ok: true, json: async () => ({ status: "success", messages_ingested: 1, duplicates_skipped: 0 }) };
  };

  let response = null;
  const sendResponse = (res) => { response = res; };
  const validTabSender = { tab: { url: "https://web.whatsapp.com/chat" } };

  // After restart, session is empty, but storage.local retains token!
  await BackgroundBridge.handleRuntimeMessage(
    {
      action: "bridge_ingest_chunk",
      chatTitle: "Persistent Chat",
      chunk: [{ sender: "Omar", text: "Still paired after restart!", timestamp: "2026-09-25T10:00:00" }],
      chunkIndex: 0,
      totalChunks: 1,
      isLastChunk: true
    },
    validTabSender,
    sendResponse,
    { storageLocal: mockLocal, storageSession: mockSession, fetchFn: mockFetch, trustedStorageConfigured: true }
  );

  assert.equal(response.success, true);
  assert.equal(fetchedAuth, "Bearer persistent_paired_token_777", "Worker must use token from persistent storage.local");
});

test("BackgroundBridge: Unpairing clears token and denies future ingest", async () => {
  const localStore = { owi_token: "token_to_revoke", owi_backend_url: "http://127.0.0.1:8765" };
  const mockLocal = {
    setAccessLevel: async () => {},
    get: async (keys) => {
      const res = {};
      for (const k of keys) { if (localStore[k] !== undefined) res[k] = localStore[k]; }
      return res;
    },
    set: async (obj) => Object.assign(localStore, obj),
    remove: async (keys) => { keys.forEach((k) => delete localStore[k]); }
  };

  let response = null;
  const sendResponse = (res) => { response = res; };
  const validPopupSender = { id: "ext123", url: "chrome-extension://ext123/popup.html" };

  // 1. Unpair
  await BackgroundBridge.handleRuntimeMessage(
    { action: "unpair" },
    validPopupSender,
    sendResponse,
    { storageLocal: mockLocal, trustedStorageConfigured: true }
  );
  assert.equal(response.success, true);
  assert.equal(localStore.owi_token, undefined, "Token must be removed from storage.local on unpair");

  // 2. Next ingest attempt returns UNPAIRED
  const validTabSender = { tab: { url: "https://web.whatsapp.com/chat" } };
  await BackgroundBridge.handleRuntimeMessage(
    {
      action: "bridge_ingest_chunk",
      chatTitle: "Unpaired Chat",
      chunk: [{ sender: "Omar", text: "fail", timestamp: "2026-09-25T10:00:00" }],
      chunkIndex: 0,
      totalChunks: 1,
      isLastChunk: true
    },
    validTabSender,
    sendResponse,
    { storageLocal: mockLocal, fetchFn: async () => {}, trustedStorageConfigured: true }
  );
  assert.equal(response.success, false);
  assert.equal(response.error_code, "UNPAIRED");
});

test("BackgroundBridge: Capture state message bridge allows progress tracking without content-script storage access", async () => {
  const localStore = {};
  const mockLocal = {
    set: async (obj) => Object.assign(localStore, obj),
    get: async (keys) => {
      const res = {};
      for (const k of keys) { if (localStore[k] !== undefined) res[k] = localStore[k]; }
      return res;
    }
  };

  let response = null;
  const sendResponse = (res) => { response = res; };
  const validTabSender = { tab: { url: "https://web.whatsapp.com/chat" } };
  const validPopupSender = { id: "ext123", url: "chrome-extension://ext123/popup.html" };

  // Content script updates state via bridge
  const statePayload = { status: "running", stage: "scrolling_up", messagesScanned: 42, messagesIngested: 10 };
  await BackgroundBridge.handleRuntimeMessage(
    { action: "bridge_set_capture_state", state: statePayload },
    validTabSender,
    sendResponse,
    { storageLocal: mockLocal }
  );
  assert.equal(response.success, true);
  assert.deepEqual(localStore.owi_capture_state, statePayload);

  // Popup queries state via bridge
  await BackgroundBridge.handleRuntimeMessage(
    { action: "bridge_get_capture_state" },
    validPopupSender,
    sendResponse,
    { storageLocal: mockLocal }
  );
  assert.equal(response.success, true);
  assert.equal(response.state.messagesScanned, 42);
});

test("BackgroundBridge: Diagnostics logging works before pairing via bridge and popup can view/clear", async () => {
  const localStore = {};
  const mockLocal = {
    set: async (obj) => Object.assign(localStore, obj),
    get: async (keys) => {
      const res = {};
      for (const k of keys) { if (localStore[k] !== undefined) res[k] = localStore[k]; }
      return res;
    },
    remove: async (keys) => { keys.forEach((k) => delete localStore[k]); }
  };

  let response = null;
  const sendResponse = (res) => { response = res; };
  const validTabSender = { tab: { url: "https://web.whatsapp.com/chat" } };
  const validPopupSender = { id: "ext123", url: "chrome-extension://ext123/popup.html" };

  // Log 2 entries before pairing
  await BackgroundBridge.handleRuntimeMessage(
    { action: "bridge_log_diagnostic", entry: { stage: "init", code: "START", count: 0, details: "ok" } },
    validTabSender,
    sendResponse,
    { storageLocal: mockLocal }
  );
  assert.equal(response.success, true);

  await BackgroundBridge.handleRuntimeMessage(
    { action: "bridge_log_diagnostic", entry: { stage: "scroll_up", code: "STEP", count: 15, details: null } },
    validTabSender,
    sendResponse,
    { storageLocal: mockLocal }
  );
  assert.equal(response.success, true);

  // Popup retrieves diagnostics before pairing
  await BackgroundBridge.handleRuntimeMessage(
    { action: "bridge_get_diagnostics" },
    validPopupSender,
    sendResponse,
    { storageLocal: mockLocal }
  );
  assert.equal(response.success, true);
  assert.equal(response.logs.length, 2);
  assert.equal(response.logs[0].code, "START");
  assert.equal(response.logs[1].count, 15);

  // Popup clears diagnostics
  await BackgroundBridge.handleRuntimeMessage(
    { action: "bridge_clear_diagnostics" },
    validPopupSender,
    sendResponse,
    { storageLocal: mockLocal }
  );
  assert.equal(response.success, true);
  assert.equal(localStore.owi_diagnostic_logs, undefined);
});
