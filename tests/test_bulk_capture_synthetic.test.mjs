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

// --- 7. Attachment Capture, Truthful Status & Target Picker Tests ---

test("BulkEngine: detectMessageAttachments detects audio, video, document, and image attachments", () => {
  const mockMsgEl = {
    tagName: "DIV",
    classList: { contains: () => false },
    getAttribute: () => null,
    querySelector: function(sel) { return this.querySelectorAll(sel)[0] || null; },
    querySelectorAll: (sel) => {
      if (sel.includes("audio")) {
        return [{
          tagName: "AUDIO",
          src: "blob:https://web.whatsapp.com/audio-uuid-1",
          getAttribute: () => null
        }];
      }
      if (sel.includes("video")) {
        return [{
          tagName: "VIDEO",
          src: "blob:https://web.whatsapp.com/video-uuid-1",
          getAttribute: () => null
        }];
      }
      if (sel.includes("document-thumb")) {
        return [{
          tagName: "DIV",
          getAttribute: (attr) => (attr === "data-testid" ? "document-thumb" : (attr === "title" ? "Financial_Report.pdf" : null)),
          innerText: "Financial_Report.pdf"
        }];
      }
      if (sel.includes("img[src]")) {
        return [{
          tagName: "IMG",
          src: "blob:https://web.whatsapp.com/image-uuid-1",
          getAttribute: (attr) => (attr === "src" ? "blob:https://web.whatsapp.com/image-uuid-1" : null),
          classList: { contains: () => false }
        }];
      }
      return [];
    }
  };

  const atts = BulkEngine.detectMessageAttachments(mockMsgEl, "Test Chat");
  assert.equal(atts.length, 4);

  const audioAtt = atts.find((a) => a.file_type === "audio");
  assert.ok(audioAtt);
  assert.equal(audioAtt.blob_url, "blob:https://web.whatsapp.com/audio-uuid-1");
  assert.equal(audioAtt.attachment_status, "available");

  const vidAtt = atts.find((a) => a.file_type === "video");
  assert.ok(vidAtt);
  assert.equal(vidAtt.blob_url, "blob:https://web.whatsapp.com/video-uuid-1");

  const docAtt = atts.find((a) => a.file_type === "document");
  assert.ok(docAtt);
  assert.equal(docAtt.file_name, "Financial_Report.pdf");
  assert.equal(docAtt.mime_type, "application/pdf");

  const imgAtt = atts.find((a) => a.file_type === "image");
  assert.ok(imgAtt);
  assert.equal(imgAtt.blob_url, "blob:https://web.whatsapp.com/image-uuid-1");
});

test("BulkEngine: detectMessageAttachments handles multiple attachments on a single message", () => {
  const mockAlbumEl = {
    tagName: "DIV",
    classList: { contains: () => false },
    getAttribute: () => null,
    querySelector: function(sel) { return this.querySelectorAll(sel)[0] || null; },
    querySelectorAll: (sel) => {
      if (sel.includes("img[src]")) {
        return [
          {
            tagName: "IMG",
            src: "blob:https://web.whatsapp.com/img-1",
            getAttribute: (attr) => (attr === "src" ? "blob:https://web.whatsapp.com/img-1" : null),
            classList: { contains: () => false }
          },
          {
            tagName: "IMG",
            src: "blob:https://web.whatsapp.com/img-2",
            getAttribute: (attr) => (attr === "src" ? "blob:https://web.whatsapp.com/img-2" : null),
            classList: { contains: () => false }
          }
        ];
      }
      return [];
    }
  };

  const atts = BulkEngine.detectMessageAttachments(mockAlbumEl, "Album Chat");
  assert.equal(atts.length, 2, "Must detect both images in the album container");
  assert.equal(atts[0].blob_url, "blob:https://web.whatsapp.com/img-1");
  assert.equal(atts[1].blob_url, "blob:https://web.whatsapp.com/img-2");
});

test("BulkEngine: detectMessageAttachments flags preview-only thumbnail and unsupported extensions", () => {
  const mockEl = {
    tagName: "DIV",
    classList: { contains: () => false },
    getAttribute: () => null,
    querySelector: function(sel) { return this.querySelectorAll(sel)[0] || null; },
    querySelectorAll: (sel) => {
      if (sel.includes("document-thumb")) {
        return [{
          tagName: "DIV",
          getAttribute: (attr) => (attr === "title" ? "trojan.exe" : (attr === "data-testid" ? "document-thumb" : null)),
          innerText: "trojan.exe"
        }];
      }
      if (sel.includes("img[src]")) {
        return [{
          tagName: "IMG",
          src: "data:image/jpeg;base64,/9j/4AAQSkZJRg==", // Small preview data URI
          getAttribute: (attr) => (attr === "src" ? "data:image/jpeg;base64,/9j/4AAQSkZJRg==" : null),
          classList: { contains: (c) => c === "thumbnail" }
        }];
      }
      return [];
    }
  };

  const atts = BulkEngine.detectMessageAttachments(mockEl, "Security Test");
  assert.equal(atts.length, 2);

  const doc = atts.find((a) => a.file_name === "trojan.exe");
  assert.ok(doc);
  assert.equal(doc.attachment_status, "unsupported", ".exe must be flagged unsupported");

  const img = atts.find((a) => a.file_type === "image");
  assert.ok(img);
  assert.equal(img.is_thumbnail_only, true);
  assert.equal(img.attachment_status, "preview-only");
});

test("BulkEngine: Bounded chunking and memory-safe base64 conversion", () => {
  const rawData = new Uint8Array(500 * 1024); // 500 KB
  for (let i = 0; i < rawData.length; i++) {
    rawData[i] = i % 256;
  }

  const chunks = BulkEngine.sliceIntoChunks(rawData, 128 * 1024);
  assert.equal(chunks.length, 4, "500 KB / 128 KB should produce 4 chunks");
  assert.equal(chunks[0].byteLength, 128 * 1024);
  assert.equal(chunks[3].byteLength, 116 * 1024);

  const b64 = BulkEngine.uint8ArrayToBase64(rawData);
  assert.ok(b64.length > 0);
  const decoded = Buffer.from(b64, "base64");
  assert.equal(decoded.length, rawData.length);
  assert.equal(decoded[0], rawData[0]);
  assert.equal(decoded[decoded.length - 1], rawData[rawData.length - 1]);
});

