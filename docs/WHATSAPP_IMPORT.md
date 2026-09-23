# WhatsApp Import & Ingestion Modes

OWI provides four flexible ingestion modes to convert WhatsApp chats into structured knowledge.

---

## 1. Mode A: WhatsApp Export Import (Primary MVP Mode)

WhatsApp exports can be imported as single `.txt` files or as `.zip` archives containing chat text and media attachments.

### Supported Export Formats
OWI handles variations across operating systems and locales:
- **iOS Format**: `[14/09/2026, 14:32:10] Sender: Message` or `[14/9/26, 2:32:10 PM] Sender: Message`
- **Android Format**: `14/09/2026, 14:32 - Sender: Message` or `14/9/26, 2:32 PM - Sender: Message`
- **Arabic Locales**: Strips Unicode bidirectional marks (`\u200e`, `\u202f`, `\u200f`) and parses Arabic AM/PM markers (`\u0635` / `\u0645`).
- **Multiline Continuations**: Accurately aggregates subsequent lines until the next valid timestamp header.
- **System Messages**: Detects and isolates encryption notices, group creation, member additions, and icon updates.
- **Attachment Association**: Identifies `<Media omitted>`, `photo.jpg (file attached)`, `<attached: audio.opus>`, and links physical files from the ZIP archive to their exact parent messages.

---

## 2. Mode B: Drag and Drop

Users can drag individual or multiple files directly onto the OWI interface:
- **Supported Formats**: Audio (`.opus`, `.mp3`, `.m4a`), Images (`.jpg`, `.png`), Video (`.mp4`), Documents (`.pdf`, `.docx`, `.xlsx`, `.csv`, `.txt`), and `.zip` archives.
- **Processing**: Files can be attached to existing conversations or ingested as standalone workspace assets.

---

## 3. Mode C: Folder Watch / Folder Import

Users can select an explicitly designated local folder (e.g. `Downloads/WhatsApp_Exports`) for automated ingestion:
- **Strict User Consent**: Folder watching must be explicitly started by the user. OWI never scans arbitrary directories or user profile folders silently.
- **Idempotency**: Computes SHA-256 hashes of new files to avoid duplicate reprocessing.

---

## 4. Mode D: WhatsApp Web Companion (Browser Extension)

An optional Manifest V3 browser companion extension designed for user-initiated capturing:
- **User-Initiated**: Captures only when the user clicks "Capture Visible Messages" in the extension popup.
- **No Background Scraping**: Never runs unattended background crawlers and never accesses session tokens, credentials, or authentication cookies.
- **Authenticated Localhost Bridge**: Transmits captured selections to `http://127.0.0.1:8765/api/companion/ingest` protected by the `X-OWI-Token` header.
