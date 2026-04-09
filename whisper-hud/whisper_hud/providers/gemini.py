"""
Google Gemini API provider for audio transcription.

Gemini models can process audio natively and provide transcription.
Supports speaker diarization through prompting.

Models (February 2026):
- gemini-3-pro-preview: Highest quality, supports audio input
- gemini-3-flash-preview: Fast, strong quality, supports audio input
- gemini-2.5-flash: Stable, supports audio input
- gemini-2.5-flash-lite: Lowest latency/cost, supports audio input
"""

from types import SimpleNamespace
from typing import Callable
from .base import TranscriptionProvider, TranscriptionResult
from .error_utils import build_provider_error_message
from ..keychain import get_api_key


class GeminiProvider(TranscriptionProvider):
    """Google Gemini for audio transcription."""

    name = "gemini"
    display_name = "Google Gemini"
    CLIENT_TIMEOUT_MS = 30000

    # Available models with approximate costs
    MODELS = [
        {
            "id": "gemini-3-pro-preview",
            "name": "Gemini 3 Pro (Preview)",
            "description": "Highest quality, supports audio input",
            "cost_per_minute": 0.001,
        },
        {
            "id": "gemini-3-flash-preview",
            "name": "Gemini 3 Flash",
            "description": "Latest, fastest, frontier intelligence",
            "cost_per_minute": 0.001,
            "recommended": True,
        },
        {
            "id": "gemini-2.5-flash",
            "name": "Gemini 2.5 Flash",
            "description": "Stable, fast, supports audio input",
            "cost_per_minute": 0.001,
        },
        {
            "id": "gemini-2.5-flash-lite",
            "name": "Gemini 2.5 Flash Lite",
            "description": "Lowest latency/cost, supports audio input",
            "cost_per_minute": 0.001,
        },
    ]

    def __init__(self, model: str = "gemini-3-flash-preview"):
        self.model = model
        self._client = None

    def _get_client(self):
        """Get or create the Gemini client."""
        if self._client is None:
            try:
                from google import genai
                from google.genai import types
            except ImportError:
                raise RuntimeError("google-genai package not installed. Install with: pip install google-genai")

            api_key = get_api_key("gemini")
            if not api_key:
                raise ValueError("Gemini API key not configured")
            self._client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=self.CLIENT_TIMEOUT_MS),
            )

        return self._client

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        """Transcribe audio using Gemini."""
        if not audio_bytes:
            return TranscriptionResult(
                text="", duration_seconds=0, cost_estimate=0, provider=self.name, model=self.model
            )

        client = self._get_client()

        from google.genai import types

        # Transcription prompt - optimized for accuracy
        prompt = """Transcribe this audio exactly as spoken.
Output ONLY the transcription text, nothing else.
Do not add any commentary, labels, or formatting.
Preserve natural punctuation."""

        try:
            response = client.models.generate_content(
                model=self.model,
                contents=[
                    prompt,
                    types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav"),
                ],
            )
        except Exception as e:
            raise RuntimeError(self._build_transcribe_error_message(e)) from e

        # Get the model config for cost calculation
        model_config = next((m for m in self.MODELS if m["id"] == self.model), self.MODELS[0])

        # Estimate duration from audio bytes (16kHz, 16-bit mono = 32KB/sec)
        duration_seconds = len(audio_bytes) / 32000

        # Calculate cost
        cost = (duration_seconds / 60) * model_config["cost_per_minute"]

        text = self._extract_transcription_text(response)
        if text is None:
            raise RuntimeError(
                "Gemini transcription returned an unexpected response format. " "No transcription text was found."
            )

        return TranscriptionResult(
            text=text,
            duration_seconds=duration_seconds,
            cost_estimate=cost,
            provider=self.name,
            model=self.model,
            language=None,
        )

    def is_configured(self) -> bool:
        """Check if Gemini API key exists."""
        return get_api_key("gemini") is not None

    def get_models(self) -> list[dict]:
        """Return available Gemini models."""
        return self.MODELS

    def set_model(self, model_id: str) -> None:
        """Set the active model."""
        if any(m["id"] == model_id for m in self.MODELS):
            self.model = model_id
            self._client = None

    def get_current_model(self) -> str:
        """Get the current model ID."""
        return self.model

    def supports_streaming(self) -> bool:
        """Gemini supports streaming transcription."""
        return True

    @staticmethod
    def _build_transcribe_error_message(error: Exception) -> str:
        """Map Gemini request failures to safe user-readable RuntimeError messages."""
        return build_provider_error_message("Gemini", "transcription", error)

    @staticmethod
    def _extract_transcription_text(response) -> str | None:
        """Return stripped response text when Gemini returns a valid payload."""
        text = getattr(response, "text", None)
        if text is None and isinstance(response, dict):
            text = response.get("text")
        if text is None and isinstance(response, SimpleNamespace):
            text = response.__dict__.get("text")
        if text is None:
            return None
        return text.strip()

    def transcribe_streaming(self, audio_bytes: bytes, on_chunk: Callable[[str], None]) -> TranscriptionResult:
        """
        Transcribe audio with streaming output.

        Args:
            audio_bytes: WAV file contents
            on_chunk: Callback called with cumulative text as it streams

        Returns:
            TranscriptionResult with final text and metadata
        """
        if not audio_bytes:
            return TranscriptionResult(
                text="", duration_seconds=0, cost_estimate=0, provider=self.name, model=self.model
            )

        client = self._get_client()
        from google.genai import types

        # Transcription prompt
        prompt = """Transcribe this audio exactly as spoken.
Output ONLY the transcription text, nothing else.
Do not add any commentary, labels, or formatting.
Preserve natural punctuation."""

        cumulative_text = ""
        try:
            response = client.models.generate_content_stream(
                model=self.model,
                contents=[
                    prompt,
                    types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav"),
                ],
            )

            for chunk in response:
                if chunk.text:
                    cumulative_text += chunk.text
                    on_chunk(cumulative_text.strip())
        except Exception as e:
            raise RuntimeError(self._build_transcribe_error_message(e)) from e

        # Get final text
        final_text = cumulative_text.strip()

        # Get the model config for cost calculation
        model_config = next((m for m in self.MODELS if m["id"] == self.model), self.MODELS[0])

        # Estimate duration from audio bytes (16kHz, 16-bit mono = 32KB/sec)
        duration_seconds = len(audio_bytes) / 32000

        # Calculate cost
        cost = (duration_seconds / 60) * model_config["cost_per_minute"]

        return TranscriptionResult(
            text=final_text,
            duration_seconds=duration_seconds,
            cost_estimate=cost,
            provider=self.name,
            model=self.model,
            language=None,
        )
