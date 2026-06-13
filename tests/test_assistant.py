"""Tests for the gpt-realtime voice assistant."""

import json
import threading
import time
from types import SimpleNamespace
from typing import Optional
from unittest.mock import MagicMock

import numpy as np

from whisper_hud.providers.realtime_audio import (
    REALTIME_SAMPLE_RATE,
    decode_pcm16_chunk,
    encode_pcm16_chunk,
)


class _RecvClosed(Exception):
    """Sentinel raised by FakeConnection.recv() once the script is exhausted."""


class FakeConnection:
    """Scripted realtime connection: yields events, then blocks until closed."""

    def __init__(self, events=None):
        self._events = list(events or [])
        self.session = MagicMock()
        self.response = MagicMock()
        self.conversation = MagicMock()
        self.input_audio_buffer = MagicMock()
        self.closed = threading.Event()
        self._exhausted = threading.Event()
        # Optional connect gate: when armed, __enter__ blocks (like a real
        # network handshake) until the test releases it, so a stop() can be made
        # to race the in-flight connect. entered fires once __enter__ proceeds.
        self._connect_gate: Optional[threading.Event] = None
        self.entered = threading.Event()

    def arm_connect_gate(self) -> threading.Event:
        """Block __enter__ until the returned event is set."""
        self._connect_gate = threading.Event()
        return self._connect_gate

    def __enter__(self):
        self.entered.set()
        if self._connect_gate is not None:
            self._connect_gate.wait(2.0)
        return self

    def __exit__(self, *exc):
        return False

    def recv(self):
        if self.closed.is_set():
            raise _RecvClosed()
        if self._events:
            return self._events.pop(0)
        # Script exhausted: park until stop() closes the connection so the
        # recv-loop behaves like a real long-lived conversation.
        self._exhausted.set()
        while not self.closed.is_set():
            time.sleep(0.005)
        raise _RecvClosed()

    def close(self):
        self.closed.set()

    def wait_exhausted(self, timeout=2.0):
        return self._exhausted.wait(timeout)


class FakeRecorder:
    """Captures the on_audio_chunk handler the assistant registers."""

    def __init__(self):
        self.on_audio_chunk = None
        self.started = False
        self.stopped = False

    def start(self, on_audio_chunk=None, **kwargs):
        self.started = True
        self.on_audio_chunk = on_audio_chunk

    def stop(self):
        self.stopped = True
        return b""


class FakePlayer:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.enqueued: list[bytes] = []
        self.flushed = 0

    def start(self):
        self.started = True

    def enqueue(self, pcm_bytes):
        self.enqueued.append(pcm_bytes)

    def flush(self):
        self.flushed += 1

    def stop(self):
        self.stopped = True

    def is_active(self):
        return self.started and not self.stopped


class Harness:
    """Builds a VoiceAssistant wired to fakes and collects all callbacks."""

    def __init__(self, **overrides):
        from whisper_hud.assistant import VoiceAssistant

        self.states: list[str] = []
        self.user_texts: list[str] = []
        self.assistant_texts: list[str] = []
        self.exchanges: list[tuple[str, str]] = []
        self.errors: list[Exception] = []
        self.paste_calls: list[str] = []

        self.connection = FakeConnection(overrides.pop("events", None))
        self.recorder = FakeRecorder()
        self.player = FakePlayer()
        self.client = MagicMock()
        self.client.realtime.connect.return_value = self.connection

        paste_result = overrides.pop("paste_result", True)

        def paste_callback(text):
            self.paste_calls.append(text)
            if isinstance(paste_result, Exception):
                raise paste_result
            return paste_result

        kwargs = dict(
            api_key="sk-test",
            paste_callback=paste_callback,
            on_state=self.states.append,
            on_user_text=self.user_texts.append,
            on_assistant_text=self.assistant_texts.append,
            on_exchange=lambda u, a: self.exchanges.append((u, a)),
            on_error=self.errors.append,
            client_factory=lambda _key: self.client,
            recorder_factory=lambda: self.recorder,
            player_factory=lambda: self.player,
        )
        kwargs.update(overrides)
        self.assistant = VoiceAssistant(**kwargs)

    def run_script(self):
        """Start the assistant and wait for the scripted events to drain."""
        self.assistant.start()
        assert self.connection.wait_exhausted(), "recv-loop never consumed the script"
        # Let the final event's side effects settle on the recv thread.
        time.sleep(0.05)

    def stop(self):
        self.assistant.stop()


