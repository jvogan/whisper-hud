"""Tests for the OpenAI live speech-translation provider."""

import json
import threading

import numpy as np
import pytest

from whisper_hud.providers.openai_translate_live import (
    OpenAITranslateLiveSession,
    PROVIDER_NAME,
    SUPPORTED_TARGET_LANGUAGES,
    TRANSLATE_LIVE_COST_PER_MINUTE,
    TRANSLATE_LIVE_MODEL,
    create_live_translation_session,
    is_supported_target_language,
    normalize_target_language,
)


class _RecvClosed(Exception):
    """Sentinel raised by the fake socket when its script is exhausted."""


class FakeWebSocket:
    """Deterministic stand-in for a websockets sync connection.

    ``recv()`` pops the next scripted JSON string. When the script runs out it
    either blocks on a caller-controlled event (default) or raises
    ``_RecvClosed`` to simulate a dropped socket, depending on ``raise_on_end``.
    """

    def __init__(self, script, *, raise_on_end=False):
        self._script = list(script)
        self._raise_on_end = raise_on_end
        self.sent = []
        self.closed = False
        self._release = threading.Event()

    def send(self, message):
        self.sent.append(json.loads(message))

    def recv(self, timeout=None):
        if self._script:
            return self._script.pop(0)
        if self._raise_on_end:
            raise _RecvClosed("socket closed")
        if timeout is not None:
            if self._release.wait(timeout=timeout):
                raise _RecvClosed("released")
            raise TimeoutError("timed out waiting for websocket frame")
        # Block until the test closes the session, then unblock the run loop.
        self._release.wait(timeout=0.5)
        raise _RecvClosed("released")

    def close(self):
        self.closed = True
        self._release.set()

    def sent_of_type(self, event_type):
        return [frame for frame in self.sent if frame.get("type") == event_type]


def _make_session(script=None, *, target_language="es", raise_on_end=False, connect_factory=None):
    partials = []
    finals = []
    errors = []
    ready = []

    sockets = []

    if connect_factory is None:

        def connect_factory(url, headers):  # noqa: ARG001 - signature seam
            socket = FakeWebSocket(script or [], raise_on_end=raise_on_end)
            sockets.append(socket)
            return socket

    session = OpenAITranslateLiveSession(
        api_key="sk-test",
        target_language=target_language,
        on_partial=partials.append,
        on_final=finals.append,
        on_error=errors.append,
        on_ready=lambda: ready.append(True),
        connect_factory=connect_factory,
    )
    return session, partials, finals, errors, ready, sockets


def _run_session_to_completion(session, timeout=1.0):
    """Start the session and join its run thread."""
    session.start()
    session._thread.join(timeout=timeout)
    assert not session._thread.is_alive(), "run thread did not terminate"


# ---------------------------------------------------------------------------
# Direct handler-level tests (no thread): exercise event routing precisely.
# ---------------------------------------------------------------------------


def test_readiness_flushes_preconnect_audio_in_order():
    """session.updated flips ready, calls on_ready, and flushes buffered audio."""
    session, _, _, _, ready, _ = _make_session()
    socket = FakeWebSocket([])
    session._websocket = socket

    first = np.array([0.25, -0.25], dtype=np.float32)
    second = np.array([0.5, -0.5], dtype=np.float32)
    session.push_audio(first, sample_rate=24000)
    session.push_audio(second, sample_rate=24000)

    assert len(session._pending_audio) == 2
    assert session.is_ready() is False

    session._handle_message(json.dumps({"type": "session.updated"}))

    assert ready == [True]
    assert session.is_ready() is True
    appends = socket.sent_of_type("session.input_audio_buffer.append")
    assert len(appends) == 2
    # Order preserved: first chunk's payload precedes the second.
    assert appends[0]["audio"] != appends[1]["audio"]
    assert all("audio" in frame for frame in appends)


def test_readiness_fallback_on_unknown_first_event():
    """An unknown first server event must still flip readiness."""
    session, _, _, _, ready, _ = _make_session()
    session._websocket = FakeWebSocket([])

    session._handle_message(json.dumps({"type": "some.undocumented.ack"}))

    assert session.is_ready() is True
    assert ready == [True]


def test_session_update_payload_carries_target_language():
    """The session.update frame must request the target output language."""
    script = [json.dumps({"type": "session.updated"}), json.dumps({"type": "session.closed"})]
    session, _, _, _, _, sockets = _make_session(script=script, target_language="pt-BR")

    _run_session_to_completion(session)

    update = sockets[0].sent_of_type("session.update")
    assert len(update) == 1
    assert update[0]["session"]["audio"]["output"]["language"] == "pt"


