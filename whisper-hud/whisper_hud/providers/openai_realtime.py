"""
OpenAI Realtime transcription provider.

Uses the Realtime WebSocket API for true live microphone dictation with
incremental transcript deltas and a final committed turn transcript.
"""

from __future__ import annotations

import base64
import math
import threading
from collections import deque
from typing import Any, Callable, Optional

import numpy as np
from openai import OpenAI
from scipy.signal import resample_poly

from .base import LiveTranscriptionSession, TranscriptionProvider, TranscriptionResult
from .openai_whisper import OpenAITranscribeProvider
from ..keychain import get_api_key
from ..logging_config import get_logger

logger = get_logger("providers.openai_realtime")


class OpenAIRealtimeSession(LiveTranscriptionSession):
    """One-shot live transcription session for a single recording turn."""

    TARGET_SAMPLE_RATE = 24000
    PRECONNECT_BUFFER_SECONDS = 2.0
    INPUT_AUDIO_FORMAT = {"type": "audio/pcm", "rate": TARGET_SAMPLE_RATE}
    NOISE_REDUCTION = {"type": "near_field"}

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        provider_name: str,
        cost_per_minute: float,
        on_partial: Callable[[str], None],
        on_final: Callable[[TranscriptionResult], None],
        on_error: Callable[[Exception], None],
        on_ready: Optional[Callable[[], None]] = None,
        language: Optional[str] = None,
        prompt: Optional[str] = None,
    ):
        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._provider_name = provider_name
        self._cost_per_minute = cost_per_minute
        self._language = language
        self._prompt = prompt
        self._on_partial = on_partial
        self._on_final = on_final
        self._on_error = on_error
        self._on_ready = on_ready

        self._thread: Optional[threading.Thread] = None
        self._connection = None
        self._connection_lock = threading.Lock()
        self._state_lock = threading.Lock()

        self._ready = threading.Event()
        self._closed = threading.Event()
        self._stop_requested = threading.Event()
        self._commit_sent = False
        self._error_sent = False
        self._final_sent = False
        self._committed_item_id: Optional[str] = None
        self._partial_transcripts: dict[str, str] = {}
        self._pending_audio: deque[tuple[str, float]] = deque()
        self._pending_audio_seconds = 0.0
        self._sent_audio_seconds = 0.0

    def start(self) -> None:
        """Start the remote session in a background thread."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def is_ready(self) -> bool:
        """Return True once the remote session has confirmed the config."""
        return self._ready.is_set()

    def push_audio(self, audio_chunk: Any, sample_rate: int) -> None:
        """Convert and queue microphone audio for the live session."""
        if self._closed.is_set() or self._stop_requested.is_set():
            return

        encoded_audio, duration_seconds = self._encode_audio_chunk(audio_chunk, sample_rate)
        if not encoded_audio:
            return

        if not self._ready.is_set():
            with self._state_lock:
                self._pending_audio.append((encoded_audio, duration_seconds))
                self._pending_audio_seconds += duration_seconds
                while self._pending_audio and self._pending_audio_seconds > self.PRECONNECT_BUFFER_SECONDS:
                    _, dropped_seconds = self._pending_audio.popleft()
                    self._pending_audio_seconds -= dropped_seconds
            return

        self._append_audio(encoded_audio, duration_seconds)

    def request_stop(self) -> None:
        """Commit the current audio buffer exactly once."""
        self._stop_requested.set()
        if not self._ready.is_set():
            return
        self._commit_audio()

    def close(self) -> None:
        """Close the session and underlying websocket."""
        if self._closed.is_set():
            return
        self._closed.set()
        connection = self._connection
        if connection is not None:
            try:
                connection.close()
            except Exception:
                logger.debug("Failed to close OpenAI realtime connection cleanly", exc_info=True)

    def _run(self) -> None:
        """Own the websocket lifetime and process incoming events."""
        try:
            with self._client.realtime.connect() as connection:
                self._connection = connection
                connection.session.update(session=self._build_session_update())

                while not self._closed.is_set():
                    event = connection.recv()
                    self._handle_event(event)
                    if self._final_sent:
                        break
        except Exception as e:
            if not self._closed.is_set():
                self._notify_error(RuntimeError(f"OpenAI Realtime session failed: {e}"))
        finally:
            self.close()

    def _build_session_update(self) -> dict[str, Any]:
        """Build the transcription session payload."""
        transcription: dict[str, Any] = {"model": self._model}
        if self._language:
            transcription["language"] = self._language
        if self._prompt:
            transcription["prompt"] = self._prompt

        return {
            "type": "transcription",
            "audio": {
                "input": {
                    "format": dict(self.INPUT_AUDIO_FORMAT),
                    "noise_reduction": dict(self.NOISE_REDUCTION),
                    "transcription": transcription,
                    "turn_detection": None,
                }
            },
        }

    def _handle_event(self, event: Any) -> None:
        """Route relevant realtime events to callbacks."""
        event_type = getattr(event, "type", "")

        if event_type == "session.updated":
            self._ready.set()
            self._flush_pending_audio()
            if self._on_ready:
                self._on_ready()
            if self._stop_requested.is_set():
                self._commit_audio()
            return

        if event_type == "input_audio_buffer.committed":
            self._committed_item_id = getattr(event, "item_id", None)
            return

        if event_type == "conversation.item.input_audio_transcription.delta":
            item_id = getattr(event, "item_id", "")
            delta = getattr(event, "delta", "") or ""
            if not delta:
                return

            current = self._partial_transcripts.get(item_id, "")
            updated = current + delta
            if item_id:
                self._partial_transcripts[item_id] = updated
            self._on_partial(updated)
            return

        if event_type == "conversation.item.input_audio_transcription.completed":
            item_id = getattr(event, "item_id", "")
            if self._committed_item_id and item_id and item_id != self._committed_item_id:
                return

            transcript = (getattr(event, "transcript", "") or "").strip()
            if not transcript and item_id:
                transcript = self._partial_transcripts.get(item_id, "").strip()
            if item_id:
                self._partial_transcripts[item_id] = transcript

            usage = getattr(event, "usage", None)
            duration_seconds = self._extract_duration_seconds(usage)
            cost_estimate = (duration_seconds / 60.0) * self._cost_per_minute

            with self._state_lock:
                if self._final_sent:
                    return
                self._final_sent = True

            self._on_final(
                TranscriptionResult(
                    text=transcript,
                    duration_seconds=duration_seconds,
                    cost_estimate=cost_estimate,
                    provider=self._provider_name,
                    model=self._model,
                    language=self._language,
                )
            )
            return

        if event_type == "conversation.item.input_audio_transcription.failed":
            item_id = getattr(event, "item_id", "")
            if self._committed_item_id and item_id and item_id != self._committed_item_id:
                return

            error = getattr(event, "error", None)
            message = getattr(error, "message", None) or "OpenAI Realtime transcription failed"
            self._notify_error(RuntimeError(message))
            return

        if event_type == "error":
            error = getattr(event, "error", None)
            message = getattr(error, "message", None) or "OpenAI Realtime websocket error"
            self._notify_error(RuntimeError(message))

    def _flush_pending_audio(self) -> None:
        """Send any audio collected while the socket was connecting."""
        pending: list[tuple[str, float]]
        with self._state_lock:
            pending = list(self._pending_audio)
            self._pending_audio.clear()
            self._pending_audio_seconds = 0.0

        for encoded_audio, duration_seconds in pending:
            self._append_audio(encoded_audio, duration_seconds)

    def _append_audio(self, encoded_audio: str, duration_seconds: float) -> None:
        """Append one base64 PCM16 audio chunk to the input buffer."""
        if self._closed.is_set():
            return

        try:
            with self._connection_lock:
                if self._connection is None:
                    return
                self._connection.input_audio_buffer.append(audio=encoded_audio)
            self._sent_audio_seconds += duration_seconds
        except Exception as e:
            self._notify_error(RuntimeError(f"OpenAI Realtime audio append failed: {e}"))

    def _commit_audio(self) -> None:
        """Commit the current input buffer once."""
        with self._state_lock:
            if self._commit_sent or self._closed.is_set():
                return
            self._commit_sent = True

        try:
            with self._connection_lock:
                if self._connection is None:
                    return
                self._connection.input_audio_buffer.commit()
        except Exception as e:
            self._notify_error(RuntimeError(f"OpenAI Realtime audio commit failed: {e}"))

    def _notify_error(self, error: Exception) -> None:
        """Emit the first terminal error to the app."""
        with self._state_lock:
            if self._error_sent or self._final_sent:
                return
            self._error_sent = True
        self._on_error(error)

    def _extract_duration_seconds(self, usage: Any) -> float:
        """Extract billed or estimated duration from the event."""
        seconds = self._read_usage_number(usage, ("seconds", "duration_seconds", "audio_seconds"))
        if seconds is not None:
            return seconds

        milliseconds = self._read_usage_number(usage, ("duration_ms", "audio_duration_ms"))
        if milliseconds is not None:
            return milliseconds / 1000.0

        return self._sent_audio_seconds

    @staticmethod
    def _read_usage_number(usage: Any, field_names: tuple[str, ...]) -> Optional[float]:
        """Read a numeric usage field from either an SDK object or a raw dict."""
        if usage is None:
            return None

        for field_name in field_names:
            if isinstance(usage, dict):
                value = usage.get(field_name)
            else:
                value = getattr(usage, field_name, None)
            if isinstance(value, (int, float)):
                return float(value)

        return None

    @classmethod
    def _encode_audio_chunk(cls, audio_chunk: Any, sample_rate: int) -> tuple[str, float]:
        """Resample float32 microphone audio to 24 kHz mono PCM16 and base64-encode it."""
        if audio_chunk is None or sample_rate <= 0:
            return "", 0.0

        chunk = np.asarray(audio_chunk, dtype=np.float32)
        if chunk.size == 0:
            return "", 0.0

        if chunk.ndim == 2:
            mono = chunk.mean(axis=1)
        else:
            mono = chunk.reshape(-1)

        mono = np.clip(mono, -1.0, 1.0)

        if sample_rate != cls.TARGET_SAMPLE_RATE:
            gcd = math.gcd(sample_rate, cls.TARGET_SAMPLE_RATE)
            up = cls.TARGET_SAMPLE_RATE // gcd
            down = sample_rate // gcd
            mono = resample_poly(mono, up, down).astype(np.float32)

        pcm16 = (mono * 32767.0).astype("<i2")
        encoded = base64.b64encode(pcm16.tobytes()).decode("ascii")
        duration_seconds = len(mono) / float(cls.TARGET_SAMPLE_RATE)
        return encoded, duration_seconds


class OpenAIRealtimeProvider(TranscriptionProvider):
    """OpenAI transcription provider backed by the Realtime API."""

    name = "openai_realtime"
    display_name = "OpenAI Realtime"
    DEFAULT_MODEL = "gpt-4o-mini-transcribe"

    MODELS = [
        {
            "id": "gpt-4o-mini-transcribe",
            "name": "GPT-4o Mini Transcribe",
            "description": "True live dictation with the fastest OpenAI transcription model",
            "cost_per_minute": 0.003,
            "recommended": True,
        },
        {
            "id": "gpt-4o-transcribe",
            "name": "GPT-4o Transcribe",
            "description": "Higher-accuracy live dictation for noisy or complex speech",
            "cost_per_minute": 0.006,
        },
    ]

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = self._normalize_model(model)

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        """Fallback one-shot transcription if the app calls this provider synchronously."""
        batch_provider = OpenAITranscribeProvider(model=self.model)
        result = batch_provider.transcribe(audio_bytes)
        return TranscriptionResult(
            text=result.text,
            duration_seconds=result.duration_seconds,
            cost_estimate=result.cost_estimate,
            provider=self.name,
            model=result.model,
            language=result.language,
        )

    def is_configured(self) -> bool:
        """OpenAI Realtime reuses the standard OpenAI API key."""
        return get_api_key("openai") is not None

    def get_models(self) -> list[dict]:
        """Return supported Realtime transcription models."""
        return self.MODELS

    def set_model(self, model_id: str) -> None:
        """Select the active Realtime transcription model."""
        self.model = self._normalize_model(model_id)

    def get_current_model(self) -> str:
        """Return the currently selected Realtime model."""
        return self.model

    def supports_live_input(self) -> bool:
        """OpenAI Realtime supports true live microphone input."""
        return True

    def create_live_session(
        self,
        *,
        on_partial: Callable[[str], None],
        on_final: Callable[[TranscriptionResult], None],
        on_error: Callable[[Exception], None],
        on_ready: Optional[Callable[[], None]] = None,
        language: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> LiveTranscriptionSession:
        """Create a live OpenAI Realtime session for a single turn."""
        api_key = get_api_key("openai")
        if not api_key:
            raise ValueError("OpenAI API key not configured")

        model_config = self._get_model_config(self.model)
        return OpenAIRealtimeSession(
            api_key=api_key,
            model=self.model,
            provider_name=self.name,
            cost_per_minute=model_config["cost_per_minute"],
            on_partial=on_partial,
            on_final=on_final,
            on_error=on_error,
            on_ready=on_ready,
            language=language,
            prompt=prompt,
        )

    @classmethod
    def _normalize_model(cls, model_id: str) -> str:
        """Normalize the configured model to a supported Realtime model."""
        if any(model["id"] == model_id for model in cls.MODELS):
            return model_id
        return cls.DEFAULT_MODEL

    @classmethod
    def _get_model_config(cls, model_id: str) -> dict:
        """Look up the model metadata for pricing and labels."""
        return next(
            (model for model in cls.MODELS if model["id"] == model_id),
            cls.MODELS[0],
        )
