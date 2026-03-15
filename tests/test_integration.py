"""Integration coverage for the end-to-end transcription pipeline."""

from pathlib import Path
import sys
import threading
import types
from unittest.mock import MagicMock

import numpy as np
import pytest

from whisper_hud.config import Config
from whisper_hud.providers.base import TranscriptionProvider, TranscriptionResult
from whisper_hud.transcribe import TranscriptionManager

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "integration_short.wav"
EXPECTED_TEXT = "integration transcript from bundled fixture"


class ImmediateThread:
    """Thread stand-in that runs its target synchronously."""

    def __init__(self, *, target, daemon=None):
        self._target = target
        self.daemon = daemon

    def start(self):
        self._target()


class FakeWhisperLocalProvider(TranscriptionProvider):
    """Mock Whisper Local provider that still exercises the real manager path."""

    name = "whisper_local"
    display_name = "Whisper Local"
    response_text = EXPECTED_TEXT
    error: Exception | None = None
    seen_audio: list[bytes] = []

    def __init__(self, model=None):
        self.model = model or "tiny"

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        self.__class__.seen_audio.append(audio_bytes)
        if self.__class__.error is not None:
            raise self.__class__.error
        return TranscriptionResult(
            text=self.__class__.response_text,
            duration_seconds=0.8,
            cost_estimate=0.0,
            provider=self.name,
            model=self.model,
        )

    def is_configured(self) -> bool:
        return True

    def get_models(self) -> list[dict]:
        return [{"id": self.model, "name": self.model}]

    def set_model(self, model_id: str) -> None:
        self.model = model_id

    def get_current_model(self) -> str:
        return self.model


class FakeInputStream:
    """sounddevice.InputStream stand-in for recorder integration tests."""

    last_instance = None

    def __init__(self, **kwargs):
        self.callback = kwargs["callback"]
        FakeInputStream.last_instance = self

    def start(self):
        return None

    def stop(self):
        return None

    def close(self):
        return None


def _build_app(transcriber: TranscriptionManager):
    from whisper_hud.app import WhisperHUDApp

    app = WhisperHUDApp.__new__(WhisperHUDApp)
    app._recording_lock = threading.Lock()
    app._lock = threading.Lock()
    app._is_recording = False
    app._turn_counter = 0
    app._active_turn = None
    app.ICON_RECORDING = "recording"
    app.ICON_PROCESSING = "processing"
    app.ICON_ERROR = "error"
    app.ICON_SUCCESS = "success"
    app._set_title = MagicMock()
    app._get_idle_icon = MagicMock(return_value="idle")
    app._notify = MagicMock()
    app._schedule_menu_rebuild = MagicMock()
    app._play_completion_sound = MagicMock()
    app._ensure_cloud_credentials_ready = MagicMock(return_value=True)
    app._ensure_history_encryption_session = MagicMock()
    app._selected_live_language = MagicMock(return_value=None)
    app._start_level_monitor = MagicMock()
    app._start_max_duration_timer = MagicMock()
    app._start_live_connect_timer = MagicMock(return_value=None)
    app._cancel_turn_timers = MagicMock()
    app._close_live_session = MagicMock()
    app._is_passphrase_store_locked = MagicMock(return_value=False)
    app.widget = None
    app.hud = MagicMock()
    app.streaming_panel = MagicMock()
    app.transcriber = transcriber
    app.translator = MagicMock()
    app.paste_target_manager = MagicMock()
    app.recorder = None
    app.config = Config()
    app.config.save = MagicMock(return_value=True)
    app.config.show_hud = True
    app.config.auto_stop = False
    app.config.auto_paste = True
    app.config.restore_clipboard = True
    app.config.translation_enabled = False
    app.config.streaming_enabled = False
    app.config.history_enabled = True
    app.config.history = []
    app.config.private_mode = False
    app.config.history_encrypted = False
    app.config.default_provider = "whisper_local"
    app.config.paste_target_enabled = False
    app.config.paste_target_type = "focused"
    app.config.paste_target_identifier = ""
    app.config.paste_target_return_focus = True
    return app


@pytest.fixture(autouse=True)
def reset_fake_provider():
    FakeWhisperLocalProvider.response_text = EXPECTED_TEXT
    FakeWhisperLocalProvider.error = None
    FakeWhisperLocalProvider.seen_audio = []
    FakeInputStream.last_instance = None
    yield


@pytest.fixture
def fixture_audio_bytes() -> bytes:
    return FIXTURE_PATH.read_bytes()


@pytest.fixture
def fake_manager(monkeypatch) -> TranscriptionManager:
    monkeypatch.setitem(
        TranscriptionManager.PROVIDER_CLASSES,
        "whisper_local",
        FakeWhisperLocalProvider,
    )
    config = Config()
    config.default_provider = "whisper_local"
    return TranscriptionManager(config=config)


