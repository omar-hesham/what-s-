# Omar WhatsApp Intelligence (OWI) — Architectural Decisions (ADR)

**Document Version**: 2.0  
**Date**: 23 September 2026  

This document records the architectural choices, alternatives considered, and rationale for Omar WhatsApp Intelligence (OWI).

---

## ADR 001: SQLite with WAL Mode as Authoritative Source

### Status
Accepted

### Context
OWI requires an embedded, high-performance, zero-maintenance datastore that operates 100% locally on Windows without requiring separate database server processes (e.g., PostgreSQL, MySQL).

### Decision
Use SQLite with SQLAlchemy ORM, configured with:
- `PRAGMA journal_mode=WAL` (Write-Ahead Logging for non-blocking concurrent reads during background worker writes)
- `PRAGMA foreign_keys=ON` (enforced relational integrity and cascading deletes)
- `PRAGMA synchronous=NORMAL`
- `PRAGMA busy_timeout=15000` (bounded 15-second wait on lock contention)

### Consequences
- Eliminates any external database dependencies or ports.
- Reads do not block writes, and writes do not block reads.
- Authoritative state is kept in `owi.db`. All search indexes, embeddings, and NLP extractions are treated as disposable derivatives.

---

## ADR 002: Localhost Loopback Boundary, DNS Rebinding Mitigation, and Session Cookies

### Status
Accepted

### Context
Section 16 of the specification requires local boundary isolation. Simply binding to `127.0.0.1` is insufficient if a malicious website in the user's browser attempts DNS rebinding or cross-origin requests.

### Decision
1. Application binds strictly to `127.0.0.1`.
2. `LocalHostHeaderMiddleware` inspects the HTTP `Host` header, allowing only `127.0.0.1` and `localhost` (with optional port). External hostnames are rejected with HTTP 403 Forbidden.
3. Cross-origin requests from foreign `Origin` domains are rejected on state-changing endpoints.
4. Launcher supplies an ephemeral single-use bootstrap secret via URL fragment (`#bootstrap=...`), which the frontend immediately exchanges via `POST /api/auth/exchange` for an `HttpOnly`, `SameSite=Strict` session cookie (`owi_session`).
5. A secondary header token (`X-OWI-Token`) is reserved strictly for paired browser extensions.

### Consequences
- Prevents drive-by web attacks and DNS rebinding exploits from extracting local WhatsApp chat data.
- Wildcard CORS is prohibited.

---

## ADR 003: In-Process Durable Job Queue with Crash Recovery

### Status
Accepted

### Context
Heavy operations (transcription, OCR, document chunking, media indexing) must not freeze FastAPI HTTP handlers. However, running Redis + Celery requires external services that violate the zero-overhead Windows desktop contract.

### Decision
Implement `JobQueue` backed by SQLite `jobs` table with a managed `ThreadPoolExecutor`:
- Worker leases are tracked with `lease_expires_at` (15-minute lease duration).
- On application startup, `job_queue.reclaim_orphaned_jobs()` automatically identifies any jobs left in `processing` state from a prior crashed process and resolves them to `failed` with a clear diagnostic explanation.
- Supports user-initiated cancellation via `job_queue.cancel(job_id)`.

### Consequences
- Zero external broker dependencies.
- Survives sudden process termination or system reboot without corrupting state.

---

## ADR 004: Native SQLite WAL-Aware Backup API

### Status
Accepted

### Context
Simply copying an active `owi.db` file while SQLite is running in WAL mode causes database corruption or missed recent writes stored in `owi.db-wal`.

### Decision
Implement `owi/db/backup.py` using Python's native `sqlite3.Connection.backup()` API:
- Flushes and checkpoints all active WAL pages into a standalone snapshot database.
- Collects immutable `data/sources/` and `data/media/` assets.
- Computes SHA-256 hashes and creates a cryptographic `manifest.json`.
- Restores only after staging validation confirms 100% hash integrity.

### Consequences
- Guaranteed zero-corruption backups even under active read/write operations.
- Staged restore prevents partial overwrites.

---

## ADR 005: Spreadsheet Formula Injection (CSV Injection) Mitigation

### Status
Accepted

### Context
WhatsApp messages and contact names may contain adversarial or accidental text starting with characters like `=`, `+`, `-`, or `@`. Opening an unescaped CSV export in Microsoft Excel can trigger formula execution or Dynamic Data Exchange (DDE).

### Decision
Implement `sanitize_csv_cell()` in `owi/core/security.py`:
- Any string cell whose leading character is `=`, `+`, `-`, `@`, `\t`, or `\r` is prepended with a single quote `'`.
- CSV exports write a UTF-8 Byte Order Mark (`\ufeff`) so Excel on Windows properly displays Arabic and English text without encoding corruption.

### Consequences
- Eliminates CWE-1236 (Improper Neutralization of Formula Elements in a CSV File).
- Preserves readability and Excel compatibility for bilingual Arabic/English data.

---

## ADR 006: Message-Timestamp Anchored Relative Date Resolution

### Status
Accepted

### Context
Resolving phrases like "بكرة" (tomorrow) or "الأسبوع الجاي" (next week) against the current computer system clock leads to incorrect historical task deadlines when importing older WhatsApp archives.

### Decision
Relative dates are strictly calculated relative to the parsed source message's timestamp (`msg.timestamp`), never `datetime.utcnow()`. Ambiguous expressions ("قريباً", "فيما بعد") are flagged as uncertain and require human review.

### Consequences
- Accurate deadlines for historical imports.
- No invented or hallucinated dates.
