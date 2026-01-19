"""
OpenAI Transcription API provider.

Models (December 2025):
- gpt-4o-transcribe: Best accuracy, improved WER over Whisper
- gpt-4o-mini-transcribe: Faster, more affordable
- whisper-1: Classic Whisper v2, still available

API endpoint: POST https://api.openai.com/v1/audio/transcriptions
"""

import io
from openai import OpenAI
from .base import TranscriptionProvider, TranscriptionResult
from ..keychain import get_api_key


class OpenAITranscribeProvider(TranscriptionProvider):
    """OpenAI transcription using latest gpt-4o-transcribe models."""

    name = "openai"
    display_name = "OpenAI"

    # Available models with pricing (per minute)
    MODELS = [
        {
            "id": "gpt-4o-transcribe",
            "name": "GPT-4o Transcribe",
            "description": "Best accuracy, handles accents and noise well",
            "cost_per_minute": 0.006
        },
        {
            "id": "gpt-4o-mini-transcribe",
            "name": "GPT-4o Mini Transcribe",
            "description": "Fast and affordable, good for clear audio",
            "cost_per_minute": 0.003
        },
        {
            "id": "whisper-1",
            "name": "Whisper v2",
            "description": "Classic Whisper model, reliable",
            "cost_per_minute": 0.006
        }
    ]

    def __init__(self, model: str = "gpt-4o-transcribe"):
        self.model = model
        self._client = None

    @property
    def client(self) -> OpenAI:
        """Lazy-load the OpenAI client."""
        if self._client is None:
            api_key = get_api_key("openai")
            if not api_key:
                raise ValueError("OpenAI API key not configured")
            self._client = OpenAI(api_key=api_key)
        return self._client

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        """Transcribe audio using OpenAI API."""
        if not audio_bytes:
            return TranscriptionResult(
                text="",
                duration_seconds=0,
                cost_estimate=0,
                provider=self.name,
                model=self.model
            )

        # Create file-like object for API
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "recording.wav"

        # Get the model config for cost calculation
        model_config = next(
            (m for m in self.MODELS if m["id"] == self.model),
            self.MODELS[0]
        )

        # Call transcription API
        # gpt-4o-transcribe models support json and text output
        # whisper-1 also supports srt, vtt, verbose_json
        if self.model == "whisper-1":
            response = self.client.audio.transcriptions.create(
                model=self.model,
                file=audio_file,
                response_format="verbose_json"
            )
            duration = response.duration
            text = response.text.strip()
            language = response.language
        else:
            # gpt-4o-transcribe models
            response = self.client.audio.transcriptions.create(
                model=self.model,
                file=audio_file,
                response_format="json"
            )
            text = response.text.strip()
            # Estimate duration from audio bytes (16kHz, 16-bit mono = 32KB/sec)
            duration = len(audio_bytes) / 32000
            language = None

        # Calculate cost
        duration_minutes = duration / 60
        cost = duration_minutes * model_config["cost_per_minute"]

        return TranscriptionResult(
            text=text,
            duration_seconds=duration,
            cost_estimate=cost,
            provider=self.name,
            model=self.model,
            language=language
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