test("BulkEngine: captureAttachmentOriginalBytes truthfully distinguishes statuses", async () => {
  // 1. Saved original from blob
  const sampleBytes = Buffer.from("OWI Original Audio Bytes 2026", "utf-8");
  const mockFetchOk = async () => ({
    ok: true,
    blob: async () => ({
      size: sampleBytes.length,
      type: "audio/ogg",
      arrayBuffer: async () => sampleBytes.buffer
    })
  });

  const resOk = await BulkEngine.captureAttachmentOriginalBytes(
    {
      file_name: "voice.ogg",
      file_type: "audio",
      mime_type: "audio/ogg",
      blob_url: "blob:https://web.whatsapp.com/voice-1",
      is_thumbnail_only: false
    },
    { fetchFn: mockFetchOk }
  );

  assert.equal(resOk.status, "saved-original");
  assert.equal(resOk.file_size, sampleBytes.length);
  assert.ok(resOk.sha256);

  // 2. Preview only - never claim saved-original
  const resPreview = await BulkEngine.captureAttachmentOriginalBytes(
    {
      file_name: "thumb.jpg",
      file_type: "image",
      mime_type: "image/jpeg",
      blob_url: "blob:https://web.whatsapp.com/thumb-1",
      is_thumbnail_only: true // Explicit preview
    },
    { fetchFn: mockFetchOk }
  );

  assert.equal(resPreview.status, "preview-only", "Thumbnail must be marked preview-only, never saved-original");

  // 3. Expired blob (404/revoked)
  const mockFetch404 = async () => ({ ok: false, status: 404 });
  const resExpired = await BulkEngine.captureAttachmentOriginalBytes(
    {
      file_name: "expired.pdf",
      file_type: "document",
      blob_url: "blob:https://web.whatsapp.com/expired-1"
    },
    { fetchFn: mockFetch404 }
  );
  assert.equal(resExpired.status, "expired");

  // 4. Too large
  const mockFetchTooLarge = async () => ({
    ok: true,
    blob: async () => ({
      size: 100 * 1024 * 1024, // 100 MB
      arrayBuffer: async () => new ArrayBuffer(0)
    })
  });
  const resTooLarge = await BulkEngine.captureAttachmentOriginalBytes(
    {
      file_name: "huge_video.mp4",
      file_type: "video",
      blob_url: "blob:https://web.whatsapp.com/video-huge"
    },
    { fetchFn: mockFetchTooLarge, maxBytes: 50 * 1024 * 1024 }
  );
  assert.equal(resTooLarge.status, "too-large");

  // 5. Unsupported format
  const resUnsupported = await BulkEngine.captureAttachmentOriginalBytes({
    file_name: "script.bat",
    file_type: "document",
    blob_url: "blob:https://web.whatsapp.com/script-1"
  });
  assert.equal(resUnsupported.status, "unsupported");
});

test("BulkEngine: uploadCapturedMediaItem uploads direct (<=2MB) and cleans up in-memory bytes", async () => {
  const dummyBytes = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8]);
  const att = {
    file_name: "photo.jpg",
    file_type: "image",
    mime_type: "image/jpeg",
    file_size: dummyBytes.byteLength,
    attachment_status: "saved-original",
    sha256: "abc123sha",
    bytes: dummyBytes
  };

  let bridgePayload = null;
  const mockSender = async (payload) => {
    bridgePayload = payload;
    return { success: true, data: { asset_id: 42 } };
  };

  const res = await BulkEngine.uploadCapturedMediaItem({
    attachment: att,
    conversationId: 13,
    platformMsgId: "msg_123",
    chatTitle: "H",
    bridgeSender: mockSender,
    maxDirectBytes: 2 * 1024 * 1024
  });

  assert.equal(res.success, true);
  assert.equal(att.attachment_status, "saved-original");
  assert.equal(att.bytes, null, "Bytes must be cleared to prevent in-memory leaks");
  assert.equal(bridgePayload.action, "bridge_media_upload");
  assert.equal(bridgePayload.conversationId, 13);
  assert.equal(bridgePayload.platformMsgId, "msg_123");
});

test("BulkEngine: uploadCapturedMediaItem uploads via session (>2MB) in bounded chunks", async () => {
  const dummyBytes = new Uint8Array(3 * 1024 * 1024); // 3 MB > 2 MB cap
  const att = {
    file_name: "big_video.mp4",
    file_type: "video",
    mime_type: "video/mp4",
    file_size: dummyBytes.byteLength,
    attachment_status: "saved-original",
    sha256: "sha_vid_777",
    bytes: dummyBytes
  };

  const sentActions = [];
  const mockSender = async (payload) => {
    sentActions.push(payload.action);
    return { success: true, data: { status: "success" } };
  };

  const res = await BulkEngine.uploadCapturedMediaItem({
    attachment: att,
    conversationId: 13,
    bridgeSender: mockSender,
    maxDirectBytes: 2 * 1024 * 1024,
    chunkSize: 1024 * 1024 // 1 MB chunk
  });

  assert.equal(res.success, true);
  assert.equal(att.bytes, null);
  assert.equal(sentActions[0], "bridge_media_session_start");
  assert.ok(sentActions.includes("bridge_media_session_chunk"));
  assert.equal(sentActions[sentActions.length - 1], "bridge_media_session_finish");
});

test("BulkEngine: postChunkWithRetry passes targetConversationId, confirmTargetMerge, and attachment metadata", async () => {
  let forwardedPayload = null;
  const mockSender = async (p) => {
    forwardedPayload = p;
    return { success: true, data: { messages_ingested: 1 } };
  };

  const res = await BulkEngine.postChunkWithRetry({
    chatTitle: "WhatsApp Web H",
    chunk: [
      {
        sender: "H",
        text: "Document attached",
        timestamp: "2026-09-25T10:00:00",
        platform_msg_id: "p_msg_99",
        has_media: true,
        media_type: "document",
        media_filename: "Contract.pdf",
        attachment_status: "saved-original",
        attachments: [
          {
            file_name: "Contract.pdf",
            file_type: "document",
            mime_type: "application/pdf",
            file_size: 15000,
            sha256: "sha_contract_123",
            attachment_status: "saved-original"
          }
        ]
      }
    ],
    chunkIndex: 0,
    totalChunks: 1,
    isLastChunk: true,
    targetConversationId: 13,
    confirmTargetMerge: true,
    bridgeSender: mockSender
  });

  assert.equal(res.success, true);
  assert.equal(forwardedPayload.targetConversationId, 13);
  assert.equal(forwardedPayload.confirmTargetMerge, true);
  assert.equal(forwardedPayload.chunk[0].attachment_status, "saved-original");
  assert.equal(forwardedPayload.chunk[0].attachments.length, 1);
  assert.equal(forwardedPayload.chunk[0].attachments[0].file_name, "Contract.pdf");
});

test("BackgroundBridge: Target picker query bridge returns target list from backend", async () => {
  const localStore = { owi_token: "token_abc", owi_backend_url: "http://127.0.0.1:8765" };
  const mockLocal = {
    setAccessLevel: async () => {},
    get: async () => localStore
  };

  const mockFetch = async (url) => {
    assert.ok(url.endsWith("/api/companion/targets"));
    return {
      ok: true,
      json: async () => ({
        targets: [
          { id: 13, title: "H", source_type: "export_zip", message_count: 197 },
          { id: 14, title: "Work Group", source_type: "companion", message_count: 50 }
        ]
      })
    };
  };

  let response = null;
  const sendResponse = (res) => { response = res; };
  const validPopupSender = { id: "ext123", url: "chrome-extension://ext123/popup.html" };

  await BackgroundBridge.handleRuntimeMessage(
    { action: "bridge_get_targets" },
    validPopupSender,
    sendResponse,
    { storageLocal: mockLocal, fetchFn: mockFetch, trustedStorageConfigured: true }
  );

  assert.equal(response.success, true);
  assert.equal(response.targets.length, 2);
  assert.equal(response.targets[0].id, 13);
  assert.equal(response.targets[0].source_type, "export_zip");
  assert.equal(response.targets[0].message_count, 197);
});

// --- 7. Reviewer Delta Synthetic Tests (P0 1 - P0 4) ---

