# Omar WhatsApp Intelligence (OWI)

> **Local-First, Privacy-Conscious, Zero-Recurring-Cost Knowledge Engine for WhatsApp Conversations, Voice Notes, Media, and Documents.**

---

## 🌟 Executive Overview

**Omar WhatsApp Intelligence (OWI)** transforms messy WhatsApp exports into a structured, searchable, and actionable knowledge base. It delivers the integrated feeling of:

$$\text{WhatsApp} + \text{Notion} + \text{AI Executive Assistant} + \text{Knowledge Base} + \text{Task Extraction}$$

The system operates **100% locally** on Windows 10 & 11 with **$0 recurring software fees**, **no mandatory cloud subscriptions**, and **no mandatory third-party AI APIs**.

---

## 🏛️ System Architecture

```
                          +----------------------------------------+
                          |         React + TypeScript Desktop     |
                          |      (Vite, Arabic RTL, English LTR)   |
                          +-------------------+--------------------+
                                              | Localhost REST / SSE
                          +-------------------v--------------------+
                          |         FastAPI Local Backend          |
                          |        (Python 3.12, Uvicorn)          |
                          +---------+---------+---------+----------+
                                    |         |         |
                   +----------------+         |         +----------------+
                   |                          |                          |
        +----------v----------+    +----------v----------+    +----------v----------+
        | Ingestion Pipeline  |    | Relational Database |    | Offline AI Engines  |
        | - WhatsApp Parser   |    | - SQLite (WAL mode) |    | - Local Rule NLP    |
        | - ZIP & Media Link  |    | - FTS5 Full-Text    |    | - Local Whisper     |
        | - Drag-and-Drop     |    | - Vector Embeddings |    | - Local OCR         |
        | - Folder Watcher    |    | - Knowledge Graph   |    | - Local FFmpeg      |
        +---------------------+    +---------------------+    +---------------------+
```

---

## ✨ Key Capabilities

### 1. Ingestion Engine
- **WhatsApp Text & Media Exports**: Parses `.txt` exports and full `.zip` archives containing media.
- **Robust Multi-Locale Parsing**: Handles iOS, Android, and Windows formats; 12h/24h timestamps; Arabic locale timestamps with Unicode bidirectional markers (`\u200e`, `\u202f`, `\u0635`, `\u0645`).
- **Media Association**: Automatically links voice notes (`.opus`, `.mp3`), photos (`.jpg`, `.png`), documents (`.pdf`, `.docx`, `.xlsx`), and videos (`.mp4`) with corresponding message records.
- **Idempotent Ingestion**: SHA-256 content deduplication prevents re-importing identical exports.
- **Security Protection**: Built-in defense against **Zip Slip** directory traversal vulnerabilities.

### 2. Voice Note Processing
- **Local Whisper Engine**: Configurable performance profiles (`LIGHT`: Whisper Tiny, `BALANCED`: Whisper Base, `QUALITY`: Whisper Small).
- **Dialect Handling**: Handles Egyptian, Gulf, Modern Standard Arabic, English, and mixed Franco-Arab dialogue.
- **Timed Scrubbing**: Click any transcript segment to seek and play the original audio from that exact second.

### 3. Knowledge Model & Task Extraction
- **AI Task Inbox**: Automatically discovers tasks and action items with confidence scores. Review, Accept, Edit, or Dismiss items before committing them to your active board.
- **Timestamp-Anchored Relative Dates**: Never mistakes computer current date for message context. "Tomorrow" in a message sent on 14 Sept resolves to 15 Sept.
- **Waiting-For Tracker**: Dedicated pipeline tracking deliverables you are waiting for from contacts.
- **Decisions & Commitments**: Isolates agreed choices ("we decided on 250k EGP") and personal pledges.

### 4. Domain Templates
- **Property Stone Mode (Real Estate)**: Automatically detects property type, area in sqm, price, currency, administrative license, finishing level, and generates clean listing drafts backed by conversational evidence.
- **Research Mode**: Tracks academic topics, hypotheses, citations, findings, and follow-ups.

### 5. Grounded Conversational Search ("Ask Your WhatsApp")
- Conversational RAG grounded strictly in your local database.
- Every assertion links to the **exact local source** (sender, date, message excerpt, media asset).
- Zero hallucination guarantee when data is not in local records.

### 6. Zero-Surprise Cost Screen
- Real-time audit dashboard showing **Core Mode: Local**, **Mandatory Subscriptions: None**, and **Recurring Software Fee: $0.00**.

---

## 🚀 Quick Start on Windows

### One-Click Launch
Double-click `run_owi.bat` or run:
```powershell
.\start_owi.ps1
```
This automatically starts the backend server and opens `http://127.0.0.1:8765` in your default browser.

### Developer Setup
1. **Backend**:
   ```bash
   cd backend
   uv venv .venv --python 3.12
   .venv\Scripts\activate
   uv pip install -r requirements.txt
   uv pip install -e .
   python run_backend.py
   ```
2. **Frontend**:
   ```bash
   cd frontend
   npm install
   npm run build
   # Or for development: npm run dev
   ```
3. **Run Automated Tests**:
   ```bash
   pytest tests -v
   ```

---

## 📚 Detailed Documentation

- [v2.0 Implementation Specification](docs/SPECIFICATION_V2.md)
- [Implementation Status (Phases 0–7)](docs/implementation-status.md)
- [Architectural Decisions (ADR)](docs/decisions.md)
- [Compatibility & Environment Matrix](docs/compatibility.md)
- [Formal Acceptance Report](docs/acceptance-report.md)
- [Architecture Guide](docs/ARCHITECTURE.md)
- [Installation Guide](docs/INSTALLATION.md)
- [Development Guide](docs/DEVELOPMENT.md)
- [Data Model & Schema](docs/DATA_MODEL.md)
- [AI Pipeline & Audio Scrubbing](docs/AI_PIPELINE.md)
- [WhatsApp Import & Parser Specs](docs/WHATSAPP_IMPORT.md)
- [Security & Loopback Protection](docs/SECURITY.md)
- [Privacy & Data Ownership](docs/PRIVACY.md)
- [Zero-Surprise Cost Model & Audit ($0.00)](docs/COST_MODEL.md)
- [Testing & Quality Assurance](docs/TESTING.md)
- [Troubleshooting & Windows Tips](docs/TROUBLESHOOTING.md)
- [Future Roadmap](docs/ROADMAP.md)

---

## 📄 License
MIT License. 100% Free and Open Source.
