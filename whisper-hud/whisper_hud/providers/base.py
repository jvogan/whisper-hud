"""
Abstract base class for transcription providers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Callable


@dataclass
class TranscriptionResult:
    """Result from a transcription request."""
    text: str
    duration_seconds: float
    cost_estimate: float  # in USD
    provider: str
    model: str
    language: Optional[str] = None


class TranscriptionProvider(ABC):
    """Base class for all transcription providers."""

    name: str = "base"
    display_name: str = "Base Provider"

    @abstractmethod
    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        """
        Transcribe audio to text.

        Args:
            audio_bytes: WAV file contents

        Returns:
            TranscriptionResult with text and metadata
        """
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if API key is set and valid."""
        pass

    @abstractmethod
    def get_models(self) -> list[dict]:
        """
        Return available models for this provider.

        Returns:
            List of dicts with 'id', 'name', 'description', 'cost_per_minute'
        """
        pass

    @abstractmethod
    def set_model(self, model_id: str) -> None:
        """Set the active model."""
        pass

    @abstractmethod
    def get_current_model(self) -> str:
        """Get the current model ID."""
        pass

    def supports_streaming(self) -> bool:
        """Check if this provider supports streaming transcription."""
        return False

    def transcribe_streaming(
        self,
        audio_bytes: bytes,
        on_chunk: Callable[[str], None]
    ) -> TranscriptionResult:
        """
        Transcribe audio with streaming output.

        Providers that support streaming should override this method.
        Default implementation falls back to regular transcribe().

        Args:
            audio_bytes: WAV file contents
            on_chunk: Callback called with cumulative text as it streams

        Returns:
            TranscriptionResult with final text and metadata
        """
        # Default: fall back to non-streaming
        result = self.transcribe(audio_bytes)
        if result.text:
            on_chunk(result.text)
        return result