test("BulkEngine: runBulkCapture wires media upload parameters through initial viewport and virtualized scroll", async () => {
  const bridgeCalls = [];
  const mockSender = async (p) => {
    bridgeCalls.push(p);
    return { success: true, data: { asset_id: bridgeCalls.length } };
  };

  const fakeFetch = async (url) => {
    const data = Buffer.from("PDF content for " + url);
    return {
      ok: true,
      blob: async () => ({
        size: data.length,
        type: "application/pdf",
        arrayBuffer: async () => data.buffer
      })
    };
  };

  const mockDoc = {
    querySelector: (sel) => {
      if (sel.includes("conversation-info-header") || sel.includes("header")) {
        return { innerText: "H", getAttribute: () => "H" };
      }
      return null;
    }
  };

  const createMsgNode = (id, timeStr, text, blobUrl, fileName) => ({
    getAttribute: (attr) => (attr === "data-id" ? id : null),
    classList: { contains: (cls) => cls === "message-in" },
    getBoundingClientRect: () => ({ top: 10, bottom: 50 }),
    innerText: text,
    querySelector: (sel) => {
      if (sel.includes("selectable-text") || sel.includes("copyable-text")) {
        return { innerText: text, getAttribute: () => `[${timeStr}] Omar: ` };
      }
      return null;
    },
    querySelectorAll: (sel) => {
      if (sel.includes("document") || sel.includes(".")) {
        return [{
          getAttribute: (attr) => (attr === "title" ? fileName : null),
          innerText: fileName,
          tagName: "DIV",
          parentElement: null,
          querySelector: (s) => (s.includes("a[href") ? { href: blobUrl } : null)
        }];
      }
      return [];
    }
  });

  const node1 = createMsgNode("wam_doc_1", "10:00, 25/09/2026", "Doc 1 attached", "blob:http://localhost/doc1", "doc1.pdf");
  const node2 = createMsgNode("wam_doc_2", "10:05, 25/09/2026", "Doc 2 attached", "blob:http://localhost/doc2", "doc2.pdf");

  const mockContainer = {
    scrollTop: 0,
    clientHeight: 200,
    scrollHeight: 400,
    getBoundingClientRect: () => ({ top: 0, bottom: 200 }),
    querySelectorAll: () => {
      if (mockContainer.scrollTop === 0) {
        return [node1];
      } else {
        return [node2];
      }
    }
  };

  const captureSessionId = "sess_bulk_test_42";
  const result = await BulkEngine.runBulkCapture({
    container: mockContainer,
    doc: mockDoc,
    mode: "visible_to_newest",
    captureMedia: true,
    targetConversationId: 13,
    confirmTargetMerge: true,
    sessionId: captureSessionId,
    bridgeSender: mockSender,
    fetchFn: fakeFetch,
    maxScrollAttempts: 3,
    scrollDelayMs: 2
  });

  assert.equal(result.messages.length, 2);
  const mediaUploads = bridgeCalls.filter(c => c.action === "bridge_media_upload");
  assert.equal(mediaUploads.length, 2);

  // Assert ALL worker bridge payloads include the same target, confirmation, session
  for (const upload of mediaUploads) {
    assert.equal(upload.conversationId, 13);
    assert.equal(upload.confirmTargetMerge, true);
    assert.equal(upload.sessionId, captureSessionId);
    assert.ok(upload.messageKey);
    assert.ok(upload.attachmentPosition >= 1);
  }

  assert.equal(mediaUploads[0].messageKey, "wam_doc_1");
  assert.equal(mediaUploads[1].messageKey, "wam_doc_2");
});

test("BulkEngine: >2MB attachment chunked upload uses single uploadSessionId across start/chunk/finish and carries captureSessionId", async () => {
  const bridgeCalls = [];
  const mockSender = async (p) => {
    bridgeCalls.push(p);
    return { success: true, data: { status: "session_finished" } };
  };

  const largeBytes = new Uint8Array(2.5 * 1024 * 1024);
  largeBytes.fill(65);

  const att1 = {
    id: "att_1",
    file_type: "document",
    file_name: "large_blueprint.pdf",
    mime_type: "application/pdf",
    bytes: largeBytes,
    file_size: largeBytes.byteLength,
    attachment_status: "saved-original",
    sha256: "sha_large_123"
  };

  const captureSessionId = "capture_sess_abc";

  const res1 = await BulkEngine.uploadCapturedMediaItem({
    attachment: att1,
    attachmentPosition: 1,
    conversationId: 13,
    confirmTargetMerge: true,
    platformMsgId: "msg_large_1",
    messageKey: "msg_large_1",
    sessionId: captureSessionId,
    bridgeSender: mockSender,
    maxDirectBytes: 2 * 1024 * 1024,
    chunkSize: 1024 * 1024
  });

  assert.equal(res1.success, true);
  assert.equal(res1.status, "saved-original");

  const startCalls = bridgeCalls.filter(c => c.action === "bridge_media_session_start");
  const chunkCalls = bridgeCalls.filter(c => c.action === "bridge_media_session_chunk");
  const finishCalls = bridgeCalls.filter(c => c.action === "bridge_media_session_finish");

  assert.equal(startCalls.length, 1);
  assert.ok(chunkCalls.length >= 2);
  assert.equal(finishCalls.length, 1);

  const uploadSessId1 = startCalls[0].sessionId;
  assert.ok(uploadSessId1.startsWith("media_upload_"));
  assert.equal(startCalls[0].capture_session_id, captureSessionId);
  assert.equal(startCalls[0].conversationId, 13);
  assert.equal(startCalls[0].confirmTargetMerge, true);

  for (const chunk of chunkCalls) {
    assert.equal(chunk.sessionId, uploadSessId1, "All chunks must use uploadSessionId, not captureSessionId or null");
  }
  assert.equal(finishCalls[0].sessionId, uploadSessId1, "Finish must use uploadSessionId, not captureSessionId or null");

  // Second attachment in same capture session
  const att2 = {
    id: "att_2",
    file_type: "video",
    file_name: "large_video.mp4",
    mime_type: "video/mp4",
    bytes: largeBytes,
    file_size: largeBytes.byteLength,
    attachment_status: "saved-original",
    sha256: "sha_video_456"
  };

  const res2 = await BulkEngine.uploadCapturedMediaItem({
    attachment: att2,
    attachmentPosition: 2,
    conversationId: 13,
    confirmTargetMerge: true,
    platformMsgId: "msg_large_1",
    messageKey: "msg_large_1",
    sessionId: captureSessionId,
    bridgeSender: mockSender,
    maxDirectBytes: 2 * 1024 * 1024,
    chunkSize: 1024 * 1024
  });

  assert.equal(res2.success, true);
  const startCalls2 = bridgeCalls.filter(c => c.action === "bridge_media_session_start");
  assert.equal(startCalls2.length, 2);
  const uploadSessId2 = startCalls2[1].sessionId;
  assert.notEqual(uploadSessId1, uploadSessId2, "Distinct attachments must use distinct uploadSessionIds");
  assert.equal(startCalls2[1].capture_session_id, captureSessionId, "Both must carry same captureSessionId");
});