@pytest.fixture
def app_symbols(monkeypatch):
    fake_rumps = types.SimpleNamespace(
        App=type("FakeRumpsApp", (), {}),
        MenuItem=type("FakeMenuItem", (), {}),
        separator=object(),
        alert=lambda *args, **kwargs: 0,
    )
    fake_hotkey = types.SimpleNamespace(
        HotkeyListener=type("HotkeyListener", (), {"DEFAULT_HOTKEY": set()}),
        HotkeyCapture=type("HotkeyCapture", (), {}),
        format_hotkey_display=lambda keys: "+".join(sorted(keys)),
        string_to_key=lambda key: key,
    )

    monkeypatch.setitem(sys.modules, "rumps", fake_rumps)
    monkeypatch.setitem(sys.modules, "whisper_hud.hud", types.SimpleNamespace(create_hud=lambda *args, **kwargs: None))
    monkeypatch.setitem(
        sys.modules,
        "whisper_hud.floating_widget",
        types.SimpleNamespace(create_floating_widget=lambda *args, **kwargs: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "whisper_hud.streaming_panel",
        types.SimpleNamespace(create_streaming_panel=lambda *args, **kwargs: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "whisper_hud.setup_wizard",
        types.SimpleNamespace(show_setup_wizard=lambda *args, **kwargs: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "whisper_hud.image_processor",
        types.SimpleNamespace(ImageProcessor=type("ImageProcessor", (), {})),
    )
    monkeypatch.setitem(
        sys.modules,
        "whisper_hud.character_packs",
        types.SimpleNamespace(CharacterPackManager=type("CharacterPackManager", (), {})),
    )
    monkeypatch.setitem(sys.modules, "whisper_hud.hotkey", fake_hotkey)

    from whisper_hud.app import ActiveTranscriptionTurn, WhisperHUDApp

    return types.SimpleNamespace(ActiveTranscriptionTurn=ActiveTranscriptionTurn, WhisperHUDApp=WhisperHUDApp)


@pytest.mark.integration
def test_audio_fixture_transcribes_and_pastes_to_clipboard(monkeypatch, fake_manager, fixture_audio_bytes, app_symbols):
    """A bundled WAV should flow through TranscriptionManager into the paste path."""
    app = _build_app(fake_manager)
    app._active_turn = app_symbols.ActiveTranscriptionTurn(turn_id=1, provider_id="whisper_local")
    clipboard = {}

    monkeypatch.setattr("whisper_hud.app.threading.Thread", ImmediateThread)
    monkeypatch.setattr("whisper_hud.app.time.sleep", lambda _: None)
    monkeypatch.setattr(
        "whisper_hud.app.insert_text",
        lambda text, restore_clipboard=True: clipboard.setdefault("text", text) == text,
    )

    result = fake_manager.transcribe(fixture_audio_bytes, provider_id="whisper_local")
    app._process_turn_result(1, result, use_streaming=False, stats_already_recorded=True)

    assert FakeWhisperLocalProvider.seen_audio == [fixture_audio_bytes]
    assert clipboard["text"] == EXPECTED_TEXT
    app.hud.show_success.assert_called_once_with("Done! (5 words)")


@pytest.mark.integration
def test_recording_start_stop_transcribes_and_pastes(monkeypatch, fake_manager, app_symbols):
    """Recorder -> manager -> app batch paste should work with a mocked audio stream."""
    from whisper_hud.recorder import AudioRecorder

    app = _build_app(fake_manager)
    app.recorder = AudioRecorder(sample_rate=16000)
    pasted = {}

    monkeypatch.setattr("whisper_hud.recorder.is_valid_input_device", lambda device: True)
    monkeypatch.setattr("whisper_hud.recorder.sd.InputStream", FakeInputStream)
    monkeypatch.setattr("whisper_hud.app.threading.Thread", ImmediateThread)
    monkeypatch.setattr("whisper_hud.app.time.sleep", lambda _: None)
    monkeypatch.setattr(
        "whisper_hud.app.insert_text",
        lambda text, restore_clipboard=True: pasted.setdefault("text", text) == text,
    )

    app._start_recording()
    assert app._is_recording is True

    speech_chunk = np.ones((4096, 1), dtype=np.float32) * 0.1
    FakeInputStream.last_instance.callback(speech_chunk, len(speech_chunk), None, None)
    FakeInputStream.last_instance.callback(speech_chunk, len(speech_chunk), None, None)

    app._stop_recording()
    assert app._active_turn is not None
    app._start_batch_transcription(app._active_turn.turn_id)

    assert app._is_recording is False
    assert pasted["text"] == EXPECTED_TEXT
    assert FakeWhisperLocalProvider.seen_audio
    assert FakeWhisperLocalProvider.seen_audio[0].startswith(b"RIFF")
    app.hud.show_recording.assert_called_once_with()
    app.hud.show_processing.assert_called_once_with()
    app.hud.show_success.assert_called_once_with("Done! (5 words)")


@pytest.mark.integration
def test_provider_error_propagates_to_hud(monkeypatch, fake_manager, app_symbols):
    """Provider failures should surface through the app's terminal HUD error state."""
    from whisper_hud.recorder import AudioRecorder

    FakeWhisperLocalProvider.error = RuntimeError("provider exploded")

    app = _build_app(fake_manager)
    app.recorder = AudioRecorder(sample_rate=16000)

    monkeypatch.setattr("whisper_hud.recorder.is_valid_input_device", lambda device: True)
    monkeypatch.setattr("whisper_hud.recorder.sd.InputStream", FakeInputStream)
    monkeypatch.setattr("whisper_hud.app.threading.Thread", ImmediateThread)
    monkeypatch.setattr("whisper_hud.app.time.sleep", lambda _: None)

    app._start_recording()

    speech_chunk = np.ones((4096, 1), dtype=np.float32) * 0.1
    FakeInputStream.last_instance.callback(speech_chunk, len(speech_chunk), None, None)
    FakeInputStream.last_instance.callback(speech_chunk, len(speech_chunk), None, None)

    app._stop_recording()
    assert app._active_turn is not None
    app._start_batch_transcription(app._active_turn.turn_id)

    app.hud.show_error.assert_called_once_with("Transcription failed")
    app._notify.assert_called_once_with("WhisperHUD", "Transcription failed", "provider exploded")
