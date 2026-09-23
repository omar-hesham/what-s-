# PowerShell Launcher for Omar WhatsApp Intelligence (OWI)
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " Starting Omar WhatsApp Intelligence (OWI)" -ForegroundColor Green
Write-Host " 100% Local-First - Zero Recurring Costs - Privacy-Safe" -ForegroundColor Yellow
Write-Host "========================================================" -ForegroundColor Cyan

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$pythonExe = Join-Path $scriptDir "backend\.venv\Scripts\python.exe"

if (-Not (Test-Path $pythonExe)) {
    Write-Host "[ERROR] Python virtual environment not found at $pythonExe" -ForegroundColor Red
    Exit 1
}

# Check if port 8765 is already open
$activeConnection = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if ($activeConnection) {
    Write-Host "[INFO] OWI service is already active on port 8765." -ForegroundColor Yellow
    Write-Host "[*] Opening browser interface at http://127.0.0.1:8765 ..." -ForegroundColor Green
    Start-Process "http://127.0.0.1:8765"
    Exit 0
}

Write-Host "[1/2] Opening browser interface at http://127.0.0.1:8765 ..." -ForegroundColor Green
Start-Process "http://127.0.0.1:8765"

Write-Host "[2/2] Starting FastAPI server on port 8765 (Ctrl+C to quit) ..." -ForegroundColor Cyan
& $pythonExe "backend\run_backend.py"

