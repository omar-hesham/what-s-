"""
Runner script for OWI backend server.
"""

import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

import uvicorn
from owi.config import settings

def main():
    print(f"Launching {settings.APP_NAME} backend on http://{settings.HOST}:{settings.PORT} ...")
    uvicorn.run(
        "owi.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info"
    )

if __name__ == "__main__":
    main()
