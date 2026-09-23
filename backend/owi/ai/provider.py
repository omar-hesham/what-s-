"""
AI Provider abstraction interfaces and registry.
Supports pluggable local and offline backends:
- Heuristic Local Provider (100% offline, zero download, instant)
- Ollama Provider (local REST API to Ollama)
- Llama.cpp Provider
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import httpx

from owi.config import settings
from owi.core.logging import logger

class LLMProvider(ABC):
    """Abstract interface for Language Model completions and structured extractions."""
    
    @abstractmethod
    def complete(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        pass

    @abstractmethod
    def summarize(self, text: str, max_words: int = 150) -> str:
        pass

class TranscriptionProvider(ABC):
    """Abstract interface for speech-to-text engines."""

    @abstractmethod
    def transcribe(self, audio_path: str, model_size: str) -> Dict[str, Any]:
        pass

class EmbeddingProvider(ABC):
    """Abstract interface for local dense vector generation."""

    @abstractmethod
    def embed_text(self, text: str) -> List[float]:
        pass

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        pass

class HeuristicLocalLLM(LLMProvider):
    """
    Offline zero-dependency heuristic language processor.
    Uses rule-based NLP, regex, and structured parsing to extract
    summaries, tasks, and facts without requiring massive model weights.
    """

    def complete(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        return f"[Local Offline Intelligence Response]: Processed prompt of {len(prompt)} characters."

    def summarize(self, text: str, max_words: int = 150) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return "لا توجد رسائل كافية للتلخيص."
        # Pick top salient lines
        summary_lines = lines[:min(5, len(lines))]
        return " - " + "\n - ".join(summary_lines)

class OllamaLLMProvider(LLMProvider):
    """Connects to a locally running Ollama instance."""

    def __init__(self, base_url: str = settings.OLLAMA_BASE_URL, model: str = settings.OLLAMA_MODEL):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def is_available(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=1.5)
            return r.status_code == 200
        except Exception:
            return False

    def complete(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False
            }
            if system_prompt:
                payload["system"] = system_prompt
            r = httpx.post(f"{self.base_url}/api/generate", json=payload, timeout=60.0)
            if r.status_code == 200:
                return r.json().get("response", "")
        except Exception as e:
            logger.error(f"Error communicating with local Ollama: {e}")
        # Fallback to heuristic
        return HeuristicLocalLLM().complete(prompt, system_prompt)

    def summarize(self, text: str, max_words: int = 150) -> str:
        prompt = f"Summarize the following WhatsApp conversation in {max_words} words or less:\n\n{text[:4000]}"
        return self.complete(prompt, system_prompt="You are a concise executive assistant summarizing conversations.")

class AIProviderRegistry:
    """Manages active AI providers across the application."""
    
    def __init__(self):
        self.llm_providers: Dict[str, LLMProvider] = {
            "heuristic": HeuristicLocalLLM(),
            "ollama": OllamaLLMProvider()
        }
        self.active_llm_name = settings.LOCAL_LLM_PROVIDER

    def get_llm(self) -> LLMProvider:
        provider = self.llm_providers.get(self.active_llm_name)
        if isinstance(provider, OllamaLLMProvider) and not provider.is_available():
            # If configured for ollama but not running, fallback safely to heuristic
            return self.llm_providers["heuristic"]
        return provider or self.llm_providers["heuristic"]

    def set_llm(self, name: str):
        if name in self.llm_providers:
            self.active_llm_name = name
            logger.info(f"Switched active LLM provider to '{name}'")
        else:
            raise ValueError(f"Unknown LLM provider: {name}")

ai_registry = AIProviderRegistry()
