# OWI System Architecture

## 1. Design Philosophy

Omar WhatsApp Intelligence (OWI) is architected around four core pillars:
1. **Local-First & Privacy Sovereign**: All databases, embeddings, and media assets reside strictly on the user's host filesystem (`data/`).
2. **Zero-Recurring Cost**: Zero mandatory cloud accounts, zero paid API keys, zero per-token fees.
3. **Multi-Modal Traceability**: Every extracted entity (task, property, decision) links directly to its parent conversation, message index, timestamp, and media asset.
4. **Resilience & Graceful Degradation**: If advanced neural dependencies (GPU Whisper, Ollama) are absent, the application gracefully degrades to rule-based NLP, CPU transcription, and lexical search without failing or crashing.

---

## 2. Component Topology

```
+-------------------------------------------------------------------------+
|                           User Interface Layer                          |
|  - React 18 / 19 + TypeScript + Vite                                    |
|  - RTL / LTR layout engine with Cairo & Inter typography                |
|  - Media Players (synchronized audio segment scrubbing, image zoom)     |
+------------------------------------+------------------------------------+
                                     |
                                     | HTTP REST & Static Assets (:8765)
                                     v
+-------------------------------------------------------------------------+
|                            Backend Core Layer                           |
|  - FastAPI ASGI application (Python 3.12)                               |
|  - Security Middleware: Path traversal validation, Zip-Slip guard       |
|  - Background Job Queue: ThreadPoolExecutor with persistent job records |
|  - Logging Engine: Automatic scrubbing of sensitive tokens              |
+-------------------+----------------+-------------------+----------------+
                    |                |                   |
                    v                v                   v
+-----------------------+  +-------------------+  +-----------------------+
|   Ingestion Pipeline  |  |  Knowledge Graph  |  |      AI Providers     |
| - WhatsApp text parser|  | - SQLite WAL mode |  | - Heuristic Rule NLP  |
| - ZIP unpacker        |  | - SQLAlchemy ORM  |  | - Local Whisper (CPU) |
| - Drag & Drop Handler |  | - FTS5 Full-Text  |  | - Tesseract OCR       |
| - Folder Watcher      |  | - Cosine Vectors  |  | - Local FFmpeg        |
| - Companion Bridge    |  | - Stone RealEstate|  | - Pluggable Ollama    |
+-----------------------+  +-------------------+  +-----------------------+
```

---

## 3. Storage Architecture

All persistent data is structured cleanly inside the `data/` folder:
- `data/owi.db`: SQLite database running in Write-Ahead Logging (WAL) mode with foreign keys enabled.
- `data/media/audio/`: Voice notes and extracted audio tracks (`.opus`, `.mp3`, `.wav`).
- `data/media/images/`: Screenshots, property photos, documents (`.jpg`, `.png`).
- `data/media/video/`: Video files (`.mp4`, `.mov`).
- `data/media/documents/`: PDF, DOCX, XLSX, TXT files.
- `data/derived/frames/`: Representative keyframes extracted from video.
- `data/derived/transcripts/`: Cached speech transcriptions.
- `data/logs/owi.log`: Sanitized application logs.
