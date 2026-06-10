"""
Voice assistant mode backed by OpenAI's gpt-realtime conversation model.

Holds a long-lived realtime websocket conversation: microphone audio streams
up, spoken replies stream back through :class:`PCM16Player`, and server VAD
drives turn-taking (no manual commits). The model may request a single safe
tool, ``paste_text``, which is the only side effect this module ever performs
on the user's machine.

Security: ``paste_text`` is the ONLY executable tool. Model output is never
routed to a shell, a file API, or ``eval``; every model-supplied string is
treated as opaque data. The ``paste_callback`` is the single side-effect
channel and is the integrator's responsibility to keep safe.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Callable, Optional

from openai import OpenAI

from .audio_output import PCM16Player
from .logging_config import get_logger
from .providers.error_utils import build_provider_error_message
from .providers.http_client_utils import (
    OPENAI_API_BASE_URL,
    OPENAI_WEBSOCKET_BASE_URL,
    build_hardened_http_client,
)
from .providers.realtime_audio import (
    REALTIME_SAMPLE_RATE,
    decode_pcm16_chunk,
    encode_pcm16_chunk,
)
from .recorder import AudioRecorder

logger = get_logger("assistant")

_CLIENT_TIMEOUT_SECONDS = 30.0

_DEFAULT_INSTRUCTIONS = (
    "You are a voice assistant living inside a dictation app on this Mac. "
    "You can paste text into the user's currently focused application with the "
    "paste_text tool when the user asks you to. Keep spoken replies brief and "
    "conversational."
)

# The single tool the model is ever allowed to invoke.
_PASTE_TOOL = {
    "type": "function",
    "name": "paste_text",
    "description": "Paste the given text into the user's currently focused application.",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Exact text to paste"},
        },
        "required": ["text"],
    },
}


def _default_client(api_key: str) -> OpenAI:
    """Build the hardened OpenAI client used for the realtime conversation."""
    return OpenAI(
        api_key=api_key,
        base_url=OPENAI_API_BASE_URL,
        websocket_base_url=OPENAI_WEBSOCKET_BASE_URL,
        timeout=_CLIENT_TIMEOUT_SECONDS,
        http_client=build_hardened_http_client(_CLIENT_TIMEOUT_SECONDS),
    )


class VoiceAssistant:
    """A push-to-start / click-to-stop spoken conversation with gpt-realtime."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-realtime-2",
        voice: str = "marin",
        reasoning_effort: str = "low",
        instructions: Optional[str] = None,
        paste_tool_enabled: bool = True,
        paste_callback: Callable[[str], bool],
        on_state: Callable[[str], None],
        on_user_text: Callable[[str], None],
        on_assistant_text: Callable[[str], None],
        on_exchange: Callable[[str, str], None],
        on_error: Callable[[Exception], None],
        client_factory: Optional[Callable[[str], Any]] = None,
        recorder_factory: Optional[Callable[[], Any]] = None,
        player_factory: Optional[Callable[[], Any]] = None,
    ):
        self._api_key = api_key
        self._model = model
        self._voice = voice
        self._reasoning_effort = reasoning_effort
        self._instructions = instructions if instructions is not None else _DEFAULT_INSTRUCTIONS
        self._paste_tool_enabled = paste_tool_enabled
        self._paste_callback = paste_callback

        self._on_state = on_state
        self._on_user_text = on_user_text
        self._on_assistant_text = on_assistant_text
        self._on_exchange = on_exchange
        self._on_error = on_error

        self._client_factory = client_factory or _default_client
        self._recorder_factory = recorder_factory or AudioRecorder
        self._player_factory = player_factory or PCM16Player

        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stopping = threading.Event()
        self._active = False

        self._connection: Any = None
        self._recorder: Any = None
        self._player: Any = None

        # Per-turn transcript accumulators (touched only on the recv thread).
        self._user_text = ""
        self._assistant_text = ""

    def start(self) -> None:
        """Open the conversation in a background thread (no-op if active)."""
        with self._lock:
            if self._active:
                return
            self._active = True
            self._stopping.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

        self._emit_state("connecting")

    def stop(self) -> None:
        """Tear down mic, playback, and the connection (idempotent, thread-safe)."""
        with self._lock:
            if not self._active:
                return
            self._active = False
            self._stopping.set()
            thread = self._thread
            self._thread = None

        self._teardown()

        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5.0)

        self._emit_state("stopped")

    def is_active(self) -> bool:
        """Return True while the conversation thread owns a connection."""
        return self._active

    def _run(self) -> None:
        """Own the connection lifetime and pump realtime events until stop."""
        try:
            with self._client_factory(self._api_key).realtime.connect(model=self._model) as connection:
                self._connection = connection
                # stop() may have arrived during the (network-bound) connect
                # handshake, when _teardown found every resource still None. Bail
                # before opening the mic/player so they are never started; the
                # finally below still closes the connection we just opened.
                if self._stopping.is_set():
                    return
                connection.session.update(session=self._build_session_payload())

                self._player = self._player_factory()
                self._player.start()

                self._recorder = self._recorder_factory()
                self._recorder.start(on_audio_chunk=self._on_audio_chunk)

                while not self._stopping.is_set():
                    event = connection.recv()
                    self._handle_event(event)
        except Exception as exc:
            # A stop() closes the connection, which makes recv() raise; that
            # exit is expected and must stay silent.
            if not self._stopping.is_set():
                self._handle_abnormal_exit(exc)
        finally:
            # Own every resource on every exit path: if stop() raced ahead of
            # resource assignment (so its _teardown found None) the streams we
            # opened afterwards would otherwise leak. _teardown is idempotent,
            # so the double call from the stop()/abnormal paths is a safe no-op.
            self._teardown()

    def _build_session_payload(self) -> dict[str, Any]:
        """Build the session.update payload (kept in one place for tuning)."""
        payload: dict[str, Any] = {
            "type": "realtime",
            "instructions": self._instructions,
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": REALTIME_SAMPLE_RATE},
                    "transcription": {"model": "gpt-realtime-whisper"},
                    "turn_detection": {"type": "server_vad"},
                },
                "output": {
                    "format": {"type": "audio/pcm", "rate": REALTIME_SAMPLE_RATE},
                    "voice": self._voice,
                },
            },
            "reasoning": {"effort": self._reasoning_effort},
        }
        if self._paste_tool_enabled:
            payload["tools"] = [dict(_PASTE_TOOL)]
            payload["tool_choice"] = "auto"
        return payload

    def _on_audio_chunk(self, chunk: Any, sample_rate: int) -> None:
        """Encode and forward one microphone chunk to the input buffer."""
        if self._stopping.is_set():
            return
        encoded, _ = encode_pcm16_chunk(chunk, sample_rate, REALTIME_SAMPLE_RATE)
        if not encoded:
            return
        connection = self._connection
        if connection is None:
            return
        try:
            connection.input_audio_buffer.append(audio=encoded)
        except Exception:
            # Never let a send failure tear down the audio thread.
            logger.debug("Failed to append microphone audio to realtime buffer", exc_info=True)

    def _handle_event(self, event: Any) -> None:
        """Route one realtime event to playback, transcripts, or tool dispatch."""
        event_type = getattr(event, "type", "")

        if event_type in ("session.created", "session.updated"):
            self._emit_state("listening")
            return

        if event_type == "input_audio_buffer.speech_started":
            # Barge-in: cut off any in-flight reply immediately.
            if self._player is not None:
                self._player.flush()
            self._emit_state("listening")
            return

        if event_type == "response.created":
            self._assistant_text = ""
            self._emit_state("responding")
            return

        if event_type in ("response.output_audio.delta", "response.audio.delta"):
            decoded = decode_pcm16_chunk(getattr(event, "delta", "") or "")
            if decoded and self._player is not None:
                self._player.enqueue(decoded)
            return

        if event_type in (
            "response.output_audio_transcript.delta",
            "response.audio_transcript.delta",
        ):
            self._assistant_text += getattr(event, "delta", "") or ""
            self._on_assistant_text(self._assistant_text)
            return

        if event_type == "conversation.item.input_audio_transcription.completed":
            text = (getattr(event, "transcript", "") or "").strip()
            self._user_text = text
            self._on_user_text(text)
            return

        if event_type == "response.done":
            if self._user_text or self._assistant_text:
                self._on_exchange(self._user_text, self._assistant_text)
            self._user_text = ""
            self._assistant_text = ""
            self._emit_state("listening")
            return

        if event_type == "response.function_call_arguments.done":
            self._handle_function_call(event)
            return

        if event_type == "error":
            error = getattr(event, "error", None)
            message = getattr(error, "message", None) or "request failed"
            wrapped = RuntimeError(build_provider_error_message("OpenAI Assistant", "session", RuntimeError(message)))
            self._on_error(wrapped)
            # The SDK may auto-reconnect; do not stop the session here.
            return

        # Unknown events are ignored.

    def _handle_function_call(self, event: Any) -> None:
        """Execute the paste_text tool (and nothing else), then answer the model."""
        call_id = getattr(event, "call_id", None)
        name = getattr(event, "name", "")
        raw_arguments = getattr(event, "arguments", "") or ""

        result_payload = self._dispatch_tool(name, raw_arguments)

        connection = self._connection
        if connection is None:
            return
        try:
            connection.conversation.item.create(
                item={
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result_payload),
                }
            )
            connection.response.create()
        except Exception:
            logger.debug("Failed to return function call output", exc_info=True)

    def _dispatch_tool(self, name: str, raw_arguments: str) -> dict[str, Any]:
        """Resolve a tool call to a result payload without unsafe execution.

        Only ``paste_text`` is ever executed, and only when the tool is
        enabled. Any other tool name, or a disabled tool, returns an
        ``unavailable`` error without touching the machine.
        """
        if name != "paste_text" or not self._paste_tool_enabled:
            return {"ok": False, "error": "unavailable"}

        try:
            arguments = json.loads(raw_arguments)
        except (ValueError, TypeError):
            return {"ok": False, "error": "invalid arguments"}

        if not isinstance(arguments, dict):
            return {"ok": False, "error": "invalid arguments"}

        text = arguments.get("text")
        if not isinstance(text, str):
            return {"ok": False, "error": "invalid arguments"}

        try:
            ok = bool(self._paste_callback(text))
        except Exception:
            logger.debug("paste_text callback raised", exc_info=True)
            return {"ok": False, "error": "paste failed"}

        if ok:
            return {"ok": True}
        return {"ok": False, "error": "paste failed"}

    def _handle_abnormal_exit(self, exc: Exception) -> None:
        """Report an unexpected loop exit, then fully clean up."""
        with self._lock:
            self._active = False
            self._stopping.set()
        wrapped = RuntimeError(build_provider_error_message("OpenAI Assistant", "session", exc))
        self._on_error(wrapped)
        self._teardown()
        self._emit_state("error")

    def _teardown(self) -> None:
        """Stop mic first, then playback, then close the connection. Never raises."""
        recorder = self._recorder
        self._recorder = None
        if recorder is not None:
            try:
                recorder.stop()
            except Exception:
                logger.debug("Failed to stop recorder", exc_info=True)

        player = self._player
        self._player = None
        if player is not None:
            try:
                player.stop()
            except Exception:
                logger.debug("Failed to stop audio player", exc_info=True)

        connection = self._connection
        self._connection = None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                logger.debug("Failed to close realtime connection", exc_info=True)

    def _emit_state(self, state: str) -> None:
        """Deliver a lifecycle state to the integrator without crashing."""
        try:
            self._on_state(state)
        except Exception:
            logger.debug("on_state callback raised", exc_info=True)
