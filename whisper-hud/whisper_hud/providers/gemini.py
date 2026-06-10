"""
Google Gemini API provider for audio transcription.

Gemini models can process audio natively and provide transcription.
Supports speaker diarization through prompting.

Models (verified June 2026 against ai.google.dev/gemini-api/docs/models + audio docs):
- gemini-3.1-flash-lite: Current stable default for direct audio transcription (lowest latency/cost)
- gemini-3.5-flash: Newest stable audio-capable Flash model (released 2026-05-19)
- gemini-3-flash-preview: Frontier preview balanced model
- gemini-3.1-pro-preview: Latest preview quality model
- gemini-2.5-flash: Legacy stable fallback, supports audio input
- gemini-2.5-pro: Strongest stable quality
- gemini-2.5-flash-lite: Lowest latency/cost, supports audio input

Cost-per-minute values below are approximate: Gemini bills audio understanding by
token (~32 input tokens/sec of audio), so the per-minute figure is an estimate the
HUD uses for rough cost display only.
"""

from types import SimpleNamespace
from typing import Callable, Optional, Sequence
from .base import TranscriptionProvider, TranscriptionResult
from .error_utils import build_provider_error_message
from .vocabulary_utils import normalize_vocabulary_phrases
from ..keychain import get_api_key

# Base instruction sent with the audio; a vocabulary hint line is appended when
# the user supplies biasing terms (see _build_transcription_prompt).
_BASE_TRANSCRIPTION_PROMPT = """Transcribe this audio exactly as spoken.
Output ONLY the transcription text, nothing else.
Do not add any commentary, labels, or formatting.
Preserve natural punctuation."""


