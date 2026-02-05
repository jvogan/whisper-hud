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

import base64
from typing import Callable
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

    def supports_streaming(self) -> bool:
        """Gemini supports streaming transcription."""
        return True

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

        # Transcription prompt
        prompt = """Transcribe this audio exactly as spoken.
Output ONLY the transcription text, nothing else.
Do not add any commentary, labels, or formatting.
Preserve natural punctuation."""

        # Generate with streaming
        response = model.generate_content([prompt, audio_part], stream=True)

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