test("BulkEngine: Never upgrades preview/thumbnail to saved-original and preserves truthful status", async () => {
  // 1. Data URI preview
  const dataUriAtt = {
    id: "att_thumb_data",
    file_type: "image",
    file_name: "thumbnail.jpg",
    mime_type: "image/jpeg",
    blob_url: "data:image/jpeg;base64,/9j/4AAQSkZJRg==",
    is_thumbnail_only: true,
    attachment_status: "preview-only"
  };

  const resData = await BulkEngine.captureAttachmentOriginalBytes(dataUriAtt);
  assert.equal(resData.status, "preview-only");

  dataUriAtt.attachment_status = resData.status;
  dataUriAtt.bytes = resData.bytes;
  let bridgeCalled = false;
  const mockSender = async () => { bridgeCalled = true; return { success: true }; };
  const uploadResData = await BulkEngine.uploadCapturedMediaItem({
    attachment: dataUriAtt,
    bridgeSender: mockSender
  });
  assert.equal(uploadResData.success, false);
  assert.equal(uploadResData.status, "preview-only");
  assert.equal(bridgeCalled, false, "Must never bridge-upload preview-only bytes as original");

  // 2. Blob in-chat thumbnail with is_thumbnail_only
  const fakeBlobFetch = async () => ({
    ok: true,
    blob: async () => ({
      size: 500,
      type: "image/jpeg",
      arrayBuffer: async () => new Uint8Array(500).buffer
    })
  });

  const blobThumbAtt = {
    id: "att_thumb_blob",
    file_type: "image",
    file_name: "thumb_blob.jpg",
    mime_type: "image/jpeg",
    blob_url: "blob:http://localhost/thumb1",
    is_thumbnail_only: true,
    attachment_status: "preview-only"
  };

  const resBlobThumb = await BulkEngine.captureAttachmentOriginalBytes(blobThumbAtt, { fetchFn: fakeBlobFetch });
  assert.equal(resBlobThumb.status, "preview-only");

  blobThumbAtt.attachment_status = resBlobThumb.status;
  blobThumbAtt.bytes = resBlobThumb.bytes;
  const uploadResBlob = await BulkEngine.uploadCapturedMediaItem({
    attachment: blobThumbAtt,
    bridgeSender: mockSender
  });
  assert.equal(uploadResBlob.success, false);
  assert.equal(uploadResBlob.status, "preview-only");
  assert.equal(bridgeCalled, false);

  // 3. True full-size document: succeeds as saved-original
  const fullDocAtt = {
    id: "att_full_doc",
    file_type: "document",
    file_name: "contract.pdf",
    mime_type: "application/pdf",
    blob_url: "blob:http://localhost/contract",
    is_thumbnail_only: false,
    attachment_status: "available"
  };

  const resFullDoc = await BulkEngine.captureAttachmentOriginalBytes(fullDocAtt, { fetchFn: fakeBlobFetch });
  assert.equal(resFullDoc.status, "saved-original");
  assert.ok(resFullDoc.bytes);

  fullDocAtt.attachment_status = resFullDoc.status;
  fullDocAtt.bytes = resFullDoc.bytes;
  const uploadResFull = await BulkEngine.uploadCapturedMediaItem({
    attachment: fullDocAtt,
    bridgeSender: mockSender
  });
  assert.equal(uploadResFull.success, true);
  assert.equal(uploadResFull.status, "saved-original");
  assert.equal(bridgeCalled, true);
});

test("BulkEngine: Detects older messages button, clicks repeatedly, and reports older_messages_button_unexhausted if unexhausted", async () => {
  let olderBtnClicks = 0;
  let olderBtnVisible = true;

  // Broad ancestor div whose text merely contains the phrase (e.g. chat container / wrapper)
  // Must NEVER be selected or clicked!
  const mockBroadAncestorDiv = {
    tagName: "DIV",
    innerText: "Earlier messages in H chat...\nClick here to get older messages from your phone.\nLater messages...",
    textContent: "Earlier messages in H chat...\nClick here to get older messages from your phone.\nLater messages...",
    getAttribute: (attr) => (attr === "class" ? "chat-container" : null),
    closest: (sel) => null,
    click: () => {
      throw new Error("Broad ancestor div must never be clicked as the older messages button!");
    }
  };

  // The actual interactive button (or closest actionable ancestor)
  const mockActionableBtn = {
    tagName: "DIV",
    innerText: "Click here to get older messages from your phone.",
    textContent: "Click here to get older messages from your phone.",
    getAttribute: (attr) => (attr === "role" ? "button" : null),
    closest: function (sel) {
      if (sel.includes("button") || sel.includes("[role='button']")) {
        return mockActionableBtn;
      }
      return null;
    },
    click: () => {
      olderBtnClicks++;
      if (olderBtnClicks >= 2) {
        olderBtnVisible = false;
      }
    }
  };

  // Inner span inside the button whose closest("button, [role='button']") resolves to mockActionableBtn
  const mockInnerSpan = {
    tagName: "SPAN",
    innerText: "Click here to get older messages from your phone.",
    textContent: "Click here to get older messages from your phone.",
    getAttribute: () => null,
    closest: function (sel) {
      if (sel.includes("button") || sel.includes("[role='button']")) {
        return mockActionableBtn;
      }
      return null;
    },
    click: () => {
      mockActionableBtn.click();
    }
  };

  const mockDoc = {
    querySelector: (sel) => {
      if (sel.includes("conversation-info-header") || sel.includes("header")) {
        return { innerText: "H", getAttribute: () => "H" };
      }
      if (olderBtnVisible && (sel.includes("button") || sel.includes("[role='button']"))) {
        return mockActionableBtn;
      }
      return null;
    },
    querySelectorAll: (sel) => {
      if (sel.includes("button") || sel.includes("[role='button']")) {
        return olderBtnVisible ? [mockActionableBtn] : [];
      }
      if (sel.includes("span")) {
        return olderBtnVisible ? [mockInnerSpan] : [];
      }
      if (sel.includes("div")) {
        // Broad ancestor div comes first in document order!
        return olderBtnVisible ? [mockBroadAncestorDiv, mockActionableBtn] : [mockBroadAncestorDiv];
      }
      return [];
    }
  };

  let scrollUpCalls = 0;
  const mockContainer = {
    scrollTop: 0,
    scrollHeight: 500,
    clientHeight: 200,
    getBoundingClientRect: () => ({ top: 0, bottom: 200 }),
    querySelector: () => null,
    querySelectorAll: (sel = "") => {
      if (sel.includes("button") || sel.includes("[role='button']")) {
        return olderBtnVisible ? [mockActionableBtn] : [];
      }
      if (sel.includes("span")) {
        return olderBtnVisible ? [mockInnerSpan] : [];
      }
      if (sel.includes("div") && !sel.includes("data-id") && !sel.includes("message")) {
        return olderBtnVisible ? [mockBroadAncestorDiv, mockActionableBtn] : [mockBroadAncestorDiv];
      }
      scrollUpCalls++;
      const day = String(Math.max(18, 25 - (scrollUpCalls - 1) * 2)).padStart(2, '0');
      return [
        {
          getAttribute: (attr) => (attr === "data-id" ? `msg_older_${scrollUpCalls}` : null),
          classList: { contains: () => false },
          getBoundingClientRect: () => ({ top: 10, bottom: 30 }),
          querySelector: () => ({ innerText: `Older message ${scrollUpCalls}`, getAttribute: () => `[23:59, ${day}/09/2026] User: ` })
        }
      ];
    }
  };

  // 1. When older messages button is exhausted after clicks, completes successfully
  const resExhausted = await BulkEngine.runBulkCapture({
    container: mockContainer,
    doc: mockDoc,
    mode: "date_range",
    fromDate: "2026-09-19T00:00:00",
    toDate: "2026-09-25T23:59:00",
    maxScrollAttempts: 5,
    scrollDelayMs: 2
  });

  assert.ok(olderBtnClicks >= 2, "Must activate older messages button repeatedly");
  assert.equal(resExhausted.completenessStatus, "complete");

  // 2. If older messages button remains visible when scrolling stops at top, must report partial with older_messages_button_unexhausted
  olderBtnVisible = true;
  olderBtnClicks = 0;
  const mockUnexhaustedBtn = {
    tagName: "DIV",
    innerText: "Click here to get older messages from your phone.",
    textContent: "Click here to get older messages from your phone.",
    getAttribute: (attr) => (attr === "role" ? "button" : null),
    closest: (sel) => (sel.includes("button") || sel.includes("[role='button']") ? mockUnexhaustedBtn : null),
    click: () => { olderBtnClicks++; }
  };
  const mockDocUnexhausted = {
    querySelector: (sel) => {
      if (sel.includes("conversation-info-header") || sel.includes("header")) {
        return { innerText: "H", getAttribute: () => "H" };
      }
      return mockUnexhaustedBtn;
    },
    querySelectorAll: (sel) => {
      if (sel.includes("button") || sel.includes("[role='button']")) {
        return [mockUnexhaustedBtn];
      }
      if (sel.includes("span")) {
        return [mockUnexhaustedBtn];
      }
      if (sel.includes("div")) {
        return [mockBroadAncestorDiv, mockUnexhaustedBtn];
      }
      return [];
    }
  };

  const resUnexhausted = await BulkEngine.runBulkCapture({
    container: mockContainer,
    doc: mockDocUnexhausted,
    mode: "date_range",
    fromDate: "2026-09-01T00:00:00",
    toDate: "2026-09-25T23:59:59",
    maxScrollAttempts: 3,
    scrollDelayMs: 2
  });

  assert.equal(resUnexhausted.completenessStatus, "partial");
  assert.equal(resUnexhausted.partialReason, "older_messages_button_unexhausted");
});

