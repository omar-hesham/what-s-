"""
Application configuration for Omar WhatsApp Intelligence (OWI).
All configuration defaults to local-first, zero-cost, and privacy-conscious settings.
"""

import os
from pathlib import Path
from typing import Literal, Optional
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = BASE_DIR.parent
DEFAULT_DATA_DIR = WORKSPACE_DIR / "data"

# Automatically load local .env from workspace or backend directory
load_dotenv(WORKSPACE_DIR / ".env")
load_dotenv(BASE_DIR / ".env")

class Settings(BaseSettings):
    # Application identity
    APP_NAME: str = "Omar WhatsApp Intelligence"
    APP_SHORT_NAME: str = "OWI"
    APP_VERSION: str = "1.0.0"
    
    # Environment & Host
    DEBUG: bool = False
    HOST: str = "127.0.0.1"
    PORT: int = 8765
    
    # Storage
    DATA_DIR: Path = DEFAULT_DATA_DIR
    
    # Zero-Surprise Cost & External Services Settings
    # STRICTLY ZERO RECURRING COST BY DEFAULT
    CORE_MODE: str = "Local"
    MANDATORY_SUBSCRIPTION: str = "None"
    MANDATORY_API: str = "None"
    RECURRING_SOFTWARE_FEE: str = "None ($0.00)"
    CLOUD_AI_ENABLED: bool = False
    CLOUD_STORAGE_ENABLED: bool = False

    # Gemini Multimodal API Configuration (Optional BYOK, stored strictly in local .env)
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_ENABLED: bool = bool(os.getenv("GEMINI_API_KEY"))
    
    # Companion Security
    COMPANION_SECRET_KEY: str = "owi-companion-local-bridge-key-2026"
    
    # Performance Profiles: LIGHT, BALANCED, QUALITY
    PERFORMANCE_PROFILE: Literal["LIGHT", "BALANCED", "QUALITY"] = "BALANCED"
    
    # Active Models Configuration (Local by default)
    WHISPER_MODEL: str = "base"  # Fast: tiny, Balanced: base/small, Quality: medium
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    LOCAL_LLM_PROVIDER: str = "heuristic"  # heuristic, ollama, llama_cpp
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "mistral"
    
    # Language Defaults
    DEFAULT_LANGUAGE: str = "ar"  # 'ar' (Arabic) or 'en' (English)
    
    class Config:
        env_prefix = "OWI_"
        arbitrary_types_allowed = True

    def init_directories(self):
        """Create necessary subdirectories if they do not exist."""
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "media" / "audio").mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "media" / "images").mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "media" / "video").mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "media" / "documents").mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "media" / "archives").mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "derived" / "frames").mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "derived" / "transcripts").mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "models").mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)

    @property
    def DATABASE_PATH(self) -> Path:
        return self.DATA_DIR / "owi.db"

    @property
    def DATABASE_URL(self) -> str:
        # SQLite URL with forward slashes for Windows compatibility
        db_path = str(self.DATABASE_PATH.as_posix())
        return f"sqlite:///{db_path}"

settings = Settings()
settings.init_directories()