def test_start_sends_session_update_with_expected_payload():
    """session.update should carry the realtime schema, VAD, voice, and tools."""
    h = Harness(voice="cedar", reasoning_effort="medium")
    h.run_script()

    payload = h.connection.session.update.call_args.kwargs["session"]
    assert payload["type"] == "realtime"
    assert payload["audio"]["input"]["turn_detection"] == {"type": "server_vad"}
    assert payload["audio"]["input"]["transcription"] == {"model": "gpt-realtime-whisper"}
    assert payload["audio"]["output"]["voice"] == "cedar"
    assert payload["reasoning"] == {"effort": "medium"}
    assert payload["tools"][0]["name"] == "paste_text"
    assert payload["tool_choice"] == "auto"
    h.stop()


def test_microphone_chunk_is_encoded_and_appended():
    """The mic handler should base64-encode audio that round-trips on decode."""
    h = Harness()
    h.run_script()

    chunk = np.array([0.1, -0.2, 0.3, -0.4], dtype=np.float32)
    h.recorder.on_audio_chunk(chunk, REALTIME_SAMPLE_RATE)

    assert h.connection.input_audio_buffer.append.called
    encoded = h.connection.input_audio_buffer.append.call_args.kwargs["audio"]
    decoded = decode_pcm16_chunk(encoded)
    assert len(decoded) == 8  # 4 samples * 2 bytes (PCM16)
    h.stop()


def test_audio_deltas_new_and_legacy_enqueue_decoded_bytes():
    """Both the new and legacy audio-delta event names should reach the player."""
    import base64

    pcm = np.array([5, -5, 9], dtype="<i2").tobytes()
    encoded = base64.b64encode(pcm).decode("ascii")
    h = Harness(
        events=[
            SimpleNamespace(type="response.output_audio.delta", delta=encoded),
            SimpleNamespace(type="response.audio.delta", delta=encoded),
        ]
    )
    h.run_script()

    assert h.player.enqueued == [pcm, pcm]
    h.stop()


def test_speech_started_flushes_player():
    """A speech_started event triggers barge-in via player.flush()."""
    h = Harness(events=[SimpleNamespace(type="input_audio_buffer.speech_started")])
    h.run_script()

    assert h.player.flushed == 1
    assert "listening" in h.states
    h.stop()


def test_transcripts_accumulate_and_finalize_on_response_done():
    """Assistant deltas accumulate; response.done emits one exchange and resets."""
    h = Harness(
        events=[
            SimpleNamespace(type="response.created"),
            SimpleNamespace(type="response.output_audio_transcript.delta", delta="Hel"),
            SimpleNamespace(type="response.output_audio_transcript.delta", delta="lo"),
            SimpleNamespace(
                type="conversation.item.input_audio_transcription.completed",
                transcript=" hi there ",
            ),
            SimpleNamespace(type="response.done"),
        ]
    )
    h.run_script()

    assert h.assistant_texts == ["Hel", "Hello"]
    assert h.user_texts == ["hi there"]
    assert h.exchanges == [("hi there", "Hello")]
    # Accumulators reset after the exchange fires.
    assert h.assistant.is_active()
    h.stop()


