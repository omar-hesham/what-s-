# OWI Product Roadmap

The planned enhancements for future versions of Omar WhatsApp Intelligence remain strictly adherent to the **local-first, privacy-sovereign, zero-recurring-cost** principle.

---

## Phase 1: MVP Core (Delivered ✅)
- Multi-format WhatsApp export parsing (.txt and .zip with media)
- Local SQLite relational database with WAL mode and FTS5 full-text search
- Local Whisper speech transcription with synchronized audio segment scrubbing
- In-process background task queue with retry capabilities
- AI Task Inbox with human-in-the-loop review (Accept, Dismiss, Edit)
- Waiting-For pending deliverables tracker
- Property Stone Mode (Real Estate extraction & verified listing drafts)
- Grounded conversational search ("Ask Your WhatsApp") with strict local citations
- Zero-Surprise Cost Screen audit ($0.00 recurring fees)
- Arabic RTL & English LTR responsive desktop interface
- 27 automated tests passing in 2.5 seconds

---

## Phase 2: Enhanced Local Capabilities
- **Tauri Native Windows Wrapper**: Direct `.msi` / `.exe` installer bundling WebView2 and backend into a single double-clickable native desktop app.
- **Local Speaker Diarization**: Multi-speaker clustering on local CPU to label multiple speakers within a single voice note.
- **Audio Speed Controls**: 1.25x, 1.5x, 2.0x playback controls for long voice messages.
- **Advanced Exporting**: One-click export of structured project briefings and task lists directly to local Markdown, Notion-compatible CSV, or Obsidian vaults.

---

## Phase 3: Domain Extensions
- **Medical / Clinical Mode**: Domain template for tracking patient consultations, lab reports, and medication dosages.
- **Legal & Contract Mode**: Deep clause extraction, expiration date tracking, and dispute analysis.
