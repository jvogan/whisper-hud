"""
Abstract base class for translation providers.

All translation happens locally on device for privacy.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Callable


@dataclass
class TranslationResult:
    """Result from a translation request."""
    text: str
    source_lang: str
    target_lang: str
    provider: str
    model: str


class TranslationProvider(ABC):
    """Base class for all translation providers."""

    name: str = "base"
    display_name: str = "Base Provider"

    @abstractmethod
    def translate(self, text: str, source_lang: str, target_lang: str) -> TranslationResult:
        """
        Translate text from source language to target language.

        Args:
            text: Text to translate
            source_lang: Source language code (ISO 639-1)
            target_lang: Target language code (ISO 639-1)

        Returns:
            TranslationResult with translated text and metadata
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is running and model is downloaded."""
        pass

    @abstractmethod
    def get_model_status(self) -> dict:
        """
        Return model status information.

        Returns:
            Dict with 'downloaded', 'size_gb', 'ram_required' keys
        """
        pass

    @abstractmethod
    def download_model(self, progress_callback: Optional[Callable[[str], None]] = None) -> bool:
        """
        Download the model.

        Args:
            progress_callback: Optional callback for progress updates

        Returns:
            True if download succeeded
        """
        pass

    def supports_streaming(self) -> bool:
        """Check if this provider supports streaming translation."""
        return False

    def translate_streaming(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        on_chunk: Callable[[str], None]
    ) -> TranslationResult:
        """
        Translate text with streaming output.

        Providers that support streaming should override this method.
        Default implementation falls back to regular translate().

        Args:
            text: Text to translate
            source_lang: Source language code
            target_lang: Target language code
            on_chunk: Callback called with cumulative text as it streams

        Returns:
            TranslationResult with final translated text
        """
        # Default: fall back to non-streaming
        result = self.translate(text, source_lang, target_lang)
        if result.text:
            on_chunk(result.text)
        return result
