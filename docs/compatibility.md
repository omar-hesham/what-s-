# Omar WhatsApp Intelligence (OWI) — Compatibility & Environment Matrix

**Document Version**: 2.0  
**Date**: 23 September 2026  

---

## 1. Verified Target Environment

| Component | Tested & Verified Specification | Supported Minimum |
|---|---|---|
| **Operating System** | Windows 11 Pro 64-bit (Build 22631+) | Windows 10 x64 (Build 19041+) |
| **Architecture** | x86_64 (AMD64) | x86_64 |
| **Python Runtime** | CPython 3.12.13 (via `uv`) | Python 3.10.x - 3.12.x |
| **Frontend Runtime** | Node.js v20+ / Vite 5.x / React 19.x | Modern Chromium/Edge/Firefox |
| **Database** | SQLite 3.45+ (bundled with Python) with WAL & FTS5 | SQLite 3.35+ |

---

## 2. Tested Python Packages & Dependencies

The backend environment is managed in `backend/.venv` with exact locked wheels:

| Package | Version Tested | Purpose |
|---|---|---|
| `fastapi` | 0.115.8 | High-performance asynchronous REST API server |
| `uvicorn` | 0.34.0 | ASGI web server (bound to loopback `127.0.0.1`) |
| `sqlalchemy` | 2.0.38 | Relational ORM & SQLite WAL engine |
| `pydantic` | 2.10.6 | Data validation & schema serialization |
| `pydantic-settings` | 2.7.1 | Environment and local configuration |
| `psutil` | 7.0.0 | Hardware resource detection (CPU, RAM) |
| `pillow` | 11.1.0 | Image dimension inspection and preprocessing |
| `pypdf` | 5.3.0 | PDF document text and metadata extraction |
| `python-docx` | 1.1.2 | Word document (.docx) parsing |
| `openpyxl` | 3.1.5 | Excel spreadsheet (.xlsx) data extraction |
| `pytest` | 9.1.1 | Automated testing framework (36/36 tests passing) |
| `pytest-asyncio` | 1.4.0 | Async test runners |

---

## 3. External Tooling & Hardware Accelerators

| Tool / Provider | Detected Location / State | Fallback Policy |
|---|---|---|
| **FFmpeg** | `C:\AI-Tools\bin\ffmpeg.exe` (v7.x) | Detected automatically; if absent, video audio extraction is cleanly disabled with user notice |
| **Tesseract OCR** | `tesseract` CLI with `ara+eng` traineddata | Detected automatically; if absent, OCR is flagged as unavailable in capability screen |
| **faster-whisper** | Optional local engine (CPU INT8 / CUDA) | Built-in regex/heuristic NLP fallback if weights not downloaded |
| **Sentence-Transformers** | 384-dimensional cosine vector similarity | Full-text FTS5 BM25 search remains 100% functional without models |
| **Local LLM** | Ollama loopback (`http://127.0.0.1:11434`) | Conservative rule-based suggestion engine operates out-of-the-box |

---

## 4. Hardware Resource Profiles

OWI inspects available RAM on startup and configures worker limits accordingly:

- **LIGHT Profile** (< 8 GB RAM):
  - Concurrency: 1 worker
  - Whisper model candidate: `tiny` or `base` (INT8)
  - VAD filtering: Aggressive (drops silence to conserve RAM)
- **BALANCED Profile** (8 GB - 16 GB RAM):
  - Concurrency: 2 workers
  - Whisper model candidate: `small` (INT8)
  - Batch size: 16
- **QUALITY Profile** (> 16 GB RAM):
  - Concurrency: 2 workers
  - Whisper model candidate: `medium` (INT8 or FP16 on GPU)
  - High-precision OCR and multilingual embeddings
