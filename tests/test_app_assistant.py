"""App-level tests for the voice assistant wiring (Subsystem B).

Self-contained recording-flow harness (mirrors the WhisperHUDApp.__new__ +
MagicMock pattern in test_app.py); the menu assertion reuses test_app's full
_build_menu_app harness via an explicit tests-dir path insert.
"""

import os
import sys
import threading
from unittest.mock import MagicMock, patch

# Make sibling test module importable regardless of collection order.
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from test_app import _build_menu_app, _menu_titles  # noqa: E402

from whisper_hud.app import WhisperHUDApp  # noqa: E402
from whisper_hud.config import Config  # noqa: E402


class FakeAssistant:
    """Stateful VoiceAssistant stand-in: start() flips is_active() to True."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self._active = False
        self.start = MagicMock(side_effect=self._start)
        self.stop = MagicMock(side_effect=self._stop)

    def _start(self):
        self._active = True

    def _stop(self):
        self._active = False

    def is_active(self):
        return self._active


def _build_assistant_app():
    """Construct a partial app instance for voice-assistant flow tests."""
    app = WhisperHUDApp.__new__(WhisperHUDApp)
    app._recording_lock = threading.Lock()
    app._lock = threading.Lock()
    app._is_recording = False
    app._turn_counter = 0
    app._active_turn = None
    app._voice_assistant = None
    app._assistant_error_notified = False
    app.ICON_ASSISTANT = "assistant"
    app.ICON_RECORDING = "recording"
    app._set_title = MagicMock()
    app._get_idle_icon = MagicMock(return_value="idle")
    app._notify = MagicMock()
    app._schedule_menu_rebuild = MagicMock()
    app._paste_to_target = MagicMock(return_value=True)
    app.config = Config()
    app.config.save = MagicMock(return_value=True)
    app.config.history_enabled = True
    app.config.private_mode = False
    app.config.history = []
    # These flow tests exercise construct/refuse/stop, not the cost gate or the
    # session watchdog: pre-acknowledge the one-time cost disclosure (so no modal
    # blocks the test) and disable the auto-stop cap (so no watchdog thread is
    # spawned). The cost gate and watchdog have dedicated tests in test_app.py.
    app.config.assistant_cost_ack = True
    app.config.assistant_max_session_seconds = 0
    return app


# --- (a) toggle without key -> notification, nothing constructed -------------


def test_toggle_without_key_notifies_and_does_not_construct(monkeypatch):
    app = _build_assistant_app()
    monkeypatch.setattr("whisper_hud.app.get_api_key", lambda provider: None)
    construct = MagicMock(side_effect=AssertionError("VoiceAssistant must not be constructed"))
    monkeypatch.setattr("whisper_hud.app.VoiceAssistant", construct)

    app._toggle_voice_assistant(None)

    construct.assert_not_called()
    assert app._voice_assistant is None
    assert app._notify.call_count == 1
    assert "OpenAI" in app._notify.call_args.args[1] or "OpenAI" in app._notify.call_args.args[2]


# --- (b) toggle while recording -> refused ----------------------------------


def test_toggle_while_recording_is_refused(monkeypatch):
    app = _build_assistant_app()
    app._is_recording = True
    monkeypatch.setattr("whisper_hud.app.get_api_key", lambda provider: "sk-test")
    construct = MagicMock(side_effect=AssertionError("must not construct while recording"))
    monkeypatch.setattr("whisper_hud.app.VoiceAssistant", construct)

    app._toggle_voice_assistant(None)

    construct.assert_not_called()
    assert app._voice_assistant is None
    app._notify.assert_called_once()


# --- (c) successful start constructs with config values + paste callback -----


def test_successful_start_constructs_and_starts(monkeypatch):
    app = _build_assistant_app()
    app.config.assistant_model = "gpt-realtime-2"
    app.config.assistant_voice = "cedar"
    app.config.assistant_reasoning_effort = "high"
    app.config.assistant_paste_tool_enabled = False
    monkeypatch.setattr("whisper_hud.app.get_api_key", lambda provider: "sk-test")
    monkeypatch.setattr("whisper_hud.app.VoiceAssistant", FakeAssistant)

    app._toggle_voice_assistant(None)

    assistant = app._voice_assistant
    assert isinstance(assistant, FakeAssistant)
    assert assistant.kwargs["api_key"] == "sk-test"
    assert assistant.kwargs["model"] == "gpt-realtime-2"
    assert assistant.kwargs["voice"] == "cedar"
    assert assistant.kwargs["reasoning_effort"] == "high"
    assert assistant.kwargs["paste_tool_enabled"] is False
    # The only side-effect channel is bound to the app's paste target pipeline.
    assert assistant.kwargs["paste_callback"] == app._paste_to_target
    assistant.start.assert_called_once_with()
    assert app._assistant_error_notified is False


# --- (c2) assistant recorder honors the configured input device --------------


def test_assistant_recorder_factory_uses_configured_input_device(monkeypatch):
    """The injected recorder_factory must build AudioRecorder with the user's
    configured input device, matching dictation (not the system default)."""
    app = _build_assistant_app()
    app.config.audio_input_device = 7  # a non-default device the user picked
    monkeypatch.setattr("whisper_hud.app.get_api_key", lambda provider: "sk-test")
    monkeypatch.setattr("whisper_hud.app.VoiceAssistant", FakeAssistant)

    built_devices = []

    class CapturingRecorder:
        def __init__(self, device=None):
            built_devices.append(device)

    monkeypatch.setattr("whisper_hud.app.AudioRecorder", CapturingRecorder)

    app._toggle_voice_assistant(None)

    factory = app._voice_assistant.kwargs.get("recorder_factory")
    assert factory is not None, "assistant was not given a recorder_factory"
    recorder = factory()
    assert isinstance(recorder, CapturingRecorder)
    assert built_devices == [7]


# --- (d) second toggle stops a running assistant ----------------------------


def test_second_toggle_stops_running_assistant(monkeypatch):
    app = _build_assistant_app()
    monkeypatch.setattr("whisper_hud.app.get_api_key", lambda provider: "sk-test")
    monkeypatch.setattr("whisper_hud.app.VoiceAssistant", FakeAssistant)

    app._toggle_voice_assistant(None)  # start
    assistant = app._voice_assistant
    assert assistant.is_active() is True

    app._toggle_voice_assistant(None)  # stop
    assistant.stop.assert_called_once_with()
    assert assistant.is_active() is False


# --- (e) _start_recording refused while the assistant is active -------------


def test_start_recording_refused_while_assistant_active():
    app = _build_assistant_app()
    app._voice_assistant = FakeAssistant()
    app._voice_assistant._active = True
    # If the guard fails, this attribute access path would continue; assert that
    # recording never starts and the user is told to stop the assistant first.
    app._ensure_cloud_credentials_ready = MagicMock(return_value=True)

    app._start_recording()

    assert app._is_recording is False
    app._notify.assert_called_once()
    assert app._notify.call_args.args[1] == "Voice Assistant Active"


# --- (e2) toggle serializes with dictation on _recording_lock (TOCTOU) -------


def test_toggle_voice_assistant_serializes_on_recording_lock(monkeypatch):
    """_toggle_voice_assistant must take _recording_lock around its _is_recording
    check + construct, so a dictation turn already holding the lock cannot be
    raced: while the lock is held the toggle blocks and constructs nothing."""
    app = _build_assistant_app()
    monkeypatch.setattr("whisper_hud.app.get_api_key", lambda provider: "sk-test")

    constructed = threading.Event()

    class SignalingAssistant(FakeAssistant):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            constructed.set()

    monkeypatch.setattr("whisper_hud.app.VoiceAssistant", SignalingAssistant)

    # Simulate a hotkey-started dictation turn that already holds _recording_lock
    # and is about to flip _is_recording=True inside its locked section.
    app._recording_lock.acquire()

    finished = threading.Event()

    def toggle():
        app._toggle_voice_assistant(None)
        finished.set()

    worker = threading.Thread(target=toggle, daemon=True)
    worker.start()

    # While dictation holds the lock, the toggle must NOT have constructed the
    # assistant (it is blocked acquiring _recording_lock). If the guard were not
    # lock-synchronized, it would read _is_recording (still False) and construct.
    assert not constructed.wait(0.3), "assistant constructed without holding the lock"

    # Dictation finishes claiming the mic under the lock, then releases it.
    app._is_recording = True
    app._recording_lock.release()

    assert finished.wait(2.0), "toggle never completed after lock release"
    worker.join(timeout=2.0)

    # The toggle saw the mic was taken and refused -- no assistant, dictation msg.
    assert constructed.is_set() is False
    assert app._voice_assistant is None
    assert app._notify.call_args.args[1] == "Dictation Active"


# --- (f) on_exchange writes history with source="assistant" ------------------


def test_on_exchange_writes_history_with_assistant_source():
    app = _build_assistant_app()
    app.config.assistant_model = "gpt-realtime-2"
    app.config.add_to_history = MagicMock(return_value=True)

    app._on_assistant_exchange("what time is it", "It is noon.")

    call = app.config.add_to_history.call_args
    assert call.kwargs["text"] == "It is noon."
    assert call.kwargs["original_text"] == "what time is it"
    assert call.kwargs["provider"] == "openai_assistant"
    assert call.kwargs["translated"] is False
    assert call.kwargs["source"] == "assistant"
    assert call.kwargs["model"] == "gpt-realtime-2"


# --- (g) _quit stops an active assistant ------------------------------------


def test_quit_stops_active_assistant(monkeypatch):
    app = _build_assistant_app()
    app._voice_assistant = FakeAssistant()
    app._voice_assistant._active = True
    app._active_turn = None
    app._history_view_files = []
    app.hotkey_listener = MagicMock()
    app.hud = MagicMock()
    app.streaming_panel = MagicMock()
    app.widget = None
    app._detach_menu_observers = MagicMock()

    with (
        patch("whisper_hud.app.lock_passphrase_store"),
        patch("whisper_hud.app.lock_history_encryption"),
        patch("whisper_hud.app.rumps.quit_application"),
    ):
        app._quit(None)

    app._voice_assistant.stop.assert_called_once_with()


# --- (h) menu contains the Voice Assistant submenu with all items -----------


def test_menu_contains_voice_assistant_submenu(monkeypatch):
    app = _build_menu_app(monkeypatch)

    app._build_menu()

    va_menu = next(item for item in app.menu.items if getattr(item, "title", None) == "Voice Assistant")
    titles = _menu_titles(va_menu)
    # Start/Stop item (title reflects state), pickers, paste toggle, cloud hint.
    assert any("Voice Chat" in t for t in titles)
    assert "Voice" in titles
    assert "Reasoning Effort" in titles
    assert any("Allow Pasting Text" in t for t in titles)
    assert any("gpt-realtime-2" in t for t in titles)

    voice_menu = next(item for item in va_menu.items if getattr(item, "title", None) == "Voice")
    voice_titles = _menu_titles(voice_menu)
    # The configured voice is marked; the full picker is present.
    assert any("marin" in t for t in voice_titles)
    assert any("cedar" in t for t in voice_titles)

    effort_menu = next(item for item in va_menu.items if getattr(item, "title", None) == "Reasoning Effort")
    effort_titles = _menu_titles(effort_menu)
    assert any("Low" in t for t in effort_titles)
    assert any("Medium" in t for t in effort_titles)
    assert any("High" in t for t in effort_titles)


# --- (h2) model picker lists both tiers and tracks the configured model -----


def test_menu_model_picker_lists_tiers_and_marks_selection(monkeypatch):
    app = _build_menu_app(monkeypatch)
    app.config.assistant_model = "gpt-realtime-mini"

    app._build_menu()

    va_menu = next(item for item in app.menu.items if getattr(item, "title", None) == "Voice Assistant")
    titles = _menu_titles(va_menu)
    assert "Model" in titles
    # The cloud hint follows the configured model, not a hardcoded id.
    assert any("Talks to OpenAI gpt-realtime-mini (cloud)" in t for t in titles)

    model_menu = next(item for item in va_menu.items if getattr(item, "title", None) == "Model")
    model_titles = _menu_titles(model_menu)
    assert any("gpt-realtime-2" in t for t in model_titles)
    assert any("gpt-realtime-mini" in t for t in model_titles)
    assert any(t.startswith("● ") and "gpt-realtime-mini" in t for t in model_titles)
    assert not any(t.startswith("● ") and "gpt-realtime-2" in t for t in model_titles)


# --- (h3) selecting a model persists it and the next start uses it ----------


def test_set_assistant_model_persists_and_next_start_uses_it(monkeypatch):
    app = _build_assistant_app()
    monkeypatch.setattr("whisper_hud.app.get_api_key", lambda provider: "sk-test")
    monkeypatch.setattr("whisper_hud.app.VoiceAssistant", FakeAssistant)

    app._set_assistant_model("gpt-realtime-mini")

    assert app.config.assistant_model == "gpt-realtime-mini"
    app.config.save.assert_called_once_with()
    app._schedule_menu_rebuild.assert_called_once_with()

    app._toggle_voice_assistant(None)

    assert app._voice_assistant.kwargs["model"] == "gpt-realtime-mini"


# --- (i) on_state updates the title icon ------------------------------------


def test_on_state_updates_title_icon():
    app = _build_assistant_app()

    for state in ("connecting", "listening", "responding"):
        app._set_title.reset_mock()
        app._on_assistant_state(state)
        app._set_title.assert_called_once_with(app.ICON_ASSISTANT)

    for state in ("stopped", "error"):
        app._set_title.reset_mock()
        app._on_assistant_state(state)
        app._set_title.assert_called_once_with("idle")