def test_output_transcript_deltas_accumulate_into_cumulative_partials():
    """Translated deltas accumulate; on_partial gets cumulative text each time."""
    session, partials, _, _, _, _ = _make_session()
    session._websocket = FakeWebSocket([])
    session._ready.set()

    session._handle_message(json.dumps({"type": "session.output_transcript.delta", "delta": "Hola"}))
    session._handle_message(json.dumps({"type": "session.output_transcript.delta", "delta": " mundo"}))

    assert partials == ["Hola", "Hola mundo"]


def test_input_transcript_deltas_accumulate_as_source_text():
    """Source-language deltas accumulate without emitting partials."""
    session, partials, _, _, _, _ = _make_session()
    session._websocket = FakeWebSocket([])
    session._ready.set()

    session._handle_message(json.dumps({"type": "session.input_transcript.delta", "delta": "Hello"}))
    session._handle_message(json.dumps({"type": "session.input_transcript.delta", "delta": " world"}))

    assert session._source_transcript == "Hello world"
    assert partials == []


def test_output_audio_deltas_are_ignored():
    """Translated speech audio frames are ignored for this text-only feature."""
    session, partials, finals, errors, _, _ = _make_session()
    session._websocket = FakeWebSocket([])
    session._ready.set()

    session._handle_message(json.dumps({"type": "session.output_audio.delta", "delta": "Zm9v"}))

    assert partials == []
    assert finals == []
    assert errors == []


def test_unknown_event_after_ready_is_ignored():
    """Unknown event types after readiness are silently dropped."""
    session, partials, finals, errors, _, _ = _make_session()
    session._websocket = FakeWebSocket([])
    session._ready.set()

    session._handle_message(json.dumps({"type": "totally.unknown"}))

    assert partials == [] and finals == [] and errors == []


def test_finalize_builds_translated_result_with_cost_and_source():
    """session.closed yields one final with translated text, source, and exact cost."""
    session, _, finals, errors, _, _ = _make_session(target_language="es")
    session._websocket = FakeWebSocket([])
    session._ready.set()

    # 24000 samples of silence at 24 kHz = exactly 1.0s of sent audio.
    one_second = np.zeros(24000, dtype=np.float32)
    session.push_audio(one_second, sample_rate=24000)

    session._handle_message(json.dumps({"type": "session.input_transcript.delta", "delta": "good day"}))
    session._handle_message(json.dumps({"type": "session.output_transcript.delta", "delta": " buen "}))
    session._handle_message(json.dumps({"type": "session.output_transcript.delta", "delta": "dia "}))
    session._handle_message(json.dumps({"type": "session.closed"}))

    assert errors == []
    assert len(finals) == 1
    result = finals[0]
    assert result.text == "buen dia"
    assert result.source_text == "good day"
    assert result.language == "es"
    assert result.provider == PROVIDER_NAME
    assert result.model == TRANSLATE_LIVE_MODEL
    assert result.duration_seconds == pytest.approx(1.0)
    assert result.cost_estimate == pytest.approx(1.0 / 60.0 * TRANSLATE_LIVE_COST_PER_MINUTE)
    assert result.cost_estimate == pytest.approx(0.034 / 60.0)


def test_finalize_emits_only_once():
    """A second session.closed must not produce a second final."""
    session, _, finals, _, _, _ = _make_session()
    session._websocket = FakeWebSocket([])
    session._ready.set()

    session._handle_message(json.dumps({"type": "session.closed"}))
    session._handle_message(json.dumps({"type": "session.closed"}))

    assert len(finals) == 1


def test_source_text_is_none_when_no_input_transcript():
    """No source deltas -> source_text is None, not an empty string."""
    session, _, finals, _, _, _ = _make_session()
    session._websocket = FakeWebSocket([])
    session._ready.set()

    session._handle_message(json.dumps({"type": "session.output_transcript.delta", "delta": "x"}))
    session._handle_message(json.dumps({"type": "session.closed"}))

    assert finals[0].source_text is None


def test_request_stop_sends_close_once_even_when_called_twice():
    """request_stop sends exactly one session.close even when repeated."""
    session, _, _, _, _, _ = _make_session()
    socket = FakeWebSocket([])
    session._websocket = socket
    session._ready.set()

    session.request_stop()
    session.request_stop()

    assert len(socket.sent_of_type("session.close")) == 1


def test_request_stop_before_ready_defers_close_until_readiness():
    """A stop requested before readiness is sent right after the readiness flush."""
    session, _, _, _, _, _ = _make_session()
    socket = FakeWebSocket([])
    session._websocket = socket

    session.request_stop()  # not ready yet -> nothing on the wire
    assert socket.sent_of_type("session.close") == []

    session._handle_message(json.dumps({"type": "session.updated"}))

    assert len(socket.sent_of_type("session.close")) == 1


