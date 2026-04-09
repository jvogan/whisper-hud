"""
OpenAI Transcription API provider.

Models (February 2026):
- gpt-4o-transcribe: Best accuracy, improved WER over Whisper
- gpt-4o-transcribe-diarize: Speaker-aware transcripts (diarization)
- gpt-4o-mini-transcribe: Faster, more affordable
- whisper-1: Classic Whisper v2, still available

API endpoint: POST https://api.openai.com/v1/audio/transcriptions
"""

import io
from importlib import import_module
from typing import TYPE_CHECKING
from .base import TranscriptionProvider, TranscriptionResult
from .error_utils import build_provider_error_message
from .http_client_utils import OPENAI_API_BASE_URL, build_hardened_http_client
from ..keychain import get_api_key

if TYPE_CHECKING:
    from openai import OpenAI


class OpenAITranscribeProvider(TranscriptionProvider):
    """OpenAI transcription using latest gpt-4o-transcribe models."""

    name = "openai"
    display_name = "OpenAI"
    CLIENT_TIMEOUT_SECONDS = 30.0
    CLIENT_MAX_RETRIES = 0

    # Available models with pricing (per minute)
    MODELS = [
        {
            "id": "gpt-4o-transcribe",
            "name": "GPT-4o Transcribe",
            "description": "Best accuracy, handles accents and noise well",
            "cost_per_minute": 0.006,
        },
        {
            "id": "gpt-4o-transcribe-diarize",
            "name": "GPT-4o Transcribe Diarize",
            "description": "Speaker-aware transcript (HUD shows plain text)",
            "cost_per_minute": 0.006,
        },
        {
            "id": "gpt-4o-mini-transcribe",
            "name": "GPT-4o Mini Transcribe",
            "description": "Fast and affordable, good for clear audio",
            "cost_per_minute": 0.003,
        },
        {
            "id": "whisper-1",
            "name": "Whisper v2",
            "description": "Classic Whisper model, reliable",
            "cost_per_minute": 0.006,
        },
    ]

    def __init__(self, model: str = "gpt-4o-transcribe"):
        self.model = model
        self._client = None

    @property
    def client(self) -> "OpenAI":
        """Lazy-load the OpenAI client."""
        if self._client is None:
            openai_cls = self._get_openai_client_class()
            api_key = get_api_key("openai")
            if not api_key:
                raise ValueError("OpenAI API key not configured")
            self._client = openai_cls(
                api_key=api_key,
                base_url=OPENAI_API_BASE_URL,
                timeout=self.CLIENT_TIMEOUT_SECONDS,
                max_retries=self.CLIENT_MAX_RETRIES,
                http_client=build_hardened_http_client(self.CLIENT_TIMEOUT_SECONDS),
            )
        return self._client

    @staticmethod
    def _get_openai_client_class():
        """Import the OpenAI SDK lazily so availability checks can mock package absence."""
        try:
            return import_module("openai").OpenAI
        except ModuleNotFoundError as exc:
            raise RuntimeError("openai package not installed. Install with: pip install openai") from exc

    def is_available(self) -> bool:
        """Check whether the SDK is importable and an API key is configured."""
        try:
            self._get_openai_client_class()
        except RuntimeError:
            return False
        return bool(get_api_key("openai"))

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        """Transcribe audio using OpenAI API."""
        if not audio_bytes:
            return TranscriptionResult(
                text="", duration_seconds=0, cost_estimate=0, provider=self.name, model=self.model
            )

        # Create file-like object for API
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "recording.wav"

        # Get the model config for cost calculation
        model_config = next((m for m in self.MODELS if m["id"] == self.model), self.MODELS[0])

        # Call transcription API
        # gpt-4o-transcribe models support json or text output
        # gpt-4o-transcribe-diarize supports json/text/diarized_json
        # whisper-1 also supports srt, vtt, verbose_json
        try:
            if self.model == "whisper-1":
                response = self.client.audio.transcriptions.create(
                    model=self.model, file=audio_file, response_format="verbose_json"
                )
                duration = response.duration
                text = response.text.strip()
                language = response.language
            elif self.model == "gpt-4o-transcribe-diarize":
                response = self.client.audio.transcriptions.create(
                    model=self.model, file=audio_file, response_format="diarized_json", chunking_strategy="auto"
                )
                text = self._extract_text(response)
                # Estimate duration from audio bytes (16kHz, 16-bit mono = 32KB/sec)
                duration = len(audio_bytes) / 32000
                language = None
            else:
                # gpt-4o-transcribe models
                response = self.client.audio.transcriptions.create(
                    model=self.model, file=audio_file, response_format="json"
                )
                text = response.text.strip()
                # Estimate duration from audio bytes (16kHz, 16-bit mono = 32KB/sec)
                duration = len(audio_bytes) / 32000
                language = None
        except Exception as e:
            raise RuntimeError(build_provider_error_message("OpenAI", "transcription", e)) from e

        # Calculate cost
        duration_minutes = duration / 60
        cost = duration_minutes * model_config["cost_per_minute"]

        return TranscriptionResult(
            text=text,
            duration_seconds=duration,
            cost_estimate=cost,
            provider=self.name,
            model=self.model,
            language=language,
        )

    def is_configured(self) -> bool:
        """Check if OpenAI API key exists."""
        return get_api_key("openai") is not None

    def get_models(self) -> list[dict]:
        """Return available OpenAI transcription models."""
        return self.MODELS

    def set_model(self, model_id: str) -> None:
        """Set the active model."""
        if any(m["id"] == model_id for m in self.MODELS):
            self.model = model_id
            self._client = None  # Reset client

    def get_current_model(self) -> str:
        """Get the current model ID."""
        return self.model

    @staticmethod
    def _extract_text(response) -> str:
        """Extract text from diarized responses without speaker labels."""
        # First try standard text field
        if hasattr(response, "text") and response.text:
            return response.text.strip()
        if isinstance(response, dict) and response.get("text"):
            return str(response.get("text", "")).strip()

        # Fall back to concatenating segments
        segments = None
        if isinstance(response, dict):
            segments = response.get("segments")
        else:
            segments = getattr(response, "segments", None)

        if not segments:
            return ""

        texts: list[str] = []
        for segment in segments:
            if isinstance(segment, dict):
                segment_text = segment.get("text")
            else:
                segment_text = getattr(segment, "text", None)
            if segment_text:
                texts.append(str(segment_text).strip())

        return " ".join(texts).strip()