test("BulkEngine: findOlderMessagesButton selects actionable button and never selects broad ancestor div", () => {
  const mockBroadAncestorDiv = {
    tagName: "DIV",
    innerText: "Messages...\nClick here to get older messages from your phone.\nMore...",
    textContent: "Messages...\nClick here to get older messages from your phone.\nMore...",
    getAttribute: (attr) => (attr === "class" ? "chat-container" : null),
    closest: () => null,
    click: () => { throw new Error("Must never click broad ancestor div"); }
  };

  const mockActionableBtn = {
    tagName: "DIV",
    innerText: "Click here to get older messages from your phone.",
    textContent: "Click here to get older messages from your phone.",
    getAttribute: (attr) => (attr === "role" ? "button" : null),
    closest: (sel) => (sel.includes("button") || sel.includes("[role='button']") ? mockActionableBtn : null),
    click: () => {}
  };

  const mockInnerSpan = {
    tagName: "SPAN",
    innerText: "Click here to get older messages from your phone.",
    textContent: "Click here to get older messages from your phone.",
    getAttribute: () => null,
    closest: (sel) => (sel.includes("button") || sel.includes("[role='button']") ? mockActionableBtn : null)
  };

  const mockDocWithBoth = {
    querySelectorAll: (sel) => {
      if (sel.includes("button") || sel.includes("[role='button']")) {
        return [mockActionableBtn];
      }
      if (sel.includes("span")) {
        return [mockInnerSpan];
      }
      if (sel.includes("div")) {
        return [mockBroadAncestorDiv, mockActionableBtn];
      }
      return [];
    }
  };

  // 1. Selects actionable button, not broad ancestor div
  const btn = BulkEngine.findOlderMessagesButton(null, mockDocWithBoth);
  assert.equal(btn, mockActionableBtn);

  // 2. When only broad ancestor div is present, returns null (never selects broad div)
  const mockDocOnlyBroad = {
    querySelectorAll: (sel) => {
      if (sel.includes("div")) {
        return [mockBroadAncestorDiv];
      }
      return [];
    }
  };
  const nullBtn = BulkEngine.findOlderMessagesButton(null, mockDocOnlyBroad);
  assert.equal(nullBtn, null);
});

test("BulkEngine: Older messages button clicking is bounded and cancellation-safe", async () => {
  let olderClicks = 0;
  let cancelled = false;

  const mockActionableBtn = {
    tagName: "BUTTON",
    innerText: "Click here to get older messages from your phone.",
    textContent: "Click here to get older messages from your phone.",
    getAttribute: () => null,
    closest: () => mockActionableBtn,
    click: () => {
      olderClicks++;
      if (olderClicks >= 1) {
        cancelled = true;
      }
    }
  };

  const mockDoc = {
    querySelector: (sel) => ({ innerText: "H", getAttribute: () => "H" }),
    querySelectorAll: (sel) => {
      if (sel.includes("button") || sel.includes("[role='button']")) return [mockActionableBtn];
      return [];
    }
  };

  const mockContainer = {
    scrollTop: 0,
    scrollHeight: 500,
    clientHeight: 200,
    getBoundingClientRect: () => ({ top: 0, bottom: 200 }),
    querySelector: () => null,
    querySelectorAll: () => [
      {
        getAttribute: (attr) => (attr === "data-id" ? "msg_cancel" : null),
        classList: { contains: () => false },
        getBoundingClientRect: () => ({ top: 10, bottom: 30 }),
        querySelector: () => ({ innerText: "Msg", getAttribute: () => "[10:00, 24/09/2026] User: " })
      }
    ]
  };

  const res = await BulkEngine.runBulkCapture({
    container: mockContainer,
    doc: mockDoc,
    mode: "date_range",
    fromDate: "2026-09-01T00:00:00",
    toDate: "2026-09-25T23:59:59",
    maxScrollAttempts: 5,
    scrollDelayMs: 2,
    checkCancelled: () => cancelled
  });

  assert.equal(res.completenessStatus, "partial");
  assert.equal(res.partialReason, "cancelled_by_user");
  assert.equal(olderClicks, 1, "Must immediately halt clicking upon cancellation");
});

// --- 7. Live DOM Sanity & Regression Tests (2026-09-25 Audit) ---

test("BulkEngine: extractChatTitle avoids 'Profile details' trap and extracts actual chat title 'H'", () => {
  // Live DOM scenario: An avatar/info icon with title="Profile details" precedes the chat title in the header
  const mockHeader = {
    tagName: "HEADER",
    getAttribute: (attr) => (attr === "data-testid" ? "conversation-header" : null),
    querySelector: (sel) => {
      if (sel.includes("conversation-info-header-chat-title")) {
        return {
          tagName: "DIV",
          innerText: "H",
          textContent: "H",
          getAttribute: (attr) => (attr === "data-testid" ? "conversation-info-header-chat-title" : null)
        };
      }
      if (sel.includes("conversation-info-header")) {
        return {
          tagName: "DIV",
          innerText: "H",
          textContent: "H",
          getAttribute: () => null
        };
      }
      return null;
    },
    querySelectorAll: (sel) => {
      if (sel.includes("[title]")) {
        return [
          { getAttribute: () => "Profile details", innerText: "Profile details" },
          { getAttribute: () => "H", innerText: "H" }
        ];
      }
      return [];
    }
  };

  const mockDoc = {
    querySelector: (sel) => {
      if (sel.includes("header[data-testid='conversation-header']") || sel.includes("conversation-info-header-chat-title")) {
        return mockHeader.querySelector(sel);
      }
      return null;
    },
    querySelectorAll: (sel) => mockHeader.querySelectorAll(sel)
  };

  const title = BulkEngine.extractChatTitle(mockDoc);
  assert.equal(title, "H", "Must extract chat title 'H' and never accept 'Profile details'");
  assert.equal(BulkEngine.isInvalidChatTitle("Profile details"), true);
  assert.equal(BulkEngine.isInvalidChatTitle("تفاصيل الملف الشخصي"), true);
  assert.equal(BulkEngine.isInvalidChatTitle("H"), false);
});