def test_error_event_emits_on_error_once_and_never_finalizes():
    """An error frame calls on_error exactly once and suppresses on_final."""
    session, _, finals, errors, _, _ = _make_session()
    session._websocket = FakeWebSocket([])
    session._ready.set()

    session._handle_message(json.dumps({"type": "error", "error": {"message": "invalid api key"}}))
    # A late close must not produce a final after an error.
    session._handle_message(json.dumps({"type": "session.closed"}))

    assert len(errors) == 1
    assert isinstance(errors[0], Exception)
    assert "OpenAI Live Translation" in str(errors[0])
    assert finals == []


# ---------------------------------------------------------------------------
# Thread-level tests: real run loop over the fake socket.
# ---------------------------------------------------------------------------


def test_recv_failure_mid_session_emits_on_error():
    """A socket that dies before session.closed (not user-closed) -> on_error."""
    # session.updated then the script is exhausted and recv() raises.
    script = [json.dumps({"type": "session.updated"})]
    session, _, finals, errors, _, _ = _make_session(script=script, raise_on_end=True)

    _run_session_to_completion(session)

    assert finals == []
    assert len(errors) == 1
    assert "OpenAI Live Translation" in str(errors[0])


def test_idle_timeout_before_ready_emits_on_error(monkeypatch):
    """A server that never acknowledges the session must not leave the worker alive forever."""
    monkeypatch.setattr(OpenAITranslateLiveSession, "RECV_POLL_SECONDS", 0.01)
    monkeypatch.setattr(OpenAITranslateLiveSession, "READY_IDLE_TIMEOUT_SECONDS", 0.02)

    session, _, finals, errors, ready, sockets = _make_session(script=[])

    _run_session_to_completion(session)

    assert ready == []
    assert finals == []
    assert len(errors) == 1
    assert "OpenAI Live Translation" in str(errors[0])
    assert "timed out" in str(errors[0]).lower()
    assert sockets[0].closed is True


def test_clean_close_event_does_not_error():
    """A normal session.closed finalizes without surfacing an error."""
    script = [json.dumps({"type": "session.updated"}), json.dumps({"type": "session.closed"})]
    session, _, finals, errors, ready, _ = _make_session(script=script)

    _run_session_to_completion(session)

    assert errors == []
    assert ready == [True]
    assert len(finals) == 1


def test_close_is_idempotent_and_push_audio_is_noop_afterwards():
    """close() is safe to call repeatedly; push_audio sends nothing after close."""
    session, _, _, _, _, _ = _make_session()
    socket = FakeWebSocket([])
    session._websocket = socket
    session._ready.set()

    session.close()
    session.close()  # idempotent: no raise, still closed
    assert socket.closed is True

    socket.sent.clear()
    session.push_audio(np.zeros(2400, dtype=np.float32), sample_rate=24000)
    assert socket.sent == []


def test_user_requested_close_does_not_emit_error_on_recv_drop():
    """When the user closes the session, a recv drop must not surface as an error."""
    session, _, finals, errors, _, sockets = _make_session(
        script=[json.dumps({"type": "session.updated"})], raise_on_end=False
    )
    session.start()
    # Wait for readiness, then close from the caller side.
    assert session._ready.wait(timeout=0.5)
    session.close()

    assert not session._thread.is_alive()
    assert errors == []
    assert finals == []


# ---------------------------------------------------------------------------
# Helper and factory tests.
# ---------------------------------------------------------------------------


def test_supported_target_languages_is_the_models_thirteen_outputs():
    """The supported set is exactly the model's 13 output languages."""
    assert SUPPORTED_TARGET_LANGUAGES == frozenset(
        {"en", "es", "pt", "fr", "de", "it", "ja", "ko", "zh", "ru", "hi", "id", "vi"}
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("EN", "en"),
        ("pt-BR", "pt"),
        ("zh-Hans", "zh"),
        ("  Fr  ", "fr"),
        ("es_419", "es"),
        ("", ""),
    ],
)
def test_normalize_target_language_strips_region_and_case(raw, expected):
    assert normalize_target_language(raw) == expected


@pytest.mark.parametrize(
    "code,supported",
    [
        ("pt-BR", True),
        ("ZH", True),
        ("en", True),
        ("vi", True),
        ("xx", False),
        ("th", False),
        ("", False),
    ],
)
def test_is_supported_target_language(code, supported):
    assert is_supported_target_language(code) is supported


def test_create_live_translation_session_raises_on_unsupported_target():
    """The factory rejects unsupported targets before any socket work."""
    with pytest.raises(ValueError):
        create_live_translation_session(
            api_key="sk-test",
            target_language="th",
            on_partial=lambda _t: None,
            on_final=lambda _r: None,
            on_error=lambda _e: None,
        )


def test_create_live_translation_session_builds_session_for_supported_target():
    """A supported (region-suffixed) target yields a normalized session."""
    session = create_live_translation_session(
        api_key="sk-test",
        target_language="pt-BR",
        on_partial=lambda _t: None,
        on_final=lambda _r: None,
        on_error=lambda _e: None,
    )
    assert isinstance(session, OpenAITranslateLiveSession)
    assert session._target_language == "pt"
