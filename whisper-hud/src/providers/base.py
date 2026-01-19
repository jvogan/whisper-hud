"""
Abstract base class for transcription providers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


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