test("BulkEngine: Media-only message derives defensible calendar date from preceding date divider", () => {
  // Container has date divider with 14/09/2026 followed by media-only message row with time 3:21 pm
  const mockDivider = {
    tagName: "DIV",
    getAttribute: (attr) => (attr === "data-testid" ? "date-divider" : null),
    classList: { contains: (c) => c === "date-divider" },
    innerText: "14/09/2026",
    textContent: "14/09/2026",
    querySelectorAll: () => []
  };

  const mockMediaRow = {
    tagName: "DIV",
    getAttribute: (attr) => (attr === "data-id" ? "false_msg_media_1" : (attr === "data-testid" ? "conv-msg-media" : null)),
    classList: { contains: () => false },
    previousElementSibling: mockDivider,
    nextElementSibling: null,
    parentElement: null,
    querySelector: (sel) => {
      if (sel.includes("data-pre-plain-text")) return null; // No pre-plain-text on media-only
      if (sel.includes("msg-meta")) {
        return { innerText: "3:21 pm", textContent: "3:21 pm", getAttribute: () => null };
      }
      return null;
    },
    querySelectorAll: (sel) => {
      if (sel.includes("img[src]")) {
        return [{
          tagName: "IMG",
          src: "blob:https://web.whatsapp.com/img1",
          getAttribute: (attr) => (attr === "src" ? "blob:https://web.whatsapp.com/img1" : null),
          classList: { contains: () => false }
        }];
      }
      return [];
    }
  };

  const mockContainer = {
    previousElementSibling: null,
    nextElementSibling: null
  };
  mockMediaRow.parentElement = mockContainer;

  const parsed = BulkEngine.parseMessageNode(mockMediaRow, "H", "DD/MM/YYYY", mockContainer);
  assert.ok(parsed);
  assert.equal(parsed.has_media, true);
  assert.equal(parsed.media_type, "image");
  assert.equal(parsed.raw_timestamp, "3:21 pm");
  assert.equal(parsed.timestamp_provenance, "derived_neighbor");
  assert.ok(parsed.parsed_date, "Must parse date derived from date divider");
  assert.equal(parsed.timestamp, "2026-09-14T15:21:00");
});

test("BulkEngine: Media-only message derives defensible calendar date from neighboring message row", () => {
  // Container has preceding text message row on 14/09/2026 followed by media-only row
  const mockTextRow = {
    tagName: "DIV",
    getAttribute: (attr) => (attr === "data-id" ? "false_msg_text_1" : null),
    classList: { contains: () => false },
    querySelector: (sel) => {
      if (sel.includes("data-pre-plain-text")) {
        return { getAttribute: () => "[10:15 am, 14/09/2026] H: " };
      }
      return null;
    }
  };

  const mockMediaRow = {
    tagName: "DIV",
    getAttribute: (attr) => (attr === "data-id" ? "false_msg_media_2" : null),
    classList: { contains: () => false },
    previousElementSibling: mockTextRow,
    nextElementSibling: null,
    querySelector: (sel) => {
      if (sel.includes("data-pre-plain-text")) return null;
      if (sel.includes("msg-meta")) {
        return { innerText: "3:21 pm", textContent: "3:21 pm", getAttribute: () => null };
      }
      return null;
    },
    querySelectorAll: (sel) => {
      if (sel.includes("img[src]")) {
        return [{
          tagName: "IMG",
          src: "blob:https://web.whatsapp.com/img2",
          getAttribute: (attr) => (attr === "src" ? "blob:https://web.whatsapp.com/img2" : null),
          classList: { contains: () => false }
        }];
      }
      return [];
    }
  };

  const parsed = BulkEngine.parseMessageNode(mockMediaRow, "H", "DD/MM/YYYY");
  assert.ok(parsed);
  assert.equal(parsed.timestamp, "2026-09-14T15:21:00");
  assert.equal(parsed.timestamp_provenance, "derived_neighbor");
});

test("BulkEngine: Isolated media-only message without date context marks unverified and never falls back to current date", async () => {
  const mockMediaRow = {
    tagName: "DIV",
    getAttribute: (attr) => (attr === "data-id" ? "false_msg_isolated" : null),
    classList: { contains: () => false },
    previousElementSibling: null,
    nextElementSibling: null,
    parentElement: null,
    getBoundingClientRect: () => ({ top: 10, bottom: 40 }),
    querySelector: (sel) => {
      if (sel.includes("data-pre-plain-text")) return null;
      if (sel.includes("msg-meta")) {
        return { innerText: "3:21 pm", textContent: "3:21 pm", getAttribute: () => null };
      }
      return null;
    },
    querySelectorAll: (sel) => {
      if (sel.includes("img[src]")) {
        return [{
          tagName: "IMG",
          src: "blob:https://web.whatsapp.com/img_iso",
          getAttribute: (attr) => (attr === "src" ? "blob:https://web.whatsapp.com/img_iso" : null),
          classList: { contains: () => false }
        }];
      }
      return [];
    }
  };

  const parsed = BulkEngine.parseMessageNode(mockMediaRow, "H", "DD/MM/YYYY");
  assert.equal(parsed.parsed_date, null, "Must be null, never current date");
  assert.equal(parsed.timestamp, null);
  assert.equal(parsed.timestamp_provenance, "unverified");
  assert.equal(parsed.has_media, true);

  // In runBulkCapture, presence of unverified message marks completeness partial
  const mockContainer = {
    scrollTop: 0,
    clientHeight: 200,
    scrollHeight: 200,
    getBoundingClientRect: () => ({ top: 0, bottom: 200 }),
    querySelectorAll: () => [mockMediaRow]
  };

  const res = await BulkEngine.runBulkCapture({
    container: mockContainer,
    doc: { querySelector: () => ({ innerText: "H", getAttribute: () => "H" }) },
    mode: "visible_to_newest",
    maxScrollAttempts: 2,
    scrollDelayMs: 2
  });

  assert.equal(res.completenessStatus, "partial");
  assert.equal(res.partialReason, "unverified_timestamps_present");
  assert.equal(res.messages.length, 1, "Must preserve message for correct identity tracking");
});

