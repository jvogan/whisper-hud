"""
Google Gemini API provider for audio transcription.

Gemini models can process audio natively and provide transcription.
Supports speaker diarization through prompting.

Models (December 2025):
- gemini-2.0-flash-exp: Latest, very fast
- gemini-1.5-flash: Stable, fastest
- gemini-1.5-pro: Best quality for complex audio
"""

import base64
import google.generativeai as genai
from .base import TranscriptionProvider, TranscriptionResult
from ..keychain import get_api_key


class GeminiProvider(TranscriptionProvider):
    """Google Gemini for audio transcription."""

    name = "gemini"
    display_name = "Google Gemini"

    # Available models with approximate costs
    MODELS = [
        {
            "id": "gemini-2.0-flash-exp",
            "name": "Gemini 2.0 Flash",
            "description": "Latest model, very fast, experimental",
            "cost_per_minute": 0.001
        },
        {
            "id": "gemini-1.5-flash",
            "name": "Gemini 1.5 Flash",
            "description": "Stable and fast, production ready",
            "cost_per_minute": 0.001
        },
        {
            "id": "gemini-1.5-pro",
            "name": "Gemini 1.5 Pro",
            "description": "Best quality, handles complex audio",
            "cost_per_minute": 0.005
        }
    ]

    def __init__(self, model: str = "gemini-2.0-flash-exp"):
        self.model = model
        self._configured = False

    def _configure(self):
        """Configure Gemini API with stored key."""
        if not self._configured:
            api_key = get_api_key("gemini")
            if not api_key:
                raise ValueError("Gemini API key not configured")
            genai.configure(api_key=api_key)
            self._configured = True

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

        self._configure()

        # Encode audio as base64
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')

        # Create model instance
        model = genai.GenerativeModel(self.model)

        # Prepare audio part
        audio_part = {
            "mime_type": "audio/wav",
            "data": audio_b64
        }

        # Transcription prompt - optimized for accuracy
        prompt = """Transcribe this audio exactly as spoken.
Output ONLY the transcription text, nothing else.
Do not add any commentary, labels, or formatting.
Preserve natural punctuation."""

        # Generate transcription
        response = model.generate_content([prompt, audio_part])

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
            text=response.text.strip() if response.text else "",
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
            self._configured = False  # Reset configuration

    def get_current_model(self) -> str:
        """Get the current model ID."""
        return self.model