def test_paste_text_tool_executes_and_answers_model():
    """paste_text dispatch calls the callback and returns {ok: true}."""
    args = json.dumps({"text": "hello world"})
    h = Harness(
        events=[
            SimpleNamespace(
                type="response.function_call_arguments.done",
                call_id="call-1",
                name="paste_text",
                arguments=args,
            )
        ]
    )
    h.run_script()

    assert h.paste_calls == ["hello world"]
    item = h.connection.conversation.item.create.call_args.kwargs["item"]
    assert item["type"] == "function_call_output"
    assert item["call_id"] == "call-1"
    assert json.loads(item["output"]) == {"ok": True}
    assert h.connection.response.create.called
    h.stop()


def test_unknown_tool_name_is_not_executed():
    """An unknown tool returns an error without invoking the paste callback."""
    h = Harness(
        events=[
            SimpleNamespace(
                type="response.function_call_arguments.done",
                call_id="call-2",
                name="rm_rf",
                arguments=json.dumps({"text": "rm -rf /"}),
            )
        ]
    )
    h.run_script()

    assert h.paste_calls == []
    item = h.connection.conversation.item.create.call_args.kwargs["item"]
    output = json.loads(item["output"])
    assert output["ok"] is False
    assert "error" in output
    h.stop()


def test_paste_tool_disabled_has_no_tools_and_refuses_calls():
    """With the tool disabled there are no tools and calls answer {ok: false}."""
    h = Harness(
        paste_tool_enabled=False,
        events=[
            SimpleNamespace(
                type="response.function_call_arguments.done",
                call_id="call-3",
                name="paste_text",
                arguments=json.dumps({"text": "nope"}),
            )
        ],
    )
    h.run_script()

    payload = h.connection.session.update.call_args.kwargs["session"]
    assert "tools" not in payload
    assert "tool_choice" not in payload
    assert h.paste_calls == []
    output = json.loads(h.connection.conversation.item.create.call_args.kwargs["item"]["output"])
    assert output == {"ok": False, "error": "unavailable"}
    h.stop()


def test_malformed_tool_arguments_send_error_without_raising():
    """Malformed JSON arguments produce an error payload, never an exception."""
    h = Harness(
        events=[
            SimpleNamespace(
                type="response.function_call_arguments.done",
                call_id="call-4",
                name="paste_text",
                arguments="{not valid json",
            )
        ]
    )
    h.run_script()

    assert h.paste_calls == []
    output = json.loads(h.connection.conversation.item.create.call_args.kwargs["item"]["output"])
    assert output["ok"] is False
    assert h.connection.response.create.called
    assert h.errors == []
    h.stop()


def test_error_event_reports_but_does_not_stop_session():
    """An error event calls on_error yet the recv-loop keeps running."""
    h = Harness(
        events=[
            SimpleNamespace(type="error", error=SimpleNamespace(message="boom")),
            SimpleNamespace(type="response.output_audio_transcript.delta", delta="still here"),
        ]
    )
    h.run_script()

    assert len(h.errors) == 1
    # The event after the error was still processed -> loop did not stop.
    assert h.assistant_texts == ["still here"]
    assert h.assistant.is_active()
    h.stop()


def test_stop_tears_down_in_order_and_emits_stopped_without_error():
    """stop() halts recorder then player then connection; no error; idempotent."""
    h = Harness()
    h.run_script()
    assert h.recorder.started and h.player.started

    h.stop()

    assert h.recorder.stopped is True
    assert h.player.stopped is True
    assert h.connection.closed.is_set()
    assert h.states[-1] == "stopped"
    assert h.errors == []
    assert h.assistant.is_active() is False

    # Double stop is a safe no-op.
    h.stop()
    assert h.assistant.is_active() is False