test("BulkEngine: Document card detection extracts clean filename from 'Download \"...\"' and treats thumb as clickable download control", () => {
  let clicked = false;
  const mockDocThumb = {
    tagName: "DIV",
    getAttribute: (attr) => {
      if (attr === "data-testid") return "document-thumb";
      if (attr === "title") return 'Download "Project_Specs.docx"';
      return null;
    },
    innerText: "Project_Specs.docx\n2.4 MB • docx",
    textContent: "Project_Specs.docx\n2.4 MB • docx",
    click: () => { clicked = true; },
    querySelectorAll: () => []
  };

  const mockMsgEl = {
    querySelector: () => null,
    querySelectorAll: (sel) => {
      if (sel.includes("document-thumb")) return [mockDocThumb];
      return [];
    }
  };

  const cleanName = BulkEngine.extractDocumentFilename(mockDocThumb);
  assert.equal(cleanName, "Project_Specs.docx", "Must extract clean filename without Download quotes");

  const atts = BulkEngine.detectMessageAttachments(mockMsgEl, "H");
  assert.equal(atts.length, 1);
  assert.equal(atts[0].file_name, "Project_Specs.docx");
  assert.equal(atts[0].file_type, "document");
  assert.equal(atts[0].download_el, mockDocThumb, "The document-thumb div itself must be the download control");

  // Verify Arabic pattern as well
  const mockArabicDoc = {
    tagName: "DIV",
    getAttribute: (attr) => (attr === "title" ? 'تنزيل "تقرير_العمليات.pdf"' : null),
    innerText: "تقرير_العمليات.pdf",
    querySelectorAll: () => []
  };
  assert.equal(BulkEngine.extractDocumentFilename(mockArabicDoc), "تقرير_العمليات.pdf");
});

test("BulkEngine: Voice note without DOM audio src reports truthful unavailable with voice_note_no_dom_src diagnostic", async () => {
  // Live DOM facts: button[aria-label="Play voice message"], slider, no <audio> tag or blob url
  const mockVoicePlayBtn = {
    tagName: "BUTTON",
    getAttribute: (attr) => (attr === "aria-label" ? "Play voice message" : null),
    parentElement: null,
    querySelectorAll: () => []
  };

  const mockVoiceRow = {
    querySelector: () => null,
    querySelectorAll: (sel) => {
      if (sel.includes("voice message") || sel.includes("audio")) {
        return [mockVoicePlayBtn];
      }
      return [];
    }
  };

  const atts = BulkEngine.detectMessageAttachments(mockVoiceRow, "H");
  assert.equal(atts.length, 1);
  const voiceAtt = atts[0];
  assert.equal(voiceAtt.file_type, "audio");
  assert.equal(voiceAtt.attachment_status, "unavailable");
  assert.equal(voiceAtt.diagnostic_reason, "voice_note_no_dom_src");

  // captureAttachmentOriginalBytes returns truthful status without fake bytes
  const captured = await BulkEngine.captureAttachmentOriginalBytes(voiceAtt);
  assert.equal(captured.status, "unavailable");
  assert.equal(captured.reason, "voice_note_no_dom_src");
  assert.equal(captured.bytes, undefined, "Must NEVER fake audio bytes or transcripts");
});

test("BulkEngine: Duplicate filenames across different messages bind to distinct message keys without collision", () => {
  const rowA = {
    getAttribute: (attr) => (attr === "data-id" ? "msg_key_alpha" : null),
    classList: { contains: () => false },
    querySelector: (sel) => {
      if (sel.includes("data-pre-plain-text")) return { getAttribute: () => "[10:00 am, 24/09/2026] H: " };
      return null;
    },
    querySelectorAll: (sel) => {
      if (sel.includes("document-thumb")) {
        return [{
          tagName: "DIV",
          getAttribute: (attr) => (attr === "title" ? 'Download "invoice.pdf"' : null),
          innerText: "invoice.pdf",
          querySelectorAll: () => []
        }];
      }
      return [];
    }
  };

  const rowB = {
    getAttribute: (attr) => (attr === "data-id" ? "msg_key_beta" : null),
    classList: { contains: () => false },
    querySelector: (sel) => {
      if (sel.includes("data-pre-plain-text")) return { getAttribute: () => "[10:05 am, 24/09/2026] H: " };
      return null;
    },
    querySelectorAll: (sel) => {
      if (sel.includes("document-thumb")) {
        return [{
          tagName: "DIV",
          getAttribute: (attr) => (attr === "title" ? 'Download "invoice.pdf"' : null),
          innerText: "invoice.pdf",
          querySelectorAll: () => []
        }];
      }
      return [];
    }
  };

  const parsedA = BulkEngine.parseMessageNode(rowA, "H");
  const parsedB = BulkEngine.parseMessageNode(rowB, "H");

  assert.notEqual(parsedA.key, parsedB.key);
  assert.equal(parsedA.platform_msg_id, "msg_key_alpha");
  assert.equal(parsedB.platform_msg_id, "msg_key_beta");
  assert.equal(parsedA.attachments[0].file_name, "invoice.pdf");
  assert.equal(parsedB.attachments[0].file_name, "invoice.pdf");
});

test("BulkEngine: Date range downward traversal reaching chat bottom finishes complete (not history_exhausted_before_to_bound)", async () => {
  // Scenario: Chat ends on 24/09/2026. User selects toDate 25/09/2026.
  // Downward traversal hits container bottom (isAtBottom && bottomExhaustedCount >= 2).
  // Must finish with completenessStatus "complete" because all messages to chat end were reached.
  let step = 0;
  const mockContainer = {
    scrollTop: 0,
    clientHeight: 200,
    scrollHeight: 200, // At bottom already
    getBoundingClientRect: () => ({ top: 0, bottom: 200 }),
    querySelectorAll: () => {
      step++;
      return [
        {
          getAttribute: (attr) => (attr === "data-id" ? "msg_end_of_chat" : null),
          classList: { contains: () => false },
          getBoundingClientRect: () => ({ top: 10, bottom: 30 }),
          querySelector: () => ({
            innerText: "Final real message in H chat",
            getAttribute: () => "[10:00 am, 24/09/2026] H: "
          })
        }
      ];
    }
  };

  const result = await BulkEngine.runBulkCapture({
    container: mockContainer,
    doc: { querySelector: () => ({ innerText: "H", getAttribute: () => "H" }) },
    mode: "date_range",
    fromDate: "2026-09-24T10:00:00",
    toDate: "2026-09-25T23:59:59", // Future or later than latest real message
    maxScrollAttempts: 5,
    scrollDelayMs: 2
  });

  assert.equal(result.completenessStatus, "complete", "Reaching natural chat bottom must be complete");
  assert.equal(result.partialReason, null);
  assert.equal(result.messages.length, 1);
});