class GeminiProvider(TranscriptionProvider):
    """Google Gemini for audio transcription."""

    name = "gemini"
    display_name = "Google Gemini"
    CLIENT_TIMEOUT_MS = 30000

    DEFAULT_MODEL = "gemini-3.1-flash-lite"
    STABLE_FALLBACK_MODEL = "gemini-3.1-flash-lite"
    MODEL_ALIASES = {
        "gemini-3-pro-preview": "gemini-3.1-pro-preview",
        "gemini-3-pro": "gemini-3.1-pro-preview",
        "gemini-3.1-pro": "gemini-3.1-pro-preview",
        "gemini-3-flash": "gemini-3-flash-preview",
        "gemini-3.1-flash-lite-preview": "gemini-3.1-flash-lite",
        "gemini-2.5-flash-preview": "gemini-2.5-flash",
        "gemini-2.5-flash-lite-preview-09-2025": "gemini-3.1-flash-lite",
    }

    # Available models with approximate costs
    MODELS = [
        {
            "id": "gemini-3.1-flash-lite",
            "name": "Gemini 3.1 Flash-Lite",
            "description": "Current stable default for direct audio transcription",
            "cost_per_minute": 0.001,
            "recommended": True,
        },
        {
            "id": "gemini-3.5-flash",
            "name": "Gemini 3.5 Flash",
            "description": "Newest stable audio-capable Flash model; higher quality than Flash-Lite",
            "cost_per_minute": 0.002,
            "recommended": True,
        },
        {
            "id": "gemini-3-flash-preview",
            "name": "Gemini 3 Flash (Preview)",
            "description": "Frontier preview balanced model for newer Gemini 3 multimodal support",
            "cost_per_minute": 0.001,
        },
        {
            "id": "gemini-3.1-pro-preview",
            "name": "Gemini 3.1 Pro (Preview)",
            "description": "Latest preview quality model with improved reasoning and reliability",
            "cost_per_minute": 0.001,
        },
        {
            "id": "gemini-2.5-pro",
            "name": "Gemini 2.5 Pro",
            "description": "Legacy stable quality option; Google recommends migrating to Gemini 3.1 Pro Preview",
            "cost_per_minute": 0.001,
        },
        {
            "id": "gemini-2.5-flash",
            "name": "Gemini 2.5 Flash",
            "description": "Legacy stable balanced option; Google recommends migrating to Gemini 3 Flash Preview",
            "cost_per_minute": 0.001,
        },
        {
            "id": "gemini-2.5-flash-lite",
            "name": "Gemini 2.5 Flash Lite",
            "description": "Legacy stable speed option; Google recommends migrating to Gemini 3.1 Flash-Lite",
            "cost_per_minute": 0.001,
        },
    ]

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = self.normalize_model_id(model)
        self._client = None

    @classmethod
    def normalize_model_id(cls, model_id: str) -> str:
        """Normalize configured IDs to current Gemini transcription models."""
        if any(model["id"] == model_id for model in cls.MODELS):
            return model_id
        mapped = cls.MODEL_ALIASES.get(model_id)
        if mapped and any(model["id"] == mapped for model in cls.MODELS):
            return mapped
        return cls.DEFAULT_MODEL

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
                http_options=types.HttpOptions(
                    timeout=self.CLIENT_TIMEOUT_MS,
                    clientArgs={"trust_env": False},
                    asyncClientArgs={"trust_env": False},
                ),
            )

        return self._client

    @staticmethod
    def _build_transcription_prompt(vocabulary: Optional[Sequence[str]] = None) -> str:
        """Build the transcription instruction, appending a vocabulary hint line.

        When the user supplies biasing terms, a short hint line listing them is
        appended so Gemini favors those spellings; otherwise the base prompt is
        returned unchanged.
        """
        phrases = normalize_vocabulary_phrases(vocabulary)
        if not phrases:
            return _BASE_TRANSCRIPTION_PROMPT
        hint = "Expect these words/phrases (use their exact spelling): " + ", ".join(phrases) + "."
        return f"{_BASE_TRANSCRIPTION_PROMPT}\n{hint}"

    @staticmethod
    def _is_model_not_found_error(error: Exception) -> bool:
        """Return True when Gemini rejects the selected model ID."""
        message = str(error).lower()
        if "model" not in message:
            return False
        return any(token in message for token in ("not found", "invalid", "unsupported", "unknown"))

    def transcribe(self, audio_bytes: bytes, vocabulary: Optional[Sequence[str]] = None) -> TranscriptionResult:
        """Transcribe audio using Gemini.

        ``vocabulary`` appends a short hint line listing the expected
        words/phrases to the transcription instruction so Gemini favors their
        spellings.
        """
        if not audio_bytes:
            return TranscriptionResult(
                text="", duration_seconds=0, cost_estimate=0, provider=self.name, model=self.model
            )

        client = self._get_client()

        from google.genai import types

        # Transcription prompt - optimized for accuracy (plus optional vocabulary hint)
        prompt = self._build_transcription_prompt(vocabulary)

        audio_part = types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav")
        attempt_models = [self.model]
        if self.STABLE_FALLBACK_MODEL not in attempt_models:
            attempt_models.append(self.STABLE_FALLBACK_MODEL)

        response = None
        used_model = self.model
        last_error: Exception | None = None
        for model_id in attempt_models:
            try:
                response = client.models.generate_content(
                    model=model_id,
                    contents=[prompt, audio_part],
                )
                used_model = model_id
                break
            except Exception as e:
                last_error = e
                if model_id != self.STABLE_FALLBACK_MODEL and self._is_model_not_found_error(e):
                    continue
                raise RuntimeError(self._build_transcribe_error_message(e)) from e

        if response is None:
            raise RuntimeError(self._build_transcribe_error_message(last_error or RuntimeError("unknown error")))

        if used_model != self.model:
            self.model = used_model

        # Get the model config for cost calculation
        model_config = next((m for m in self.MODELS if m["id"] == used_model), self.MODELS[0])

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
            model=used_model,
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
        if any(model["id"] == model_id for model in self.MODELS):
            normalized_model = model_id
        else:
            normalized_model = self.MODEL_ALIASES.get(model_id)
            if not normalized_model or not any(model["id"] == normalized_model for model in self.MODELS):
                return

        if normalized_model != self.model:
            self.model = normalized_model
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

    def transcribe_streaming(
        self,
        audio_bytes: bytes,
        on_chunk: Callable[[str], None],
        vocabulary: Optional[Sequence[str]] = None,
    ) -> TranscriptionResult:
        """
        Transcribe audio with streaming output.

        Args:
            audio_bytes: WAV file contents
            on_chunk: Callback called with cumulative text as it streams
            vocabulary: Optional words/phrases appended as a hint line to the
                transcription instruction.

        Returns:
            TranscriptionResult with final text and metadata
        """
        if not audio_bytes:
            return TranscriptionResult(
                text="", duration_seconds=0, cost_estimate=0, provider=self.name, model=self.model
            )

        client = self._get_client()
        from google.genai import types

        # Transcription prompt (plus optional vocabulary hint)
        prompt = self._build_transcription_prompt(vocabulary)

        audio_part = types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav")
        attempt_models = [self.model]
        if self.STABLE_FALLBACK_MODEL not in attempt_models:
            attempt_models.append(self.STABLE_FALLBACK_MODEL)

        cumulative_text = ""
        used_model = self.model
        last_error: Exception | None = None
        for model_id in attempt_models:
            cumulative_text = ""
            try:
                response = client.models.generate_content_stream(
                    model=model_id,
                    contents=[prompt, audio_part],
                )

                for chunk in response:
                    if chunk.text:
                        cumulative_text += chunk.text
                        on_chunk(cumulative_text.strip())

                used_model = model_id
                break
            except Exception as e:
                last_error = e
                if model_id != self.STABLE_FALLBACK_MODEL and self._is_model_not_found_error(e):
                    continue
                raise RuntimeError(self._build_transcribe_error_message(e)) from e
        else:
            raise RuntimeError(self._build_transcribe_error_message(last_error or RuntimeError("unknown error")))

        if used_model != self.model:
            self.model = used_model

        # Get final text
        final_text = cumulative_text.strip()

        # Get the model config for cost calculation
        model_config = next((m for m in self.MODELS if m["id"] == used_model), self.MODELS[0])

        # Estimate duration from audio bytes (16kHz, 16-bit mono = 32KB/sec)
        duration_seconds = len(audio_bytes) / 32000

        # Calculate cost
        cost = (duration_seconds / 60) * model_config["cost_per_minute"]

        return TranscriptionResult(
            text=final_text,
            duration_seconds=duration_seconds,
            cost_estimate=cost,
            provider=self.name,
            model=used_model,
            language=None,
        )