def test_stop_during_connect_handshake_never_opens_mic_or_player():
    """stop() racing the in-flight connect must not leave the mic/player open.

    Reproduces the connect-in-flight race: stop() runs while _run is blocked in
    connect(), so its _teardown finds every resource None. _run must then bail
    after connect (re-checking _stopping) and never start the recorder/player.
    """
    h = Harness()
    gate = h.connection.arm_connect_gate()

    h.assistant.start()
    assert h.connection.entered.wait(2.0), "connect() was never entered"

    # stop() will set _stopping, tear down (finds nothing), then join the thread
    # that is still parked in connect(). Run it off-thread so we can release the
    # gate while stop() is blocked on the join.
    stopped = threading.Event()

    def do_stop():
        h.assistant.stop()
        stopped.set()

    stopper = threading.Thread(target=do_stop, daemon=True)
    stopper.start()
    # Let stop() set _stopping and reach the join before connect completes.
    time.sleep(0.05)
    gate.set()

    assert stopped.wait(2.0), "stop() did not return"
    stopper.join(timeout=2.0)

    # The mic and player were never started -> nothing to leak.
    assert h.recorder.started is False
    assert h.player.started is False
    # The connection we opened was still closed on the way out.
    assert h.connection.closed.is_set()
    assert h.assistant.is_active() is False
    assert h.errors == []


def test_stop_racing_recorder_start_tears_down_the_mic():
    """stop() landing after the player starts but before recorder.start() must
    still leave nothing running once _run exits (the finally tears it down).

    This exercises the interleaving where _teardown runs while _recorder is
    None, _run then assigns+starts the recorder, the loop exits immediately
    because _stopping is set, and the finally must clean the recorder up.
    """
    from whisper_hud.assistant import VoiceAssistant

    states: list[str] = []
    errors: list[Exception] = []

    recorder = FakeRecorder()
    player = FakePlayer()

    # Gate the recorder factory so stop() can land in the window after the
    # player started but before the recorder is assigned/started.
    recorder_gate = threading.Event()
    recorder_requested = threading.Event()

    def gated_recorder_factory():
        recorder_requested.set()
        recorder_gate.wait(2.0)
        return recorder

    connection = FakeConnection()
    client = MagicMock()
    client.realtime.connect.return_value = connection

    assistant = VoiceAssistant(
        api_key="sk-test",
        paste_callback=lambda _t: True,
        on_state=states.append,
        on_user_text=lambda _t: None,
        on_assistant_text=lambda _t: None,
        on_exchange=lambda _u, _a: None,
        on_error=errors.append,
        client_factory=lambda _key: client,
        recorder_factory=gated_recorder_factory,
        player_factory=lambda: player,
    )

    assistant.start()
    # Wait until _run has started the player and is about to build the recorder.
    assert recorder_requested.wait(2.0), "recorder factory was never reached"
    assert player.started is True

    # stop() now: _teardown stops the player but finds _recorder still None.
    stopped = threading.Event()

    def do_stop():
        assistant.stop()
        stopped.set()

    stopper = threading.Thread(target=do_stop, daemon=True)
    stopper.start()
    time.sleep(0.05)  # let stop() flip _stopping and tear down the player
    recorder_gate.set()  # _run now assigns + starts the recorder, then exits

    assert stopped.wait(2.0), "stop() did not return"
    stopper.join(timeout=2.0)

    # The recorder _run started after stop() must be torn down by the finally.
    assert recorder.started is True
    assert recorder.stopped is True
    assert player.stopped is True
    assert connection.closed.is_set()
    assert assistant.is_active() is False


def test_abnormal_recv_exception_reports_error_and_cleans_up():
    """An unexpected recv() failure (not stopping) fires on_error and cleanup."""
    from whisper_hud.assistant import VoiceAssistant

    states: list[str] = []
    errors: list[Exception] = []
    recorder = FakeRecorder()
    player = FakePlayer()

    class ExplodingConnection(FakeConnection):
        def recv(self):
            raise RuntimeError("socket exploded")

    connection = ExplodingConnection()
    client = MagicMock()
    client.realtime.connect.return_value = connection

    assistant = VoiceAssistant(
        api_key="sk-test",
        paste_callback=lambda _t: True,
        on_state=states.append,
        on_user_text=lambda _t: None,
        on_assistant_text=lambda _t: None,
        on_exchange=lambda _u, _a: None,
        on_error=errors.append,
        client_factory=lambda _key: client,
        recorder_factory=lambda: recorder,
        player_factory=lambda: player,
    )

    assistant.start()

    deadline = time.time() + 2.0
    while time.time() < deadline and not errors:
        time.sleep(0.01)

    assert len(errors) == 1
    assert "error" in states
    assert recorder.stopped is True
    assert player.stopped is True
    assert assistant.is_active() is False


