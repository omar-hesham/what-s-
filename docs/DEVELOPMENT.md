# OWI Developer Guide

This guide describes how to run and contribute to Omar WhatsApp Intelligence in development mode.

---

## 1. Environment Setup

### Backend Setup
```powershell
cd backend
# Create Python 3.12 virtual environment
uv venv .venv --python 3.12

# Activate virtual environment
.\.venv\Scripts\activate

# Install dependencies and editable package
uv pip install -r requirements.txt
uv pip install -e .

# Run development server with live reload
python run_backend.py
```
The FastAPI Swagger documentation is available at `http://127.0.0.1:8765/docs`.

### Frontend Setup
```powershell
cd frontend
# Install npm packages
npm install

# Start Vite dev server
npm run dev

# Build production bundle into frontend/dist
npm run build
```

---

## 2. Running Automated Tests

Run the complete test suite:
```powershell
.\backend\.venv\Scripts\pytest.exe tests -v
```

To run a specific test suite:
```powershell
.\backend\.venv\Scripts\pytest.exe tests\test_acceptance_100_msgs.py -v
```
