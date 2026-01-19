"""
Transcription orchestrator.

Manages providers and handles transcription requests.
"""

from typing import Optional, Dict, Type
from .providers.base import TranscriptionProvider, TranscriptionResult
from .providers.openai_whisper import OpenAITranscribeProvider
from .providers.gemini import GeminiProvider
from .config import Config
from .keychain import get_configured_providers


class TranscriptionManager:
    """Manages transcription providers and requests."""

    # Registry of available providers
    PROVIDER_CLASSES: Dict[str, Type[TranscriptionProvider]] = {
        "openai": OpenAITranscribeProvider,
        "gemini": GeminiProvider
    }

    def __init__(self):
        self.config = Config.load()
        self._providers: Dict[str, TranscriptionProvider] = {}

    def get_available_providers(self) -> list[dict]:
        """
        Get list of available providers with their configured status.

        Returns:
            List of dicts with provider info and status
        """
        configured = get_configured_providers()

        return [
            {
                "id": "openai",
                "name": "OpenAI",
                "configured": "openai" in configured,
                "models": OpenAITranscribeProvider().get_models()
            },
            {
                "id": "gemini",
                "name": "Google Gemini",
                "configured": "gemini" in configured,
                "models": GeminiProvider().get_models()
            }
        ]

    def get_provider(self, provider_id: str) -> Optional[TranscriptionProvider]:
        """Get or create a provider instance."""
        if provider_id not in self._providers:
            provider_class = self.PROVIDER_CLASSES.get(provider_id)
            if provider_class:
                model = self.config.get_provider_model(provider_id)
                self._providers[provider_id] = provider_class(model=model)

        return self._providers.get(provider_id)

    def set_provider_model(self, provider_id: str, model_id: str) -> None:
        """Update the model for a provider."""
        provider = self.get_provider(provider_id)
        if provider:
            provider.set_model(model_id)
            self.config.set_provider_model(provider_id, model_id)

    def transcribe(
        self,
        audio_bytes: bytes,
        provider_id: Optional[str] = None
    ) -> TranscriptionResult:
        """
        Transcribe audio using specified or default provider.

        Args:
            audio_bytes: WAV audio data
            provider_id: Provider to use (or None for default)

        Returns:
            TranscriptionResult with text and metadata

        Raises:
            ValueError: If provider is not configured
        """
        provider_id = provider_id or self.config.default_provider
        provider = self.get_provider(provider_id)

        if not provider:
            raise ValueError(f"Unknown provider: {provider_id}")

        if not provider.is_configured():
            # Try fallback to the other provider
            other_provider = "gemini" if provider_id == "openai" else "openai"
            other = self.get_provider(other_provider)
            if other and other.is_configured():
                provider = other
                provider_id = other_provider
            else:
                raise ValueError(
                    f"No API key configured. Please add your {provider_id.title()} "
                    f"API key in the settings menu."
                )

        result = provider.transcribe(audio_bytes)

        # Update stats
        self.config.add_transcription_stats(result.cost_estimate)

        return result

    def get_stats(self) -> dict:
        """Get transcription statistics."""
        return {
            "total_transcriptions": self.config.total_transcriptions,
            "total_cost": self.config.total_cost
        }

    def reload_config(self) -> None:
        """Reload configuration from disk."""
        self.config = Config.load()
        # Update provider models
        for provider_id, provider in self._providers.items():
            model = self.config.get_provider_model(provider_id)
            provider.set_model(model)
