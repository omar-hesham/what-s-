# OWI Security Specifications & Hardening

Omar WhatsApp Intelligence (OWI) processes potentially untrusted external archives and files. Robust local security controls are enforced throughout the codebase.

---

## 1. Zip-Slip Vulnerability Prevention

Exported ZIP archives may contain maliciously crafted member filenames attempting directory traversal (e.g. `../../../../Windows/System32/evil.bat`).

### Mitigation
In `owi/core/security.py`, `safe_extract_zip()` validates every archive member before extraction:
```python
def is_safe_path(base_dir: Path, target_path: Path) -> bool:
    resolved_base = base_dir.resolve()
    resolved_target = target_path.resolve()
    return resolved_base in resolved_target.parents or resolved_base == resolved_target
```
Any entry that resolves outside the designated extraction directory is rejected and logged as a security alert.

---

## 2. Filename Sanitization

Uploaded or extracted attachment filenames are sanitized via `sanitize_filename()`:
- Null bytes (`\x00`) and control characters are stripped.
- Directory separators (`/`, `\`), traversal sequences (`..`), and shell metacharacters (`;`, `|`, `&`, `$`, `>`, `<`) are removed or replaced with underscores.
- Valid Arabic, Latin, and numeric characters are preserved.

---

## 3. Localhost Bridge Authentication

The WhatsApp Web Companion communicates with the backend via HTTP. To protect against malicious third-party web pages sending unsolicited requests to `localhost:8765`, the `/api/companion/*` endpoints require the `X-OWI-Token` header. Requests lacking this token are rejected with `401 Unauthorized`.

---

## 4. Unsafe Execution Prevention
- **No Attachment Execution**: OWI treats attachments purely as static binary or text assets. It never executes `.exe`, `.bat`, or `.vbs` files.
- **No Office Macros**: Word and Excel extraction (`python-docx`, `openpyxl`) reads data cells and text paragraphs only; macros and VBA scripts are never executed.

---

## 5. SQL Injection & Database Safety
All database interactions use SQLAlchemy ORM or parameterized queries (`:param`). Raw string concatenation in SQL statements is strictly avoided.

---

## 6. DNS Rebinding & Cross-Origin Protection

To protect the local loopback server (`127.0.0.1:8765`) from DNS rebinding attacks (where a malicious website tricks a user's browser into querying local services under an external domain name):
- `LocalHostHeaderMiddleware` inspects the HTTP `Host` header, allowing only `127.0.0.1` and `localhost` (with optional port). All other Host headers are rejected with `403 Forbidden`.
- State-changing HTTP methods (`POST`, `PUT`, `DELETE`) inspect the `Origin` header and reject external origins.
- Wildcard CORS is prohibited; CORS is strictly confined to local loopback origins.

---

## 7. Local Session Management & Bootstrap Token Flow

- The Windows launcher generates an ephemeral single-use bootstrap secret provided via URL fragment (`#bootstrap=...`).
- The frontend exchanges this token via `POST /api/auth/exchange` for an `HttpOnly`, `SameSite=Strict` session cookie (`owi_session`).
- Replay attempts using the same bootstrap token fail with `401 Unauthorized`.
- Ephemeral tokens expire in 10 minutes; session cookies expire in 24 hours.

---

## 8. Spreadsheet Formula Injection (CSV Injection / CWE-1236)

WhatsApp chat messages, sender names, and property titles might contain text starting with formula operators (`=`, `+`, `-`, `@`, `\t`, `\r`).
- All CSV exports route text fields through `sanitize_csv_cell()`, which prepends a single quote (`'`) to any dangerous leading characters.
- CSV files include a UTF-8 Byte Order Mark (`\ufeff`) ensuring Microsoft Excel on Windows parses Arabic RTL and English LTR without character corruption.

---

## 9. Atomic SQLite Backup & Cryptographic Manifest

- Backups utilize SQLite's native `sqlite3.Connection.backup()` API, checkpointing and flushing WAL state cleanly without locks or corruption.
- Every backup archive includes a `manifest.json` containing schema versions and SHA-256 hashes of the database snapshot and all included media assets.
- Restore operations validate hashes in a temporary staging directory before replacing any active dataset.

