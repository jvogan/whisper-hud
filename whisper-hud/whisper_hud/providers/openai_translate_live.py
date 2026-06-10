"""
OpenAI live speech-translation provider.

Streams microphone audio to the gpt-realtime-translate model over the
``/v1/realtime/translations`` websocket and yields translated text. The
openai SDK has no client for this endpoint, so the raw ``websockets`` sync
client carries the JSON wire protocol instead.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from typing import Any, Callable, Optional

from .base import LiveTranscriptionSession, TranscriptionResult
from .error_utils import build_provider_error_message
from .realtime_audio import REALTIME_SAMPLE_RATE, encode_pcm16_chunk
from ..logging_config import get_logger

logger = get_logger("providers.openai_translate_live")

TRANSLATE_LIVE_MODEL = "gpt-realtime-translate"
TRANSLATE_LIVE_COST_PER_MINUTE = 0.034
PROVIDER_NAME = "openai_translate_live"

TRANSLATE_LIVE_URL = f"wss://api.openai.com/v1/realtime/translations?model={TRANSLATE_LIVE_MODEL}"

# The 13 output languages the model can translate into.
SUPPORTED_TARGET_LANGUAGES = frozenset({"en", "es", "pt", "fr", "de", "it", "ja", "ko", "zh", "ru", "hi", "id", "vi"})


def normalize_target_language(code: str) -> str:
    """Lowercase and drop any region/script suffix (``pt-BR`` -> ``pt``)."""
    if not code:
        return ""
    return code.strip().lower().split("-")[0].split("_")[0]


def is_supported_target_language(code: str) -> bool:
    """Return True if the (normalized) code is one of the output languages."""
    return normalize_target_language(code) in SUPPORTED_TARGET_LANGUAGES


def _default_connect_factory(url: str, headers: dict) -> Any:
    """Open the translation websocket with the sync ``websockets`` client.

    Imported lazily so merely importing this module never pulls in the
    websockets runtime or requires a network/event loop.
    """
    from websockets.sync.client import connect

    return connect(url, additional_headers=headers)


class OpenAITranslateLiveSession(LiveTranscriptionSession):
    """One-shot live speech-translation session for a single recording turn."""

    TARGET_SAMPLE_RATE = REALTIME_SAMPLE_RATE
    PRECONNECT_BUFFER_SECONDS = 2.0

    def __init__(
        self,
        *,
        api_key: str,
        target_language: str,
        on_partial: Callable[[str], None],
        on_final: Callable[[TranscriptionResult], None],
        on_error: Callable[[Exception], None],
        on_ready: Optional[Callable[[], None]] = None,
        connect_factory: Optional[Callable[[str, dict], Any]] = None,
    ):
        self._api_key = api_key
        self._target_language = normalize_target_language(target_language)
        self._on_partial = on_partial
        self._on_final = on_final
        self._on_error = on_error
        self._on_ready = on_ready
        self._connect_factory = connect_factory or _default_connect_factory

        self._thread: Optional[threading.Thread] = None
        self._websocket: Any = None
        self._send_lock = threading.Lock()
        self._state_lock = threading.Lock()

        self._ready = threading.Event()
        self._closed = threading.Event()
        self._stop_requested = threading.Event()
        self._close_sent = False
        self._error_sent = False
        self._final_sent = False

        self._source_transcript = ""
        self._translated_transcript = ""
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
        """Return True once the remote session has acknowledged the config."""
        return self._ready.is_set()

    def push_audio(self, audio_chunk: Any, sample_rate: int) -> None:
        """Convert and queue microphone audio for the live session."""
        if self._closed.is_set() or self._stop_requested.is_set():
            return

        encoded_audio, duration_seconds = encode_pcm16_chunk(audio_chunk, sample_rate, self.TARGET_SAMPLE_RATE)
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
        """Ask the server to close the turn exactly once.

        Before readiness there is nothing to close yet; the request is
        remembered and sent right after the readiness flush.
        """
        self._stop_requested.set()
        if not self._ready.is_set():
            return
        self._send_close()

    def close(self) -> None:
        """Close the session and underlying websocket (idempotent)."""
        if self._closed.is_set():
            return
        self._closed.set()
        websocket = self._websocket
        if websocket is not None:
            try:
                websocket.close()
            except Exception:
                logger.debug("Failed to close live translation websocket cleanly", exc_info=True)

    def _run(self) -> None:
        """Own the websocket lifetime and process incoming events."""
        try:
            headers = {"Authorization": f"Bearer {self._api_key}"}
            self._websocket = self._connect_factory(TRANSLATE_LIVE_URL, headers)
            self._send_json(
                {
                    "type": "session.update",
                    "session": {"audio": {"output": {"language": self._target_language}}},
                }
            )

            while not self._closed.is_set():
                message = self._websocket.recv()
                self._handle_message(message)
                if self._final_sent:
                    break
        except Exception as e:
            # The socket dropped before a clean ``session.closed``. If the user
            # did not ask to close, surface it so the app degrades the turn to
            # its batch pipeline.
            if not self._closed.is_set():
                self._notify_error(RuntimeError(build_provider_error_message("OpenAI Live Translation", "session", e)))
        finally:
            self.close()

    def _handle_message(self, message: Any) -> None:
        """Parse a server text frame and route it to callbacks."""
        try:
            event = json.loads(message)
        except (ValueError, TypeError):
            return
        if not isinstance(event, dict):
            return

        event_type = event.get("type", "")

        if event_type in ("session.created", "session.updated"):
            self._mark_ready()
            return

        if event_type == "session.input_transcript.delta":
            delta = event.get("delta") or ""
            if delta:
                self._source_transcript += delta
            return

        if event_type == "session.output_transcript.delta":
            delta = event.get("delta") or ""
            if delta:
                self._translated_transcript += delta
                self._on_partial(self._translated_transcript)
            return

        if event_type == "session.output_audio.delta":
            # Translated speech audio; this is a text-only feature.
            return

        if event_type == "session.closed":
            self._finalize()
            return

        if event_type == "error":
            error = event.get("error")
            message_text = None
            if isinstance(error, dict):
                message_text = error.get("message")
            self._notify_error(
                RuntimeError(
                    build_provider_error_message(
                        "OpenAI Live Translation", "session", RuntimeError(message_text or "request failed")
                    )
                )
            )
            return

        # Defensive: an undocumented ack as the first event must not hang the
        # session waiting for a readiness type that never comes.
        if not self._ready.is_set():
            self._mark_ready()

    def _mark_ready(self) -> None:
        """Flip readiness once, flush buffered audio, and signal the app."""
        if self._ready.is_set():
            return
        self._ready.set()
        self._flush_pending_audio()
        if self._on_ready:
            self._on_ready()
        if self._stop_requested.is_set():
            self._send_close()

    def _flush_pending_audio(self) -> None:
        """Send any audio collected while the socket was connecting."""
        with self._state_lock:
            pending = list(self._pending_audio)
            self._pending_audio.clear()
            self._pending_audio_seconds = 0.0

        for encoded_audio, duration_seconds in pending:
            self._append_audio(encoded_audio, duration_seconds)

    def _append_audio(self, encoded_audio: str, duration_seconds: float) -> None:
        """Send one base64 PCM16 audio chunk to the input buffer."""
        if self._closed.is_set():
            return
        try:
            self._send_json({"type": "session.input_audio_buffer.append", "audio": encoded_audio})
            self._sent_audio_seconds += duration_seconds
        except Exception as e:
            self._notify_error(RuntimeError(build_provider_error_message("OpenAI Live Translation", "audio append", e)))

    def _send_close(self) -> None:
        """Tell the server to close the turn exactly once."""
        with self._state_lock:
            if self._close_sent or self._closed.is_set():
                return
            self._close_sent = True
        try:
            self._send_json({"type": "session.close"})
        except Exception as e:
            self._notify_error(
                RuntimeError(build_provider_error_message("OpenAI Live Translation", "session close", e))
            )

    def _send_json(self, payload: dict) -> None:
        """Serialize and send one JSON frame, serialized against concurrent sends."""
        with self._send_lock:
            if self._websocket is None:
                return
            self._websocket.send(json.dumps(payload))

    def _finalize(self) -> None:
        """Emit the final translated result exactly once."""
        with self._state_lock:
            if self._final_sent or self._error_sent:
                return
            self._final_sent = True

        duration_seconds = self._sent_audio_seconds
        cost_estimate = (duration_seconds / 60.0) * TRANSLATE_LIVE_COST_PER_MINUTE
        source_text = self._source_transcript.strip() or None

        self._on_final(
            TranscriptionResult(
                text=self._translated_transcript.strip(),
                duration_seconds=duration_seconds,
                cost_estimate=cost_estimate,
                provider=PROVIDER_NAME,
                model=TRANSLATE_LIVE_MODEL,
                language=self._target_language,
                source_text=source_text,
            )
        )

    def _notify_error(self, error: Exception) -> None:
        """Emit the first terminal error to the app."""
        with self._state_lock:
            if self._error_sent or self._final_sent:
                return
            self._error_sent = True
        self._on_error(error)


def create_live_translation_session(
    *,
    api_key: str,
    target_language: str,
    on_partial: Callable[[str], None],
    on_final: Callable[[TranscriptionResult], None],
    on_error: Callable[[Exception], None],
    on_ready: Optional[Callable[[], None]] = None,
) -> OpenAITranslateLiveSession:
    """Build a live translation session, validating the target language.

    Callers are expected to validate the target up front, but the guard is
    repeated here so an unsupported code can never reach the wire.
    """
    if not is_supported_target_language(target_language):
        raise ValueError(f"Unsupported live translation target language: {target_language!r}")

    return OpenAITranslateLiveSession(
        api_key=api_key,
        target_language=target_language,
        on_partial=on_partial,
        on_final=on_final,
        on_error=on_error,
        on_ready=on_ready,
    )
