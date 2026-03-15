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
from ..keychain import get_api_key


class GeminiProvider(TranscriptionProvider):
    """Google Gemini for audio transcription."""

    name = "gemini"
    display_name = "Google Gemini"

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
            "recommended": True
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
            except ImportError:
                raise RuntimeError(
                    "google-genai package not installed. Install with: pip install google-genai"
                )

            api_key = get_api_key("gemini")
            if not api_key:
                raise ValueError("Gemini API key not configured")
            self._client = genai.Client(api_key=api_key)

        return self._client

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        """Transcribe audio using Gemini."""
        if not audio_bytes:
            return TranscriptionResult(
                text="",
                duration_seconds=0,
                cost_estimate=0,
                provider=self.name,
                model=self.model
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
        model_config = next(
            (m for m in self.MODELS if m["id"] == self.model),
            self.MODELS[0]
        )

        # Estimate duration from audio bytes (16kHz, 16-bit mono = 32KB/sec)
        duration_seconds = len(audio_bytes) / 32000

        # Calculate cost
        cost = (duration_seconds / 60) * model_config["cost_per_minute"]

        text = self._extract_transcription_text(response)
        if text is None:
            raise RuntimeError(
                "Gemini transcription returned an unexpected response format. "
                "No transcription text was found."
            )

        return TranscriptionResult(
            text=text,
            duration_seconds=duration_seconds,
            cost_estimate=cost,
            provider=self.name,
            model=self.model,
            language=None
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
        """Map Gemini request failures to user-readable RuntimeError messages."""
        details = str(error).strip() or error.__class__.__name__
        error_type = error.__class__.__name__.lower()
        status_code = getattr(error, "status_code", None)
        if status_code is None:
            status_code = getattr(error, "code", None)
        if status_code is None:
            response = getattr(error, "response", None)
            status_code = getattr(response, "status_code", None)

        if GeminiProvider._is_network_error(error_type, details):
            return f"Gemini transcription failed due to a network error: {details}"
        if GeminiProvider._is_api_error(error_type, status_code):
            return f"Gemini transcription failed due to an API error: {details}"
        return f"Gemini transcription failed: {details}"

    @staticmethod
    def _is_network_error(error_type: str, details: str) -> bool:
        """Best-effort classification for transport-layer failures."""
        network_markers = (
            "connection",
            "connect",
            "timeout",
            "timed out",
            "network",
            "dns",
            "socket",
            "ssl",
            "transport",
            "unreachable",
            "temporarily unavailable",
        )
        lowered_details = details.lower()
        return "api" not in error_type and (
            any(marker in error_type for marker in network_markers)
            or any(marker in lowered_details for marker in network_markers)
        )

    @staticmethod
    def _is_api_error(error_type: str, status_code) -> bool:
        """Detect provider/API failures from SDK metadata when available."""
        if status_code is not None:
            try:
                return int(status_code) >= 400
            except (TypeError, ValueError):
                return True
        return "api" in error_type or "http" in error_type or "status" in error_type

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

    def transcribe_streaming(
        self,
        audio_bytes: bytes,
        on_chunk: Callable[[str], None]
    ) -> TranscriptionResult:
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
                text="",
                duration_seconds=0,
                cost_estimate=0,
                provider=self.name,
                model=self.model
            )

        client = self._get_client()
        from google.genai import types

        # Transcription prompt
        prompt = """Transcribe this audio exactly as spoken.
Output ONLY the transcription text, nothing else.
Do not add any commentary, labels, or formatting.
Preserve natural punctuation."""

        # Generate with streaming
        response = client.models.generate_content_stream(
            model=self.model,
            contents=[
                prompt,
                types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav"),
            ],
        )

        cumulative_text = ""
        for chunk in response:
            if chunk.text:
                cumulative_text += chunk.text
                on_chunk(cumulative_text.strip())

        # Get final text
        final_text = cumulative_text.strip()

        # Get the model config for cost calculation
        model_config = next(
            (m for m in self.MODELS if m["id"] == self.model),
            self.MODELS[0]
        )

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
            language=None
        )