test("BulkEngine: Context menu Download automation acquires genuine download for voice notes and documents", async () => {
  let contextMenuDispatched = false;
  let downloadMenuItemClicked = false;

  // Real WhatsApp Web DOM: <button aria-label="Download" role="menuitem"> under div[role="menu"]
  const mockDownloadMenuItem = {
    tagName: "BUTTON",
    getAttribute: (attr) => {
      if (attr === "aria-label") return "Download";
      if (attr === "role") return "menuitem";
      return null;
    },
    innerText: "Download",
    click: () => { downloadMenuItemClicked = true; }
  };

  const mockVoiceBtn = {
    tagName: "BUTTON",
    getAttribute: (attr) => (attr === "aria-label" ? "Play voice message" : null),
    getBoundingClientRect: () => ({ left: 10, top: 20, width: 40, height: 40 }),
    dispatchEvent: (evt) => {
      if (evt && evt.type === "contextmenu") {
        contextMenuDispatched = true;
      }
    },
    closest: () => null,
    querySelectorAll: () => []
  };

  const mockDoc = {
    querySelectorAll: (sel) => {
      if (contextMenuDispatched && (sel.includes("role='menu'") || sel.includes("button[role='menuitem']") || sel.includes("role='button'"))) {
        return [mockDownloadMenuItem];
      }
      return [];
    }
  };

  const att = {
    id: "att_voice_real",
    file_type: "audio",
    file_name: "voice_note_1.ogg",
    mime_type: "audio/ogg",
    blob_url: null,
    download_el: null,
    container_el: mockVoiceBtn,
    can_context_download: true
  };

  const mockBridgeCalls = [];
  const mockSender = async (p) => {
    mockBridgeCalls.push(p);
    if (p.action === "bridge_arm_download_capture") {
      return { success: true, status: "armed" };
    }
    if (p.action === "bridge_await_download") {
      return {
        success: true,
        downloadPath: "E:\\Users\\DELL\\Downloads\\PTT-20260925-WA0001.ogg",
        fileSize: 88633,
        mime: "audio/ogg"
      };
    }
    return { success: false };
  };

  const res = await BulkEngine.captureAttachmentOriginalBytes(att, {
    bridgeSender: mockSender,
    doc: mockDoc,
    timeoutMs: 1000
  });

  assert.equal(contextMenuDispatched, true, "Must dispatch contextmenu on voice note element");
  assert.equal(downloadMenuItemClicked, true, "Must click Download item in context menu");
  assert.equal(res.status, "saved-original");
  assert.equal(res.download_path, "E:\\Users\\DELL\\Downloads\\PTT-20260925-WA0001.ogg");
  assert.equal(res.file_size, 88633);
});

test("BackgroundBridge: Download capture arming state machine coordinates single-flight downloads and handles completion, timeout, pre-existing, and concurrent downloads", async () => {
  const bridge = BackgroundBridge.handleRuntimeMessage || BackgroundBridge.handleBridgeMessage;
  const validSender = { id: "test_ext_id", url: "chrome-extension://test_ext_id/popup.html" };

  // 1. Calling await download without arming returns NO_ARMED_DOWNLOAD
  let awaitRes1 = null;
  bridge({ action: "bridge_await_download" }, validSender, (r) => { awaitRes1 = r; });
  assert.equal(awaitRes1.success, false);
  assert.equal(awaitRes1.error_code, "NO_ARMED_DOWNLOAD");

  // 2. Setup mock chrome.downloads API
  let onCreatedCb = null;
  let onChangedCb = null;
  const mockDownloadsApi = {
    onCreated: { addListener: (fn) => { onCreatedCb = fn; } },
    onChanged: { addListener: (fn) => { onChangedCb = fn; } },
    search: (query, cb) => {
      cb([{
        id: query.id,
        filename: "E:\\Users\\DELL\\Downloads\\PTT-real.ogg",
        state: "complete",
        fileSize: 88633,
        mime: "audio/ogg"
      }]);
    }
  };
  BackgroundBridge.setupDownloadsListener(mockDownloadsApi);

  // 3. Pre-existing download rejection: an item created before arming time is strictly ignored
  const tArm = Date.now();
  let armRes = null;
  bridge(
    { action: "bridge_arm_download_capture", expectedFilename: "PTT-real.ogg", timeoutMs: 3000 },
    validSender,
    (r) => { armRes = r; }
  );
  assert.equal(armRes.success, true);
  assert.equal(armRes.status, "armed");

  // Fire onCreated with old startTime (pre-existing download from 5 seconds ago)
  onCreatedCb({ id: 50, startTime: new Date(tArm - 5000).toISOString(), filename: "E:\\Users\\DELL\\Downloads\\old.zip" });
  const pending1 = BackgroundBridge.getPendingDownload();
  assert.equal(pending1.downloadId, null, "Pre-existing download must not be adopted as armed download ID");

  // Fire onChanged for that pre-existing item: must NOT complete the armed download
  onChangedCb({ id: 50, state: { current: "complete" } });
  assert.equal(pending1.downloadId, null, "onChanged for pre-existing download must not complete armed capture");

  // 4. Fire onChanged without prior onCreated: must NOT adopt delta.id
  onChangedCb({ id: 999, state: { current: "complete" } });
  assert.equal(pending1.downloadId, null, "onChanged without matching onCreated must not adopt delta.id");

  // 5. Concurrent download conflict: firing a second onCreated while first is in-flight fails safely
  onCreatedCb({ id: 101, startTime: new Date(tArm + 50).toISOString(), filename: "E:\\Users\\DELL\\Downloads\\first.ogg" });
  assert.equal(pending1.downloadId, 101);

  // Second unexpected concurrent download begins
  onCreatedCb({ id: 102, startTime: new Date(tArm + 80).toISOString(), filename: "E:\\Users\\DELL\\Downloads\\second.ogg" });
  assert.equal(pending1.concurrentConflict, true, "Must detect concurrent download conflict");

  let concurrentAwaitRes = await new Promise((resolve) => {
    bridge({ action: "bridge_await_download" }, validSender, resolve);
  });
  assert.equal(concurrentAwaitRes.success, false);
  assert.equal(concurrentAwaitRes.error_code, "CONCURRENT_DOWNLOAD_CONFLICT");

  // 6. Interrupted / cancelled download handling
  bridge(
    { action: "bridge_arm_download_capture", expectedFilename: "PTT-real.ogg", timeoutMs: 3000 },
    validSender,
    () => {}
  );
  const pending2 = BackgroundBridge.getPendingDownload();
  const tArm2 = Date.now();
  onCreatedCb({ id: 201, startTime: new Date(tArm2 + 10).toISOString(), filename: "E:\\Users\\DELL\\Downloads\\cancel.ogg" });
  assert.equal(pending2.downloadId, 201);

  let cancelPromise = new Promise((resolve) => {
    bridge({ action: "bridge_await_download" }, validSender, resolve);
  });
  onChangedCb({ id: 201, state: { current: "interrupted" }, error: { current: "USER_CANCELED" } });

  const cancelRes = await cancelPromise;
  assert.equal(cancelRes.success, false);
  assert.equal(cancelRes.error_code, "DOWNLOAD_INTERRUPTED");

  // 7. Successful single-flight completion
  bridge(
    { action: "bridge_arm_download_capture", expectedFilename: "PTT-real.ogg", timeoutMs: 3000 },
    validSender,
    () => {}
  );
  const pending3 = BackgroundBridge.getPendingDownload();
  const tArm3 = Date.now();
  onCreatedCb({ id: 301, startTime: new Date(tArm3 + 10).toISOString(), filename: "E:\\Users\\DELL\\Downloads\\PTT-real.ogg" });
  assert.equal(pending3.downloadId, 301);

  let successPromise = new Promise((resolve) => {
    bridge({ action: "bridge_await_download" }, validSender, resolve);
  });
  onChangedCb({ id: 301, state: { current: "complete" } });

  const successRes = await successPromise;
  assert.equal(successRes.success, true);
  assert.equal(successRes.downloadPath, "E:\\Users\\DELL\\Downloads\\PTT-real.ogg");
  assert.equal(successRes.fileSize, 88633);
});
