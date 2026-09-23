"""
Model Management & Performance Profiles API routes.
"""

from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel
from owi.config import settings
from owi.ai.provider import ai_registry
from owi.core.logging import logger

router = APIRouter(prefix="/api/models", tags=["Model Manager"])

class ProfileUpdate(BaseModel):
    profile: str  # LIGHT, BALANCED, QUALITY

class ModelSwitch(BaseModel):
    llm_provider: Optional[str] = None  # heuristic, ollama
    whisper_model: Optional[str] = None  # tiny, base, small, medium

RECOMMENDED_MODELS = [
    {
        "name": "Whisper Base (Fast & Multilingual)",
        "type": "transcription",
        "size_mb": 145,
        "ram_needed_gb": 1.0,
        "languages": ["ar", "en", "mixed"],
        "cpu_supported": True,
        "status": "ready"
    },
    {
        "name": "Whisper Small (High Accuracy Arabic)",
        "type": "transcription",
        "size_mb": 460,
        "ram_needed_gb": 2.0,
        "languages": ["ar", "en", "mixed"],
        "cpu_supported": True,
        "status": "available"
    },
    {
        "name": "Heuristic Rule-Engine (Zero Download)",
        "type": "llm",
        "size_mb": 0,
        "ram_needed_gb": 0.1,
        "languages": ["ar", "en", "mixed"],
        "cpu_supported": True,
        "status": "ready"
    },
    {
        "name": "Ollama / Local GGUF (Mistral/Qwen)",
        "type": "llm",
        "size_mb": 4100,
        "ram_needed_gb": 6.0,
        "languages": ["ar", "en"],
        "cpu_supported": True,
        "status": "optional"
    }
]

@router.get("/status")
def get_model_status():
    """Current performance profile and active model configuration."""
    return {
        "performance_profile": settings.PERFORMANCE_PROFILE,
        "active_llm": ai_registry.active_llm_name,
        "active_whisper": settings.WHISPER_MODEL,
        "embedding_model": settings.EMBEDDING_MODEL,
        "recommended_models": RECOMMENDED_MODELS
    }

@router.post("/profile")
def set_performance_profile(update: ProfileUpdate):
    """Update active performance profile (LIGHT, BALANCED, QUALITY)."""
    p = update.profile.upper()
    if p not in ("LIGHT", "BALANCED", "QUALITY"):
        raise HTTPException(status_code=400, detail="Invalid profile. Choose LIGHT, BALANCED, or QUALITY.")
    
    settings.PERFORMANCE_PROFILE = p
    if p == "LIGHT":
        settings.WHISPER_MODEL = "tiny"
        ai_registry.set_llm("heuristic")
    elif p == "BALANCED":
        settings.WHISPER_MODEL = "base"
        ai_registry.set_llm("heuristic")
    elif p == "QUALITY":
        settings.WHISPER_MODEL = "small"

    return {
        "status": "updated",
        "new_profile": settings.PERFORMANCE_PROFILE,
        "whisper_model": settings.WHISPER_MODEL,
        "llm_provider": ai_registry.active_llm_name
    }

@router.post("/switch")
def switch_models(switch: ModelSwitch):
    """Switch active LLM or transcription model."""
    if switch.llm_provider:
        ai_registry.set_llm(switch.llm_provider)
    if switch.whisper_model:
        settings.WHISPER_MODEL = switch.whisper_model

    return {
        "status": "switched",
        "active_llm": ai_registry.active_llm_name,
        "active_whisper": settings.WHISPER_MODEL
    }