def test_full_scale_resample_does_not_wrap_int16():
    """Resampling full-scale audio must clip after resampling so the int16 cast
    never wraps a loud positive peak into a large negative sample (audible click).
    """
    import math

    from scipy.signal import resample_poly

    # A full-scale alternating signal at 16 kHz (the recorder's native rate);
    # the 16k->24k resample's polyphase filter overshoots past +/-1.0 on these
    # sharp transients, so an unclipped cast would wrap modularly.
    signal = np.tile([1.0, -1.0], 240).astype(np.float32)

    encoded, _ = encode_pcm16_chunk(signal, 16000, REALTIME_SAMPLE_RATE)
    decoded = np.frombuffer(decode_pcm16_chunk(encoded), dtype="<i2").astype(np.int64)

    # Build the saturating reference the encoder SHOULD produce: resample, then
    # clip, then cast. Comparing against this catches the wrap directly -- an
    # unclipped cast turns overshoot peaks into sign-inverted samples that do
    # NOT match the saturated reference.
    gcd = math.gcd(16000, REALTIME_SAMPLE_RATE)
    resampled = resample_poly(np.clip(signal, -1.0, 1.0), REALTIME_SAMPLE_RATE // gcd, 16000 // gcd)
    reference = np.clip(np.round(resampled * 32767.0), -32768.0, 32767.0).astype(np.int64)

    assert decoded.min() >= -32768
    assert decoded.max() <= 32767
    np.testing.assert_array_equal(decoded, reference)
    # The resample genuinely overshoots past +/-1.0 here, so without the
    # post-resample clip at least one sample would have wrapped.
    assert (np.abs(resampled) > 1.0).any()


def test_is_terminal_session_error_classifies_unrecoverable_frames():
    """Auth/quota/billing markers are terminal; transient frames are not."""
    from whisper_hud.assistant import _is_terminal_session_error

    assert _is_terminal_session_error(SimpleNamespace(code="invalid_api_key", type="", message=""))
    assert _is_terminal_session_error(
        SimpleNamespace(code="", type="", message="You exceeded your insufficient_quota.")
    )
    assert _is_terminal_session_error(SimpleNamespace(type="session_expired", code="", message=""))
    assert not _is_terminal_session_error(
        SimpleNamespace(code="server_error", type="", message="temporary glitch, retrying")
    )
    assert not _is_terminal_session_error(None)


def test_terminal_error_event_releases_mic_and_stops_session():
    """An auth/quota error frame must tear down (mic released), not hot-spin.

    Regression for the hot-mic hazard: the old handler notified and returned,
    leaving the recv-loop spinning and the recorder holding the mic on a session
    that never recovers.
    """
    h = Harness(
        events=[
            SimpleNamespace(
                type="error",
                error=SimpleNamespace(
                    type="invalid_request_error",
                    code="invalid_api_key",
                    message="Incorrect API key provided.",
                ),
            ),
            # Only reached if the loop wrongly kept running after the error.
            SimpleNamespace(type="response.output_audio_transcript.delta", delta="should not appear"),
        ]
    )
    h.assistant.start()

    # "error" state is emitted last, after teardown — wait for it to settle.
    deadline = time.time() + 2.0
    while time.time() < deadline and "error" not in h.states:
        time.sleep(0.01)

    assert h.assistant.is_active() is False
    assert len(h.errors) == 1
    assert "error" in h.states
    assert h.recorder.stopped is True  # mic released, not left hot
    assert h.player.stopped is True
    assert h.assistant_texts == []  # the trailing delta never ran
    h.stop()
