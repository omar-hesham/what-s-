# OWI Troubleshooting Guide for Windows

This guide covers common questions and diagnostic solutions when running OWI on Windows 10 & 11.

---

## 1. Port 8765 Conflict

**Issue**: The backend reports that port 8765 is already in use (`OSError: [WinError 10048]`).

**Solution**:
1. Open PowerShell and find the process using port 8765:
   ```powershell
   Get-Process -Id (Get-NetTCPConnection -LocalPort 8765).OwningProcess
   ```
2. Or change the port in `backend/owi/config.py` by setting `PORT = 8766` or setting the environment variable `$env:OWI_PORT=8766`.

---

## 2. Arabic Characters Displaying Inverted or Corrupted in Old Consoles

**Issue**: In older Windows cmd prompts, Arabic text in logs may appear backwards or as question marks.

**Solution**:
1. Run `chcp 65001` before executing scripts to switch the console to UTF-8 code page.
2. In the OWI browser application (`http://127.0.0.1:8765`), Arabic text is natively rendered with Cairo font and full bidirectional Unicode support.

---

## 3. Large ZIP Export Imports Taking Time

**Issue**: An export with 5,000+ messages and hundreds of media files takes several minutes to analyze.

**Solution**:
1. The initial import unpacks and links files safely in the background without freezing the UI.
2. In `Settings -> Model Manager`, select the **LIGHT** profile to prioritize ultra-fast indexing.

---

## 4. Exporting Diagnostic Logs

If you encounter an unexpected error, go to **Settings / Storage Dashboard -> Diagnostics** or check:
```
data\logs\owi.log
```
OWI automatically redacts any sensitive tokens, passwords, or personal credentials from log files.
