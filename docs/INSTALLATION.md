# OWI Installation & Setup Guide (Windows 10 & 11)

OWI is engineered for easy installation and everyday use on Windows PCs without requiring Docker, cloud accounts, or complex developer environments.

---

## 1. Prerequisites

- **Operating System**: Windows 10 (64-bit) or Windows 11.
- **Python**: Version 3.10 to 3.12 (Python 3.12 recommended).
- **RAM**: Minimum 4 GB RAM (8 GB or 16 GB recommended for Quality models).
- **Disk Space**: ~500 MB for core installation + storage for your media.

### Optional Performance Enhancements
- **FFmpeg**: Required for deep video processing and keyframe extraction (automatically detected if installed or on PATH).
- **Tesseract OCR**: Optional for optical character recognition on scanned images (`ara+eng`).
- **Ollama**: Optional if you wish to run local offline LLMs (e.g. `ollama run mistral`).

---

## 2. Windows Quick-Start

1. **Download / Clone OWI**:
   Place the project files into a folder of your choice (e.g. `C:\OWI` or `I:\whats`).

2. **One-Click Launch**:
   Double-click `run_owi.bat` or open PowerShell and execute:
   ```powershell
   .\start_owi.ps1
   ```
   The backend will start and your default web browser will open `http://127.0.0.1:8765`.

3. **First-Run Onboarding Wizard**:
   The first-run setup wizard will guide you through:
   - Selecting interface language (Arabic or English)
   - Checking hardware resources
   - Setting your performance profile (Light, Balanced, Quality)
   - Importing your first WhatsApp chat export!
