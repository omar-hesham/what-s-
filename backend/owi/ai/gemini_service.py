"""
Gemini Multimodal Intelligence Service.
Uses the official google-genai SDK to provide high-accuracy Arabic audio transcription,
document OCR/understanding, and image analysis for user-selected WhatsApp media.
API key is kept strictly local and never exposed to the frontend or extension.
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional, Union
from owi.config import settings
from owi.core.logging import logger

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    logger.warning("google-genai package not found. Cloud multimodal fallback will be disabled.")


class GeminiService:
    """Wrapper around official google-genai Client for multimodal analysis."""

    _client = None

    @classmethod
    def get_client(cls, api_key: Optional[str] = None):
        """Lazy-initialize GenAI client."""
        if not GENAI_AVAILABLE:
            raise RuntimeError("google-genai package is not installed.")

        key = api_key or settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY")
        if not key:
            raise ValueError("GEMINI_API_KEY is not configured in local environment.")

        return genai.Client(api_key=key)

    @classmethod
    def is_configured(cls) -> bool:
        """Check if Gemini service is ready to use."""
        key = settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY")
        return bool(GENAI_AVAILABLE and key and len(key) > 5)

    @classmethod
    def transcribe_audio(
        cls, 
        audio_input: Union[Path, str, bytes], 
        mime_type: str = "audio/ogg",
        prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Transcribe WhatsApp voice notes or audio messages using Gemini.
        Specialized for Arabic (Egyptian dialect, MSA) and mixed English.
        """
        if not cls.is_configured():
            return {
                "success": False,
                "error": "Gemini API key is not configured or google-genai is not available."
            }

        try:
            if isinstance(audio_input, (str, Path)):
                p = Path(audio_input)
                if not p.exists():
                    return {"success": False, "error": f"Audio file not found: {p}"}
                
                suffix = p.suffix.lower()
                if suffix in [".ogg", ".opus"]:
                    mime_type = "audio/ogg"
                elif suffix == ".mp3":
                    mime_type = "audio/mp3"
                elif suffix == ".m4a":
                    mime_type = "audio/mp4"
                elif suffix == ".wav":
                    mime_type = "audio/wav"

                with open(p, "rb") as f:
                    audio_bytes = f.read()
            else:
                audio_bytes = audio_input

            client = cls.get_client()
            default_prompt = (
                "You are an expert audio transcriber specializing in Arabic (especially Egyptian dialect) "
                "and mixed Arabic-English WhatsApp voice notes. "
                "Transcribe this voice message accurately word-for-word. "
                "If there are key tasks, decisions, or commitments mentioned, highlight them briefly at the end. "
                "Provide the transcript in clean Arabic script."
            )
            instruction = prompt or default_prompt

            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                    instruction
                ]
            )

            text_output = response.text or ""
            return {
                "success": True,
                "text": text_output.strip(),
                "model": settings.GEMINI_MODEL,
                "source": "gemini"
            }

        except Exception as e:
            logger.error(f"Gemini audio transcription error: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    @classmethod
    def analyze_image(
        cls, 
        image_input: Union[Path, str, bytes], 
        mime_type: str = "image/jpeg",
        prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze WhatsApp images, screenshots, book layouts, or handwritten documents.
        Performs high-fidelity OCR and entity extraction.
        """
        if not cls.is_configured():
            return {
                "success": False,
                "error": "Gemini API key is not configured or google-genai is not available."
            }

        try:
            if isinstance(image_input, (str, Path)):
                p = Path(image_input)
                if not p.exists():
                    return {"success": False, "error": f"Image file not found: {p}"}
                
                suffix = p.suffix.lower()
                if suffix in [".jpg", ".jpeg"]:
                    mime_type = "image/jpeg"
                elif suffix == ".png":
                    mime_type = "image/png"
                elif suffix == ".webp":
                    mime_type = "image/webp"

                with open(p, "rb") as f:
                    image_bytes = f.read()
            else:
                image_bytes = image_input

            client = cls.get_client()
            default_prompt = (
                "Analyze this image from a WhatsApp conversation. "
                "If it contains text, document pages, book drafts, receipts, or handwritten notes, "
                "perform accurate OCR and extract all readable text verbatim in Arabic/English. "
                "Then provide a concise summary of what this image shows and any key action items or entities."
            )
            instruction = prompt or default_prompt

            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    instruction
                ]
            )

            return {
                "success": True,
                "text": (response.text or "").strip(),
                "model": settings.GEMINI_MODEL,
                "source": "gemini"
            }

        except Exception as e:
            logger.error(f"Gemini image analysis error: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    @classmethod
    def analyze_document(
        cls,
        doc_input: Union[Path, str, bytes],
        mime_type: str = "application/pdf",
        prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze documents (PDF, Word, text files) shared in WhatsApp.
        """
        if not cls.is_configured():
            return {
                "success": False,
                "error": "Gemini API key is not configured or google-genai is not available."
            }

        try:
            if isinstance(doc_input, (str, Path)):
                p = Path(doc_input)
                if not p.exists():
                    return {"success": False, "error": f"Document file not found: {p}"}

                suffix = p.suffix.lower()
                if suffix == ".pdf":
                    mime_type = "application/pdf"
                elif suffix in [".docx", ".doc"]:
                    mime_type = "text/plain"
                elif suffix in [".txt", ".md"]:
                    mime_type = "text/plain"

                with open(p, "rb") as f:
                    doc_bytes = f.read()
            else:
                doc_bytes = doc_input

            client = cls.get_client()
            default_prompt = (
                "Review this document shared in WhatsApp. "
                "Provide a comprehensive structured overview: "
                "1. Summary of contents, 2. Key decisions, 3. Pending tasks or revisions, 4. Important dates/deadlines."
            )
            instruction = prompt or default_prompt

            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(data=doc_bytes, mime_type=mime_type),
                    instruction
                ]
            )

            return {
                "success": True,
                "text": (response.text or "").strip(),
                "model": settings.GEMINI_MODEL,
                "source": "gemini"
            }

        except Exception as e:
            logger.error(f"Gemini document analysis error: {e}")
            return {
                "success": False,
                "error": str(e)
            }
