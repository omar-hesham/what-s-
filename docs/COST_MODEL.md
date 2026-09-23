# OWI Cost Model & External Services Audit

**Omar WhatsApp Intelligence (OWI)** is strictly engineered to have **ZERO mandatory recurring costs**, **ZERO mandatory subscription fees**, and **ZERO paid cloud APIs**.

The system operates 100% on your local Windows PC.

---

## 1. Summary of System Costs

| Metric | Cost | Status |
| :--- | :--- | :--- |
| **Recurring Monthly Software Fee** | **$0.00 / month** | **Guaranteed** |
| **Mandatory Cloud Subscriptions** | **$0.00** | **None** |
| **Mandatory Cloud Storage Fees** | **$0.00** | **None** (100% local disk) |
| **Mandatory AI API Usage (OpenAI, Gemini, Claude)**| **$0.00** | **None** (Offline heuristic/Ollama) |
| **WhatsApp Business API Fee** | **$0.00** | **None** (Standard exports) |
| **Vector Database Hosting Fee** | **$0.00** | **None** (Local SQLite & Cosine Index) |
| **Transcription API Usage** | **$0.00** | **None** (Local Whisper runtime) |
| **Total Mandatory Recurring Cost** | **$0.00** | **100% FREE & OPEN SOURCE** |

---

## 2. Exhaustive Dependency Audit

Every software component used in OWI has been audited for license compliance, local-only execution, and absence of hidden billing or accounts:

| Component / Library | Free / Open Source? | Runs 100% Locally? | Account Required? | Recurring Fee? | Usage Fee? | Optional? | License |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Python** | Yes | Yes | No | $0.00 | $0.00 | Core | PSF License |
| **FastAPI** | Yes | Yes | No | $0.00 | $0.00 | Core | MIT |
| **Uvicorn** | Yes | Yes | No | $0.00 | $0.00 | Core | BSD-3-Clause |
| **SQLite** | Yes | Yes | No | $0.00 | $0.00 | Core | Public Domain |
| **SQLAlchemy** | Yes | Yes | No | $0.00 | $0.00 | Core | MIT |
| **React** | Yes | Yes | No | $0.00 | $0.00 | Core | MIT |
| **TypeScript** | Yes | Yes | No | $0.00 | $0.00 | Core | Apache 2.0 |
| **Vite** | Yes | Yes | No | $0.00 | $0.00 | Core | MIT |
| **Lucide Icons** | Yes | Yes | No | $0.00 | $0.00 | Core | ISC |
| **Pydantic** | Yes | Yes | No | $0.00 | $0.00 | Core | MIT |
| **Pillow (PIL)** | Yes | Yes | No | $0.00 | $0.00 | Core | HPND |
| **pypdf** | Yes | Yes | No | $0.00 | $0.00 | Core | BSD-3-Clause |
| **python-docx** | Yes | Yes | No | $0.00 | $0.00 | Core | MIT |
| **openpyxl** | Yes | Yes | No | $0.00 | $0.00 | Core | MIT |
| **psutil** | Yes | Yes | No | $0.00 | $0.00 | Core | BSD-3-Clause |
| **faster-whisper** / **Whisper** | Yes | Yes | No | $0.00 | $0.00 | Optional | MIT |
| **FFmpeg** | Yes | Yes | No | $0.00 | $0.00 | Optional | LGPL / GPL |
| **Tesseract OCR** | Yes | Yes | No | $0.00 | $0.00 | Optional | Apache 2.0 |
| **Ollama** | Yes | Yes | No | $0.00 | $0.00 | Optional | MIT |
| **Sentence-Transformers** | Yes | Yes | No | $0.00 | $0.00 | Optional | Apache 2.0 |

---

## 3. Commercial & Local Use Assurance

- **Zero Phoning Home**: The backend server does not ping any telemetry servers or license validation endpoints.
- **No Rate Limits or Quotas**: Because intelligence models and indexing algorithms run entirely in-process or on your local hardware, you can process millions of messages without encountering API quota exhaustion.
- **No Surprise Bills**: The application settings UI contains a dedicated **Cost & External Services** tab that continuously monitors and verifies zero external billing.
