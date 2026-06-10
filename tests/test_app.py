"""App-level tests for menu construction and recording dispatch flows."""

import sys
import threading
import types
from unittest.mock import MagicMock, patch

from whisper_hud.app import ActiveTranscriptionTurn, WhisperHUDApp
from whisper_hud.config import Config
from whisper_hud.providers.base import TranscriptionResult


class FakeMenuItem:
    """Minimal rumps.MenuItem replacement for menu assertions."""

    def __init__(self, title, callback=None):
        self.title = title
        self.callback = callback
        self.items = []

    def add(self, item):
        self.items.append(item)


class FakeMenu:
    """Minimal rumps menu container used by _build_menu tests."""

    def __init__(self):
        self.items = []

    def add(self, item):
        self.items.append(item)

    def clear(self):
        self.items.clear()


class AppHarness(WhisperHUDApp):
    """Test subclass that lazily supplies callback attributes."""

    def __getattr__(self, name):
        mock = MagicMock(name=name)
        setattr(self, name, mock)
        return mock


class ImmediateThread:
    """Thread stand-in that executes the target immediately."""

    def __init__(self, *, target, daemon=None):
        self._target = target
        self.daemon = daemon

    def start(self):
        self._target()


class FakeCapturePanel:
    """Minimal hotkey capture panel test double."""

    instances = []

    def __init__(self, current_hotkey, on_confirm, on_cancel=None):
        self.current_hotkey = current_hotkey
        self.on_confirm = on_confirm
        self.on_cancel = on_cancel
        self.show = MagicMock(return_value=True)
        self.close = MagicMock()
        FakeCapturePanel.instances.append(self)


def _build_recording_app():
    """Construct a partial app instance for recording-flow tests."""
    app = WhisperHUDApp.__new__(WhisperHUDApp)
    app._recording_lock = threading.Lock()
    app._lock = threading.Lock()
    app._is_recording = False
    app._turn_counter = 0
    app._active_turn = None
    app._is_capturing_hotkey = False
    app._hotkey_capture_panel = None
    app._voice_assistant = None
    app._assistant_error_notified = False
    app.ICON_RECORDING = "recording"
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
    app._finish_turn_cleanup = MagicMock()
    app._is_passphrase_store_locked = MagicMock(return_value=False)
    app.widget = None
    app.hud = MagicMock()
    app.streaming_panel = MagicMock()
    app.recorder = MagicMock()
    app.transcriber = MagicMock()
    app.translator = MagicMock()
    app.config = Config()
    app.config.save = MagicMock(return_value=True)
    app.config.show_hud = True
    app.config.auto_stop = False
    app.config.auto_paste = True
    app.config.translation_enabled = False
    app.config.streaming_enabled = False
    app.config.history_enabled = True
    app.config.history = []
    app.config.private_mode = False
    app.config.history_encrypted = False
    app.config.default_provider = "openai"
    return app


def test_import_settings_restores_previous_config_when_save_fails(monkeypatch):
    """Settings import should fail closed when the new config cannot be persisted."""

    class FakeURL:
        def path(self):
            return "/tmp/settings.json"

    class FakePanel:
        def setTitle_(self, _title):
            return None

        def setAllowedFileTypes_(self, _types):
            return None

        def setCanChooseFiles_(self, _value):
            return None

        def setCanChooseDirectories_(self, _value):
            return None

        def runModal(self):
            return 1

        def URL(self):
            return FakeURL()

    class FakeOpenPanel:
        @staticmethod
        def openPanel():
            return FakePanel()

    fake_rumps = types.SimpleNamespace(alert=MagicMock(side_effect=[1, None]))
    monkeypatch.setattr("whisper_hud.app.rumps", fake_rumps)
    monkeypatch.setitem(sys.modules, "AppKit", types.SimpleNamespace(NSOpenPanel=FakeOpenPanel))

    imported_config = Config()
    imported_config.default_provider = "gemini"

    monkeypatch.setattr(
        Config,
        "import_settings",
        classmethod(lambda cls, filepath: (True, "Imported", imported_config)),
    )

    app = AppHarness.__new__(AppHarness)
    app.config = Config()
    app.config.default_provider = "openai"
    app.config.history = [{"text": "keep"}]
    app.config.save = MagicMock(return_value=False)
    app.transcriber = MagicMock()
    app.translator = MagicMock()
    app.recorder = MagicMock()
    app._restart_hotkey_listener = MagicMock()
    app._apply_appearance_to_components = MagicMock()
    app._schedule_menu_rebuild = MagicMock()
    app._notify = MagicMock()

    app._import_settings(None)

    assert app.config.default_provider == "openai"
    assert app.config.history == [{"text": "keep"}]
    app.config.save.assert_called_once_with()
    app.transcriber.reload_config.assert_not_called()
    app.translator.reload_config.assert_not_called()
    app._notify.assert_not_called()
    assert fake_rumps.alert.call_args_list[1].kwargs["title"] == "Import Failed"


def test_clear_history_shows_failure_alert_when_persist_fails(monkeypatch):
    """Clear-history UI should not claim success when config persistence fails."""
    fake_rumps = types.SimpleNamespace(alert=MagicMock(side_effect=[1, None]))
    monkeypatch.setattr("whisper_hud.app.rumps", fake_rumps)

    app = _build_recording_app()
    app.config.clear_history = MagicMock(return_value=False)

    app._clear_history(None)

    app._schedule_menu_rebuild.assert_not_called()
    app._notify.assert_not_called()
    assert fake_rumps.alert.call_args_list[1].kwargs["title"] == "Clear History Failed"


def test_enable_private_mode_shows_failure_alert_when_persist_fails(monkeypatch):
    """Private Mode UI should fail closed if the config update cannot be saved."""
    fake_rumps = types.SimpleNamespace(alert=MagicMock(side_effect=[1, None]))
    monkeypatch.setattr("whisper_hud.app.rumps", fake_rumps)

    app = _build_recording_app()
    app.config.enable_private_mode = MagicMock(return_value=False)

    app._toggle_private_mode(None)

    app._schedule_menu_rebuild.assert_not_called()
    app._notify.assert_not_called()
    assert fake_rumps.alert.call_args_list[1].kwargs["title"] == "Private Mode Update Failed"


def _build_menu_app(monkeypatch):
    """Construct a partial app instance for _build_menu assertions."""
    fake_rumps = types.SimpleNamespace(MenuItem=FakeMenuItem, separator=object())
    monkeypatch.setattr("whisper_hud.app.rumps", fake_rumps)

    monkeypatch.setitem(
        sys.modules,
        "whisper_hud.recorder",
        types.SimpleNamespace(get_input_devices=lambda: []),
    )
    monkeypatch.setitem(
        sys.modules,
        "whisper_hud.launch_agent",
        types.SimpleNamespace(is_launch_at_login_enabled=lambda: False),
    )
    monkeypatch.setitem(
        sys.modules,
        "whisper_hud.encryption",
        types.SimpleNamespace(is_cryptography_installed=lambda: True),
    )

    import whisper_hud

    monkeypatch.setattr(whisper_hud, "__version__", "test-version", raising=False)

    app = AppHarness.__new__(AppHarness)
    app._menu = FakeMenu()
    app._menu_is_open = False
    app._pending_menu_rebuild = False
    app._menu_action_lock = threading.Lock()
    app._is_recording = False
    app._is_downloading = False
    app._translation_availability = {}
    app._translation_availability_inflight = False
    app._translation_availability_last_checked = 0.0
    app._cached_tmux_sessions = []
    app._cached_iterm2_running = False
    app._cached_terminal_running = False
    app._cached_running_apps = []
    app.character_pack_manager = MagicMock()
    app.character_pack_manager.get_pack_for_menu.return_value = []
    app.character_pack_manager.get_current_pack_id.return_value = None
    app.transcriber = MagicMock()
    app.translator = MagicMock()
    app.config = Config()
    app.config.save = MagicMock(return_value=True)
    app.config.default_provider = "openai"
    app.config.translation_enabled = False
    app.config.show_widget = False
    app.config.show_hud = True
    app.config.auto_stop = False
    app.config.auto_paste = True
    app.config.restore_clipboard = True
    app.config.private_mode = False
    app.config.history_enabled = False
    app.config.play_sound = False
    app.config.show_notifications = True
    app.config.streaming_enabled = False
    app.config.audio_input_device = None
    app.config.paste_target_enabled = False
    app.config.paste_target_type = "focused"
    app.config.paste_target_identifier = ""
    app.config.paste_target_return_focus = True
    app.config.max_recording_duration = 600
    app.config.target_language = "en"
    app.config.source_language = "auto"
    app.config.hotkey = ["cmd", "shift", "space"]
    app.config.hotkey_mode = "push_to_talk"
    app.config.history = []
    app.config.history_encrypted = False
    app.config.widget_appearance["theme"] = "default"

    provider_objects = {
        "openai": MagicMock(
            get_models=MagicMock(return_value=[{"id": "gpt-4o", "name": "GPT-4o", "recommended": True}]),
            get_current_model=MagicMock(return_value="gpt-4o"),
            is_configured=MagicMock(return_value=True),
        ),
        "whisper_local": MagicMock(
            get_models=MagicMock(return_value=[{"id": "tiny", "name": "Tiny", "downloaded": False}]),
            get_current_model=MagicMock(return_value="tiny"),
            is_configured=MagicMock(return_value=False),
        ),
    }
    app.transcriber.get_provider.side_effect = lambda provider_id: provider_objects.get(provider_id)
    app.transcriber.get_available_providers.return_value = [
        {"id": "openai", "name": "OpenAI", "category": "cloud", "configured": True},
        {
            "id": "whisper_local",
            "name": "Whisper Local",
            "category": "local",
            "configured": False,
            "requires_download": True,
        },
    ]
    app.transcriber.get_stats.return_value = {"total_transcriptions": 0, "total_cost": 0.0}

    app.translator.get_current_provider.return_value = "apple"
    app.translator.get_current_model.return_value = "en-US"

    app._log_menu_trace = MagicMock()
    app._clear_menu_callback_registry = MagicMock()
    app._wrap_menu_callbacks = MagicMock()
    app._set_title = MagicMock()
    app._get_idle_icon = MagicMock(return_value="idle")
    app._credential_mode = MagicMock(return_value="passphrase")
    app._is_passphrase_store_locked = MagicMock(return_value=False)
    app._should_query_keychain = MagicMock(return_value=False)
    app._get_configured_cloud_providers = MagicMock(return_value=["openai"])
    app._get_provider_display_name = MagicMock(
        side_effect=lambda provider_id: {
            "openai": "OpenAI",
            "whisper_local": "Whisper Local",
            "apple": "Apple",
        }.get(provider_id, provider_id)
    )
    app._is_transcription_provider_configured = MagicMock(
        side_effect=lambda provider_id, configured: provider_id in configured
    )
    app._get_paste_target_display_name = MagicMock(return_value="Notes")
    app._is_target_available_cached = MagicMock(return_value=True)
    app._get_valid_recent_targets = MagicMock(return_value=[])
    app._format_target_for_menu = MagicMock(side_effect=lambda target_type, target_id, short=False: target_id)
    return app


def _menu_titles(menu):
    """Return the titles of non-separator items in a menu container."""
    return [item.title for item in menu.items if hasattr(item, "title")]


def test_build_menu_reflects_provider_availability(monkeypatch):
    """The menu should expose provider readiness within the merged providers submenu."""
    app = _build_menu_app(monkeypatch)

    app._build_menu()

    top_level_titles = _menu_titles(app.menu)
    assert top_level_titles[0] == "✓ Ready • OpenAI"
    assert top_level_titles[1:] == [
        "Providers & Keys",
        "Paste Target",
        "Translation",
        "Dictation Intelligence",
        "Voice Assistant",
        "Settings",
        "Quit WhisperHUD",
    ]
    # Bumped from <= 7: the "Voice Assistant" top-level item is a deliberate add.
    assert len(top_level_titles) <= 8

    provider_menu = next(item for item in app.menu.items if getattr(item, "title", None) == "Providers & Keys")
    provider_titles = _menu_titles(provider_menu)
    assert "Current: OpenAI" in provider_titles
    assert "● OpenAI ✓" in provider_titles
    assert "   Whisper Local [download] ⬇️" in provider_titles
    assert "OpenAI: Not set" in provider_titles

    settings_menu = next(item for item in app.menu.items if getattr(item, "title", None) == "Settings")
    settings_titles = _menu_titles(settings_menu)
    assert "Appearance" in settings_titles
    assert "Hotkey" in settings_titles
    assert "Advanced & Support" in settings_titles

    recording_menu = next(item for item in settings_menu.items if getattr(item, "title", None) == "Recording & Display")
    recording_titles = _menu_titles(recording_menu)
    assert "Reset Position" in recording_titles


def test_dictation_intelligence_menu_lists_core_toggles(monkeypatch):
    """The Dictation Intelligence section should expose the feature toggles."""
    app = _build_menu_app(monkeypatch)

    app._build_menu()

    di_menu = next(item for item in app.menu.items if getattr(item, "title", None) == "Dictation Intelligence")
    di_titles = _menu_titles(di_menu)
    assert any("Voice Commands" in t for t in di_titles)
    assert any("Dictation Modes" in t for t in di_titles)
    assert any("AI Cleanup (Local)" in t for t in di_titles)
    assert "Vocabulary & Replacements" in di_titles
    # Cleanup is off by default, so the privacy note is shown instead of a probe.
    assert any("never sent to the cloud" in t for t in di_titles)


def test_dictation_intelligence_menu_shows_builtin_modes_when_enabled(monkeypatch):
    """Enabling modes should reveal the built-in modes submenu."""
    app = _build_menu_app(monkeypatch)
    app.config.dictation_modes_enabled = True
    app._cached_frontmost_app = None
    app._cached_frontmost_app_checked = 9e18  # avoid a real subprocess

    app._build_menu()

    di_menu = next(item for item in app.menu.items if getattr(item, "title", None) == "Dictation Intelligence")
    modes_submenu = next(item for item in di_menu.items if getattr(item, "title", "").strip() == "Built-in Modes")
    mode_titles = _menu_titles(modes_submenu)
    assert any("Email" in t for t in mode_titles)
    assert any("Code" in t for t in mode_titles)


def test_reload_dictation_config_merges_lists(monkeypatch, tmp_path):
    """Reloading should merge only the four editable lists into config."""
    fake_rumps = types.SimpleNamespace(alert=MagicMock())
    monkeypatch.setattr("whisper_hud.app.rumps", fake_rumps)

    app = _build_recording_app()
    app.config.default_provider = "openai"  # untouched field sentinel
    cfg_path = tmp_path / "dictation.json"
    cfg_path.write_text(
        '{"custom_vocabulary": ["Anthropic"], "text_replacements": [{"pattern": "a", "replacement": "b"}],'
        ' "custom_voice_commands": [], "dictation_modes": [], "unknown_key": 123}',
        encoding="utf-8",
    )
    app._dictation_config_path = MagicMock(return_value=cfg_path)

    app._reload_dictation_config(None)

    assert app.config.custom_vocabulary == ["Anthropic"]
    assert app.config.text_replacements == [{"pattern": "a", "replacement": "b"}]
    assert app.config.default_provider == "openai"  # not clobbered
    app._notify.assert_called_once()


def test_reload_dictation_config_rejects_bad_json(monkeypatch, tmp_path):
    """Malformed JSON should alert and not change config."""
    alert = MagicMock()
    monkeypatch.setattr("whisper_hud.app.rumps", types.SimpleNamespace(alert=alert))

    app = _build_recording_app()
    app.config.custom_vocabulary = ["keep"]
    cfg_path = tmp_path / "dictation.json"
    cfg_path.write_text("{not valid json", encoding="utf-8")
    app._dictation_config_path = MagicMock(return_value=cfg_path)

    app._reload_dictation_config(None)

    assert app.config.custom_vocabulary == ["keep"]
    alert.assert_called_once()
    assert alert.call_args.kwargs["title"] == "Invalid JSON"


def test_write_dictation_template_is_user_only_and_parseable(monkeypatch, tmp_path):
    """The template should be valid JSON written with 0600 permissions."""
    import json
    import os

    app = _build_recording_app()
    app.config.custom_vocabulary = ["seed"]
    cfg_path = tmp_path / "dictation.json"
    monkeypatch.setattr("whisper_hud.config.CONFIG_DIR", tmp_path)

    assert app._write_dictation_template(cfg_path) is True
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert data["custom_vocabulary"] == ["seed"]
    assert "text_replacements" in data
    mode = os.stat(cfg_path).st_mode & 0o777
    assert mode == 0o600


def test_toggle_llm_cleanup_persists_and_resets_probe(monkeypatch):
    """Toggling cleanup should flip config and force a fresh availability probe."""
    app = _build_recording_app()
    app._schedule_menu_rebuild = MagicMock()
    app._cleanup_availability_last_checked = 999.0
    assert app.config.llm_cleanup_enabled is False

    app._toggle_llm_cleanup(None)

    assert app.config.llm_cleanup_enabled is True
    assert app._cleanup_availability_last_checked == 0.0
    app._schedule_menu_rebuild.assert_called_once()


def test_needs_setup_cloud_provider_click_opens_provider_setup(monkeypatch):
    """Clicking an unconfigured cloud provider should open its key setup dialog."""
    app = _build_menu_app(monkeypatch)
    app.transcriber.get_available_providers.return_value = [
        {"id": "openai", "name": "OpenAI", "category": "cloud", "configured": True},
        {"id": "gemini", "name": "Gemini", "category": "cloud", "configured": False},
        {
            "id": "whisper_local",
            "name": "Whisper Local",
            "category": "local",
            "configured": False,
            "requires_download": True,
        },
    ]
    gemini_provider = MagicMock(
        get_models=MagicMock(return_value=[{"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash"}]),
        get_current_model=MagicMock(return_value="gemini-2.5-flash"),
        is_configured=MagicMock(return_value=False),
    )
    openai_provider = MagicMock(
        get_models=MagicMock(return_value=[{"id": "gpt-4o", "name": "GPT-4o", "recommended": True}]),
        get_current_model=MagicMock(return_value="gpt-4o"),
        is_configured=MagicMock(return_value=True),
    )
    whisper_local_provider = MagicMock(
        get_models=MagicMock(return_value=[{"id": "tiny", "name": "Tiny", "downloaded": False}]),
        get_current_model=MagicMock(return_value="tiny"),
        is_configured=MagicMock(return_value=False),
    )
    app.transcriber.get_provider.side_effect = lambda provider_id: {
        "openai": openai_provider,
        "gemini": gemini_provider,
        "whisper_local": whisper_local_provider,
    }.get(provider_id)
    app._open_provider_setup = MagicMock()

    app._build_menu()

    provider_menu = next(item for item in app.menu.items if getattr(item, "title", None) == "Providers & Keys")
    gemini_item = next(item for item in provider_menu.items if getattr(item, "title", None) == "   Gemini ⚠️")

    gemini_item.callback(None)

    app._open_provider_setup.assert_called_once_with("gemini")


def test_set_openai_key_does_not_prefill_existing_key(monkeypatch):
    """The provider setup dialog must NOT pre-fill the existing key (prevents on-screen exposure)."""
    app = _build_recording_app()
    app._is_passphrase_mode = MagicMock(return_value=False)
    app._applescript_input_dialog = MagicMock(return_value="")
    monkeypatch.setattr("whisper_hud.app.get_api_key", MagicMock(return_value="sk-existing"))

    app._set_openai_key(None)

    app._applescript_input_dialog.assert_called_once_with(
        "Enter OpenAI API Key",
        "Enter your OpenAI API key.\n\nGet your key at: platform.openai.com/api-keys\n\nA key is already saved. Enter a new key to replace it.",
        default="",
        hidden=True,
    )


def test_open_provider_setup_uses_backing_credential_dialog():
    """Cloud provider setup should route through the backing credential provider."""
    app = _build_recording_app()
    app._set_openai_key = MagicMock()
    app._set_gemini_key = MagicMock()
    app._set_anthropic_key = MagicMock()

    app._open_provider_setup("openai_realtime")
    app._open_provider_setup("gemini")

    app._set_openai_key.assert_called_once_with(None)
    app._set_gemini_key.assert_called_once_with(None)
    app._set_anthropic_key.assert_not_called()


def test_hotkey_press_starts_recording():
    """Starting a hotkey turn should mark recording active and start the recorder."""
    app = _build_recording_app()
    app.transcriber.supports_live_input.return_value = False

    app._start_recording()

    assert app._is_recording is True
    assert app._active_turn.provider_id == "openai"
    app.recorder.start.assert_called_once_with(on_audio_chunk=None)
    app.hud.show_recording.assert_called_once_with()
    app._start_level_monitor.assert_called_once_with(1)
    app._start_max_duration_timer.assert_called_once_with(1)


def test_hotkey_release_stops_recording_and_dispatches_transcription():
    """Stopping a non-live recording turn should dispatch batch transcription directly."""
    app = _build_recording_app()
    app._is_recording = True
    app._active_turn = ActiveTranscriptionTurn(turn_id=7, provider_id="openai")
    app.recorder.stop.return_value = b"x" * 2000
    app._degrade_turn_to_batch = MagicMock()
    app._start_batch_transcription = MagicMock()

    app._stop_recording()

    assert app._is_recording is False
    assert app._active_turn.stop_reason == "manual_release"
    assert app._active_turn.batch_fallback_started is False
    app.recorder.stop.assert_called_once_with()
    app._degrade_turn_to_batch.assert_not_called()
    app._start_batch_transcription.assert_called_once_with(7)


def test_degrade_turn_to_batch_starts_batch_once():
    """Batch fallback should mark itself started only when it actually dispatches batch work."""
    app = _build_recording_app()
    turn = ActiveTranscriptionTurn(turn_id=9, provider_id="openai_realtime")
    turn.audio_bytes = b"x" * 2000
    app._active_turn = turn
    app._start_batch_transcription = MagicMock()

    app._degrade_turn_to_batch(9, "not ready")
    app._degrade_turn_to_batch(9, "still not ready")

    assert turn.batch_fallback_started is True
    app._start_batch_transcription.assert_called_once_with(9)


def test_transcription_result_is_dispatched_to_paste_pipeline(monkeypatch):
    """Successful final text should be sent through the paste target pipeline."""
    app = _build_recording_app()
    app._active_turn = ActiveTranscriptionTurn(turn_id=3, provider_id="openai")
    app._paste_to_target = MagicMock(return_value=True)
    monkeypatch.setattr("whisper_hud.app.threading.Thread", ImmediateThread)
    monkeypatch.setattr("whisper_hud.app.time.sleep", lambda _: None)

    result = TranscriptionResult(
        text="hello world",
        duration_seconds=1.0,
        cost_estimate=0.01,
        provider="openai",
        model="gpt-4o",
    )

    app._process_turn_result(3, result, use_streaming=False, stats_already_recorded=True)

    app._paste_to_target.assert_called_once_with("hello world")
    app.hud.show_success.assert_called_once_with("Done! (2 words)")
    app._finish_turn_cleanup.assert_called_once_with(3)


def test_locked_paste_target_unavailable_fails_closed():
    """Locked paste targets should not silently paste private text into the focused app."""
    app = _build_recording_app()
    app.config.paste_target_enabled = True
    app.config.paste_target_type = "app"
    app.config.paste_target_identifier = "Notes"
    app._is_target_available_cached = MagicMock(return_value=False)
    app._get_paste_target_display_name = MagicMock(return_value="Notes")

    with patch("whisper_hud.app.insert_text") as mock_insert_text:
        assert app._paste_to_target("private transcript") is False

    mock_insert_text.assert_not_called()
    app._notify.assert_called_once_with("WhisperHUD", "Target Unavailable", "Notes not found. Nothing was pasted.")


def test_empty_transcription_suppresses_success_hud(monkeypatch):
    """Whitespace-only transcriptions should not surface a success banner."""
    app = _build_recording_app()
    app._active_turn = ActiveTranscriptionTurn(turn_id=5, provider_id="openai")
    monkeypatch.setattr("whisper_hud.app.threading.Thread", ImmediateThread)

    result = TranscriptionResult(
        text="   ",
        duration_seconds=1.0,
        cost_estimate=0.01,
        provider="openai",
        model="gpt-4o",
    )

    app._process_turn_result(5, result, use_streaming=False, stats_already_recorded=True)

    app.hud.show_success.assert_not_called()
    app.hud.show_error.assert_called_once_with("No speech detected")
    app._play_completion_sound.assert_not_called()
    app._finish_turn_cleanup.assert_called_once_with(5)


def test_hud_success_message_formats_word_count():
    assert WhisperHUDApp._hud_success_message("hello") == "Done! (1 word)"
    assert WhisperHUDApp._hud_success_message("hello world") == "Done! (2 words)"
    assert WhisperHUDApp._hud_success_message("   ") == "Nothing detected"


def test_hud_success_message_preserves_suffix():
    assert WhisperHUDApp._hud_success_message("hello", " -> French") == "Done! (1 word) -> French"


def test_transcription_failure_shows_hud_error():
    """Transcription errors should surface a terminal HUD error state."""
    app = _build_recording_app()
    app._active_turn = ActiveTranscriptionTurn(turn_id=4, provider_id="openai")

    app._handle_transcription_error(4, RuntimeError("boom"), use_streaming=False)

    app.hud.show_error.assert_called_once_with("Transcription failed")
    app._notify.assert_called_once_with("WhisperHUD", "Transcription failed", "boom")
    app._finish_turn_cleanup.assert_called_once_with(4)


def test_successful_transcription_flashes_widget_success(monkeypatch):
    """A completed transcription should drive the floating widget into success."""
    app = _build_recording_app()
    app.widget = MagicMock()
    app._active_turn = ActiveTranscriptionTurn(turn_id=7, provider_id="openai")
    app._paste_to_target = MagicMock(return_value=True)
    monkeypatch.setattr("whisper_hud.app.threading.Thread", ImmediateThread)
    monkeypatch.setattr("whisper_hud.app.time.sleep", lambda _: None)

    result = TranscriptionResult(
        text="hello world",
        duration_seconds=1.0,
        cost_estimate=0.01,
        provider="openai",
        model="gpt-4o",
    )

    app._process_turn_result(7, result, use_streaming=False, stats_already_recorded=True)

    app.widget.set_success.assert_called_once_with()
    app.widget.set_error.assert_not_called()


def test_empty_transcription_flashes_widget_error(monkeypatch):
    """A whitespace-only result should drive the floating widget into error."""
    app = _build_recording_app()
    app.widget = MagicMock()
    app._active_turn = ActiveTranscriptionTurn(turn_id=8, provider_id="openai")
    monkeypatch.setattr("whisper_hud.app.threading.Thread", ImmediateThread)

    result = TranscriptionResult(
        text="   ",
        duration_seconds=1.0,
        cost_estimate=0.01,
        provider="openai",
        model="gpt-4o",
    )

    app._process_turn_result(8, result, use_streaming=False, stats_already_recorded=True)

    app.widget.set_error.assert_called_once_with()
    app.widget.set_success.assert_not_called()


def test_transcription_error_flashes_widget_error():
    """Terminal transcription errors should drive the floating widget into error."""
    app = _build_recording_app()
    app.widget = MagicMock()
    app._active_turn = ActiveTranscriptionTurn(turn_id=9, provider_id="openai")

    app._handle_transcription_error(9, RuntimeError("boom"), use_streaming=False)

    app.widget.set_error.assert_called_once_with()


# === Dictation intelligence pipeline tests =================================


def _result(text="hello world"):
    return TranscriptionResult(
        text=text,
        duration_seconds=1.0,
        cost_estimate=0.01,
        provider="openai",
        model="gpt-4o",
    )


def _build_pipeline_app(monkeypatch, turn_id=20):
    """Recording app wired for finalize_result pipeline tests."""
    app = _build_recording_app()
    app._active_turn = ActiveTranscriptionTurn(turn_id=turn_id, provider_id="openai")
    app._paste_to_target = MagicMock(return_value=True)
    app.cleanup_engine = MagicMock()
    monkeypatch.setattr("whisper_hud.app.threading.Thread", ImmediateThread)
    monkeypatch.setattr("whisper_hud.app.time.sleep", lambda _: None)
    return app


def test_voice_command_discard_short_circuits(monkeypatch):
    """A discard command must skip history and paste entirely."""
    app = _build_pipeline_app(monkeypatch, turn_id=21)
    app.config.voice_commands_enabled = True
    app.config.add_to_history = MagicMock(return_value=True)

    app._process_turn_result(21, _result("scratch that"), use_streaming=False, stats_already_recorded=True)

    app._paste_to_target.assert_not_called()
    app.config.add_to_history.assert_not_called()
    app.hud.show_success.assert_called_once_with("Discarded")
    app._finish_turn_cleanup.assert_called_once_with(21)


def test_voice_command_keystroke_skips_paste(monkeypatch):
    """A keystroke command performs the keystroke and skips paste/history."""
    app = _build_pipeline_app(monkeypatch, turn_id=22)
    app.config.voice_commands_enabled = True
    app.config.add_to_history = MagicMock(return_value=True)

    with patch("whisper_hud.app.send_keystroke") as mock_send:
        app._process_turn_result(22, _result("press enter"), use_streaming=False, stats_already_recorded=True)

    mock_send.assert_called_once_with("return")
    app._paste_to_target.assert_not_called()
    app.config.add_to_history.assert_not_called()
    app._finish_turn_cleanup.assert_called_once_with(22)


def test_voice_command_insert_becomes_final_text_skipping_processing(monkeypatch):
    """An insert command's payload is pasted verbatim; replacements/cleanup are skipped."""
    app = _build_pipeline_app(monkeypatch, turn_id=23)
    app.config.voice_commands_enabled = True
    app.config.text_replacements = [{"pattern": "x", "replacement": "y"}]
    app.config.llm_cleanup_enabled = True
    app._apply_text_replacements = MagicMock(side_effect=AssertionError("replacements should be skipped"))

    app._process_turn_result(23, _result("new line"), use_streaming=False, stats_already_recorded=True)

    # "new line" inserts a newline payload.
    app._paste_to_target.assert_called_once_with("\n")
    app.cleanup_engine.cleanup.assert_not_called()


def test_voice_command_insert_payload_skips_translation(monkeypatch):
    """An insert payload must NOT be sent through translation even when it is enabled."""
    app = _build_pipeline_app(monkeypatch, turn_id=231)
    app.config.voice_commands_enabled = True
    app.config.translation_enabled = True
    app.translator.supports_streaming.return_value = False

    app._process_turn_result(231, _result("new line"), use_streaming=False, stats_already_recorded=True)

    # The literal newline payload is pasted verbatim; the translator is bypassed.
    app.translator.translate.assert_not_called()
    app._paste_to_target.assert_called_once_with("\n")


def test_custom_insert_command_payload_skips_translation(monkeypatch):
    """A user-defined insert command's payload is pasted verbatim, never translated."""
    app = _build_pipeline_app(monkeypatch, turn_id=232)
    app.config.voice_commands_enabled = True
    app.config.translation_enabled = True
    app.translator.supports_streaming.return_value = False
    app.config.custom_voice_commands = [
        {"id": "signature", "phrase": "insert signature", "action": "insert", "payload": "Best,\nJacob"}
    ]

    app._process_turn_result(232, _result("insert signature"), use_streaming=False, stats_already_recorded=True)

    app.translator.translate.assert_not_called()
    app._paste_to_target.assert_called_once_with("Best,\nJacob")


def test_normal_dictation_still_translates_when_enabled(monkeypatch):
    """Inverse sanity check: ordinary dictation (no command) still goes through translation."""
    app = _build_pipeline_app(monkeypatch, turn_id=233)
    app.config.voice_commands_enabled = True
    app.config.translation_enabled = True
    translation = MagicMock()
    translation.text = "hola mundo"
    app.translator.supports_streaming.return_value = False
    app.translator.translate.return_value = translation
    app.translator.get_supported_languages.return_value = {"es": "Spanish"}

    app._process_turn_result(233, _result("hello world"), use_streaming=False, stats_already_recorded=True)

    app.translator.translate.assert_called_once()
    app._paste_to_target.assert_called_once_with("hola mundo")


def test_replacements_applied_before_paste(monkeypatch):
    """Configured replacements should transform the transcript before pasting."""
    app = _build_pipeline_app(monkeypatch, turn_id=24)
    app.config.text_replacements = [{"pattern": "teh", "replacement": "the"}]

    app._process_turn_result(24, _result("teh cat"), use_streaming=False, stats_already_recorded=True)

    app._paste_to_target.assert_called_once_with("the cat")


def test_llm_cleanup_runs_and_is_guarded(monkeypatch):
    """When enabled, cleanup output (guard-checked by the engine) becomes the pasted text."""
    app = _build_pipeline_app(monkeypatch, turn_id=25)
    app.config.llm_cleanup_enabled = True
    app.cleanup_engine.pick_model.return_value = "qwen3:1.7b"
    app.cleanup_engine.cleanup.return_value = "Hello, world."

    app._process_turn_result(25, _result("hello world"), use_streaming=False, stats_already_recorded=True)

    app.cleanup_engine.cleanup.assert_called_once()
    # The engine receives the raw (post-replacement) text and the timeout.
    _, kwargs = app.cleanup_engine.cleanup.call_args
    assert kwargs["timeout"] == app.config.llm_cleanup_timeout_seconds
    app._paste_to_target.assert_called_once_with("Hello, world.")


def test_llm_cleanup_failure_falls_back_to_raw(monkeypatch):
    """If the engine returns None (failure), the raw transcript is pasted."""
    app = _build_pipeline_app(monkeypatch, turn_id=26)
    app.config.llm_cleanup_enabled = True
    app.cleanup_engine.pick_model.return_value = "qwen3:1.7b"
    app.cleanup_engine.cleanup.return_value = None

    app._process_turn_result(26, _result("hello world"), use_streaming=False, stats_already_recorded=True)

    app._paste_to_target.assert_called_once_with("hello world")


def test_llm_cleanup_skipped_when_no_model(monkeypatch):
    """No installed model means cleanup is skipped and raw text is used."""
    app = _build_pipeline_app(monkeypatch, turn_id=27)
    app.config.llm_cleanup_enabled = True
    app.cleanup_engine.pick_model.return_value = None

    app._process_turn_result(27, _result("hello world"), use_streaming=False, stats_already_recorded=True)

    app.cleanup_engine.cleanup.assert_not_called()
    app._paste_to_target.assert_called_once_with("hello world")


def test_translation_receives_post_cleanup_text(monkeypatch):
    """Translation must operate on the cleaned text, not the raw transcript."""
    app = _build_pipeline_app(monkeypatch, turn_id=28)
    app.config.llm_cleanup_enabled = True
    app.config.translation_enabled = True
    app.cleanup_engine.pick_model.return_value = "qwen3:1.7b"
    app.cleanup_engine.cleanup.return_value = "Hola mundo crudo"
    translation = MagicMock()
    translation.text = "Hello raw world"
    app.translator.supports_streaming.return_value = False
    app.translator.translate.return_value = translation
    app.translator.get_supported_languages.return_value = {"en": "English"}

    app._process_turn_result(28, _result("hello world"), use_streaming=False, stats_already_recorded=True)

    _, kwargs = app.translator.translate.call_args
    assert kwargs["text"] == "Hola mundo crudo"
    app._paste_to_target.assert_called_once_with("Hello raw world")


def test_mode_auto_send_presses_return_after_paste(monkeypatch):
    """A matching auto-send mode should press Return after a successful paste."""
    app = _build_pipeline_app(monkeypatch, turn_id=29)
    app.config.dictation_modes_enabled = True
    app._active_turn.frontmost_app_name = "Slack"  # matches builtin "messages" mode (auto_send False)
    # Use a custom mode with auto_send to be deterministic.
    app.config.dictation_modes = [{"id": "chat", "name": "Chat", "app_patterns": ["Slack"], "auto_send": True}]

    with patch("whisper_hud.app.send_keystroke") as mock_send:
        app._process_turn_result(29, _result("hi team"), use_streaming=False, stats_already_recorded=True)

    app._paste_to_target.assert_called_once_with("hi team")
    mock_send.assert_called_once_with("return")


def test_mode_auto_send_skipped_when_paste_fails(monkeypatch):
    """Auto-send must not fire if the paste did not succeed."""
    app = _build_pipeline_app(monkeypatch, turn_id=30)
    app._paste_to_target.return_value = False
    app.config.dictation_modes_enabled = True
    app._active_turn.frontmost_app_name = "Slack"
    app.config.dictation_modes = [{"id": "chat", "name": "Chat", "app_patterns": ["Slack"], "auto_send": True}]

    with patch("whisper_hud.app.send_keystroke") as mock_send:
        app._process_turn_result(30, _result("hi team"), use_streaming=False, stats_already_recorded=True)

    mock_send.assert_not_called()


def test_vocabulary_merges_custom_and_mode(monkeypatch):
    """Resolved vocabulary should combine global vocab and the active mode's vocab."""
    app = _build_recording_app()
    app.config.custom_vocabulary = ["Anthropic"]
    app.config.dictation_modes_enabled = True
    app.config.dictation_modes = [{"id": "code", "app_patterns": ["Code"], "vocabulary": ["Kubernetes"]}]
    turn = ActiveTranscriptionTurn(turn_id=31, provider_id="openai")
    turn.frontmost_app_name = "Code"

    vocab = app._resolve_vocabulary(turn)

    assert "Anthropic" in vocab
    assert "Kubernetes" in vocab


def test_vocabulary_custom_only_when_modes_disabled(monkeypatch):
    """With modes off, only the global custom vocabulary is used."""
    app = _build_recording_app()
    app.config.custom_vocabulary = ["Anthropic"]
    app.config.dictation_modes_enabled = False
    app.config.dictation_modes = [{"id": "code", "app_patterns": ["Code"], "vocabulary": ["Kubernetes"]}]
    turn = ActiveTranscriptionTurn(turn_id=32, provider_id="openai")
    turn.frontmost_app_name = "Code"

    vocab = app._resolve_vocabulary(turn)

    assert vocab == ["Anthropic"]


def test_batch_transcription_passes_vocabulary(monkeypatch):
    """Batch transcription should forward the resolved vocabulary to the manager."""
    app = _build_recording_app()
    app.config.custom_vocabulary = ["Anthropic"]
    turn = ActiveTranscriptionTurn(turn_id=33, provider_id="openai")
    turn.audio_bytes = b"x" * 2000
    app._active_turn = turn
    app.transcriber.transcribe.return_value = _result("hi")
    app._process_turn_result = MagicMock()
    monkeypatch.setattr("whisper_hud.app.threading.Thread", ImmediateThread)

    app._start_batch_transcription(33)

    _, kwargs = app.transcriber.transcribe.call_args
    assert kwargs["vocabulary"] == ["Anthropic"]


def test_capture_frontmost_app_only_when_modes_enabled(monkeypatch):
    """The frontmost-app subprocess should be skipped unless modes are enabled."""
    app = _build_recording_app()
    turn = ActiveTranscriptionTurn(turn_id=34, provider_id="openai")

    with patch("whisper_hud.app.get_frontmost_app", return_value="Code") as mock_front:
        app.config.dictation_modes_enabled = False
        app._capture_frontmost_app(turn)
        mock_front.assert_not_called()
        assert turn.frontmost_app_name is None

        app.config.dictation_modes_enabled = True
        app._capture_frontmost_app(turn)
        mock_front.assert_called_once_with()
        assert turn.frontmost_app_name == "Code"


def test_select_provider_updates_config_and_rebuilds_menu():
    """Selecting a provider should persist the new default provider and rebuild the menu."""
    app = WhisperHUDApp.__new__(WhisperHUDApp)
    app.config = Config()
    app.config.save = MagicMock(return_value=True)
    app._schedule_menu_rebuild = MagicMock()

    app._select_provider("gemini")

    assert app.config.default_provider == "gemini"
    app.config.save.assert_called_once_with()
    app._schedule_menu_rebuild.assert_called_once_with()


def test_hotkey_config_opens_capture_panel_with_existing_hotkey(monkeypatch):
    app = _build_recording_app()
    app.hotkey_listener = MagicMock()
    monkeypatch.setattr("whisper_hud.app.HotkeyCapturePanel", FakeCapturePanel)
    FakeCapturePanel.instances.clear()

    app._change_hotkey(None)

    assert app._is_capturing_hotkey is True
    app.hotkey_listener.stop.assert_called_once_with()
    assert len(FakeCapturePanel.instances) == 1
    assert FakeCapturePanel.instances[0].current_hotkey == ["cmd", "shift", "space"]
    FakeCapturePanel.instances[0].show.assert_called_once_with()


def test_hotkey_config_cancel_restores_listener():
    app = _build_recording_app()
    app._is_capturing_hotkey = True
    app._restart_hotkey_listener = MagicMock()
    panel = FakeCapturePanel(["cmd", "shift", "space"], MagicMock(), MagicMock())
    app._hotkey_capture_panel = panel

    app._cancel_hotkey_capture()

    assert app._is_capturing_hotkey is False
    assert app._hotkey_capture_panel is None
    panel.close.assert_called_once_with()
    app._restart_hotkey_listener.assert_called_once_with()


def test_hotkey_config_capture_saves_and_restarts_listener(monkeypatch):
    class FakeHotkeyListener:
        def __init__(self, on_start, on_stop, hotkey, mode):
            self.on_start = on_start
            self.on_stop = on_stop
            self.hotkey = hotkey
            self.mode = mode
            self.start = MagicMock()

    app = _build_recording_app()
    app.hotkey_listener = MagicMock()
    app._is_capturing_hotkey = True
    app._hotkey_capture_panel = FakeCapturePanel(["cmd", "shift", "space"], MagicMock(), MagicMock())
    app._refresh_widget_tooltip = MagicMock()
    app._schedule_menu_rebuild = MagicMock()
    app._build_hotkey_set = MagicMock(return_value={"new-hotkey"})
    monkeypatch.setattr("whisper_hud.app.HotkeyListener", FakeHotkeyListener)

    app._on_hotkey_captured({"new-hotkey"}, ["cmd", "alt", "r"])

    assert app.config.hotkey == ["cmd", "alt", "r"]
    app.config.save.assert_called_once_with()
    assert isinstance(app.hotkey_listener, FakeHotkeyListener)
    assert app.hotkey_listener.hotkey == {"new-hotkey"}
    app.hotkey_listener.start.assert_called_once_with()
    app._notify.assert_called_once_with("WhisperHUD", "Hotkey Changed", "New hotkey: ⌘⌥R")
    app._refresh_widget_tooltip.assert_called_once_with()
    app._schedule_menu_rebuild.assert_called_once_with()


# === File transcription + history upgrade tests ============================


def test_build_menu_exposes_transcribe_file_action(monkeypatch):
    """The Providers & Keys menu should include the 'Transcribe Audio File…' action."""
    app = _build_menu_app(monkeypatch)

    app._build_menu()

    provider_menu = next(item for item in app.menu.items if getattr(item, "title", None) == "Providers & Keys")
    provider_titles = _menu_titles(provider_menu)
    assert "Transcribe Audio File…" in provider_titles
    # Top-level structure must remain unchanged (no new top-level entry).
    assert "Transcribe Audio File…" not in _menu_titles(app.menu)


def test_history_menu_exposes_view_search_and_size(monkeypatch):
    """History submenu should expose View/Search and a History Size submenu."""
    app = _build_menu_app(monkeypatch)
    app.config.history_enabled = True
    app.config.private_mode = False
    app.config.history = [{"text": "hello", "timestamp": 1, "provider": "openai"}]

    app._build_menu()

    settings_menu = next(item for item in app.menu.items if getattr(item, "title", None) == "Settings")
    history_menu = next(item for item in settings_menu.items if getattr(item, "title", None) == "History & Stats")
    history_titles = _menu_titles(history_menu)
    assert "View History…" in history_titles
    assert "Search History…" in history_titles

    size_menu = next(item for item in history_menu.items if getattr(item, "title", None) == "History Size")
    size_titles = _menu_titles(size_menu)
    # Default cap is 50 -> the 50 option is marked selected.
    assert any("50 entries" in t and t.startswith("● ") for t in size_titles)
    assert any("200 entries" in t for t in size_titles)


def test_view_history_blocks_in_private_mode():
    """The history viewer must refuse to render anything in private mode."""
    app = _build_recording_app()
    app.config.private_mode = True
    app._open_history_view = MagicMock()

    app._view_history(None)

    app._open_history_view.assert_not_called()
    app._notify.assert_called_once()
    assert app._notify.call_args.args[1] == "Private Mode"


def test_view_history_blocks_when_history_empty():
    """An empty history should surface a notice instead of an empty file."""
    app = _build_recording_app()
    app.config.private_mode = False
    app.config.history_enabled = True
    app.config.history = []
    app._open_history_view = MagicMock()

    app._view_history(None)

    app._open_history_view.assert_not_called()
    assert app._notify.call_args.args[1] == "History Empty"


def test_view_history_renders_entries_to_viewer():
    """With saved entries, the viewer should be invoked with the decrypted list."""
    app = _build_recording_app()
    app.config.private_mode = False
    app.config.history_enabled = True
    app.config.history_encrypted = False
    app.config.history = [
        {"text": "first", "timestamp": 1, "provider": "openai", "source": "mic"},
        {"text": "second", "timestamp": 2, "provider": "apple", "source": "file"},
    ]
    app._open_history_view = MagicMock()

    app._view_history(None)

    app._open_history_view.assert_called_once()
    rendered_entries = app._open_history_view.call_args.args[0]
    assert len(rendered_entries) == 2


def test_write_history_view_file_is_user_only(monkeypatch, tmp_path):
    """The history view file must be written 0600 in the scratch dir."""
    import os

    app = _build_recording_app()
    monkeypatch.setattr(
        "whisper_hud.encryption.get_private_scratch_dir",
        lambda: tmp_path,
    )

    path = app._write_history_view_file("hello history\n")

    assert path is not None
    assert os.path.exists(path)
    mode = os.stat(path).st_mode & 0o777
    assert mode == 0o600
    with open(path, encoding="utf-8") as f:
        assert "hello history" in f.read()


class FakeTimer:
    """threading.Timer stand-in that records its schedule and fires on demand."""

    instances = []

    def __init__(self, interval, function, args=None, kwargs=None):
        self.interval = interval
        self.function = function
        self.args = args or ()
        self.kwargs = kwargs or {}
        self.daemon = False
        self.started = False
        FakeTimer.instances.append(self)

    def start(self):
        self.started = True

    def fire(self):
        self.function(*self.args, **self.kwargs)


def test_open_history_view_registers_and_schedules_secure_delete(monkeypatch, tmp_path):
    """Opening the history viewer must register the export and arm a delete timer."""
    import os
    import subprocess

    FakeTimer.instances.clear()
    app = _build_recording_app()
    app._history_view_files = []
    monkeypatch.setattr("whisper_hud.encryption.get_private_scratch_dir", lambda: tmp_path)
    monkeypatch.setattr(subprocess, "run", MagicMock())
    monkeypatch.setattr("whisper_hud.app.threading.Timer", FakeTimer)

    entries = [{"text": "secret transcript", "timestamp": 0, "provider": "openai"}]
    app._open_history_view(entries)

    # The plaintext export exists, is tracked for the quit-sweep, and a daemon
    # timer was armed to securely delete that exact path.
    assert len(app._history_view_files) == 1
    path = app._history_view_files[0]
    assert os.path.exists(path)
    assert len(FakeTimer.instances) == 1
    timer = FakeTimer.instances[0]
    assert timer.started is True
    assert timer.daemon is True
    assert timer.args == (path,)
    assert timer.function == app._delete_history_view_file

    # Firing the timer securely deletes the export and forgets it.
    timer.fire()
    assert not os.path.exists(path)
    assert path not in app._history_view_files


def test_quit_sweeps_pending_history_view_files(monkeypatch, tmp_path):
    """_quit must shred any history exports still on disk before quitting."""
    import os
    import subprocess

    FakeTimer.instances.clear()
    app = _build_recording_app()
    app._history_view_files = []
    monkeypatch.setattr("whisper_hud.encryption.get_private_scratch_dir", lambda: tmp_path)
    monkeypatch.setattr(subprocess, "run", MagicMock())
    monkeypatch.setattr("whisper_hud.app.threading.Timer", FakeTimer)

    app._open_history_view([{"text": "secret", "timestamp": 0, "provider": "openai"}])
    path = app._history_view_files[0]
    assert os.path.exists(path)

    # Stub out the rest of the shutdown path so _quit only exercises the sweep.
    app._active_turn = None
    app.hotkey_listener = MagicMock()
    app._detach_menu_observers = MagicMock()
    with (
        patch("whisper_hud.app.lock_passphrase_store"),
        patch("whisper_hud.app.lock_history_encryption"),
        patch("whisper_hud.app.rumps.quit_application") as mock_quit,
    ):
        app._quit(None)

    mock_quit.assert_called_once()
    assert not os.path.exists(path)
    assert app._history_view_files == []


def test_render_history_entries_includes_tags_and_full_text():
    """Rendering should include source/provider/model tags and full text."""
    entries = [
        {
            "text": "the full transcript body",
            "timestamp": 0,
            "provider": "apple",
            "source": "file",
            "model": "en-US",
            "duration_seconds": 65,
        }
    ]
    rendered = WhisperHUDApp._render_history_entries(entries, header="2 matches for 'x'")
    assert "2 matches for 'x'" in rendered
    assert "source: file" in rendered
    assert "provider: apple" in rendered
    assert "model: en-US" in rendered
    assert "duration: 1:05" in rendered
    assert "the full transcript body" in rendered


def test_render_history_entries_tolerates_legacy_entries():
    """Old entries without the new keys should still render without error."""
    entries = [{"text": "legacy", "timestamp": 0, "provider": "openai", "translated": False}]
    rendered = WhisperHUDApp._render_history_entries(entries)
    assert "legacy" in rendered
    # No crash and no source tag rendered for the missing key.
    assert "source:" not in rendered


def test_search_history_filters_and_opens_matches(monkeypatch):
    """Search should case-insensitively match text/provider/source and open matches."""
    app = _build_recording_app()
    app.config.private_mode = False
    app.config.history_enabled = True
    app.config.history_encrypted = False
    app.config.history = [
        {"text": "Buy milk and eggs", "timestamp": 1, "provider": "openai", "source": "mic"},
        {"text": "Meeting notes", "timestamp": 2, "provider": "apple", "source": "file"},
    ]
    app._applescript_input_dialog = MagicMock(return_value="MILK")
    app._open_history_view = MagicMock()

    app._search_history(None)

    app._open_history_view.assert_called_once()
    matches = app._open_history_view.call_args.args[0]
    assert len(matches) == 1
    assert matches[0]["text"] == "Buy milk and eggs"
    header = app._open_history_view.call_args.kwargs.get("header", "")
    assert "1 match" in header


def test_search_history_reports_no_matches(monkeypatch):
    """A query with no hits should notify and not open the viewer."""
    app = _build_recording_app()
    app.config.private_mode = False
    app.config.history_enabled = True
    app.config.history_encrypted = False
    app.config.history = [{"text": "hello", "timestamp": 1, "provider": "openai", "source": "mic"}]
    app._applescript_input_dialog = MagicMock(return_value="zzz")
    app._open_history_view = MagicMock()

    app._search_history(None)

    app._open_history_view.assert_not_called()
    assert app._notify.call_args.args[1] == "No Matches"


def test_set_history_size_persists_and_notifies():
    """Selecting a new history size should persist and notify."""
    app = _build_recording_app()
    app.config.set_history_max_items = MagicMock(return_value=True)

    app._set_history_size(100)

    app.config.set_history_max_items.assert_called_once_with(100)
    app._schedule_menu_rebuild.assert_called_once()
    assert app._notify.call_args.args[1] == "History Size Updated"


def test_transcribe_audio_file_blocks_when_cloud_keys_locked():
    """File transcription must not run when required cloud keys are locked."""
    app = _build_recording_app()
    app._ensure_cloud_credentials_ready = MagicMock(return_value=False)
    app._pick_audio_file = MagicMock()

    app._transcribe_audio_file(None)

    app._pick_audio_file.assert_not_called()
    app._notify.assert_called_once()
    assert app._notify.call_args.args[1] == "Cloud Keys Locked"


def test_transcribe_audio_file_rejects_invalid_file(monkeypatch):
    """An unsupported file should surface an error and never transcribe."""
    app = _build_recording_app()
    app._ensure_cloud_credentials_ready = MagicMock(return_value=True)
    app._pick_audio_file = MagicMock(return_value="/tmp/notes.txt")
    monkeypatch.setattr("whisper_hud.app.threading.Thread", ImmediateThread)

    app._transcribe_audio_file(None)

    app.transcriber.transcribe.assert_not_called()
    app.hud.show_error.assert_called_once_with("Unsupported file")
    assert app._notify.call_args.args[1] == "Cannot Transcribe File"


def test_transcribe_audio_file_happy_path_copies_and_stores(monkeypatch):
    """A successful file transcription copies to clipboard and stores with source=file."""
    app = _build_recording_app()
    app._ensure_cloud_credentials_ready = MagicMock(return_value=True)
    app._pick_audio_file = MagicMock(return_value="/tmp/clip.mp3")
    app._resolve_vocabulary = MagicMock(return_value=["Anthropic"])
    app.config.add_to_history = MagicMock(return_value=True)
    app._reset_title_after_delay = MagicMock()
    monkeypatch.setattr("whisper_hud.app.validate_audio_file", lambda path: (True, ""))
    monkeypatch.setattr("whisper_hud.app.threading.Thread", ImmediateThread)
    monkeypatch.setattr("whisper_hud.app.time.sleep", lambda _: None)

    fake_outcome = {
        "text": "decoded transcript",
        "char_count": len("decoded transcript"),
        "duration_seconds": 65,
        "provider": "apple",
        "model": "en-US",
    }
    monkeypatch.setattr("whisper_hud.app.transcribe_file", lambda path, **kwargs: fake_outcome)
    fake_pyperclip = types.SimpleNamespace(copy=MagicMock())
    monkeypatch.setitem(sys.modules, "pyperclip", fake_pyperclip)

    app._transcribe_audio_file(None)

    fake_pyperclip.copy.assert_called_once_with("decoded transcript")
    app.config.add_to_history.assert_called_once()
    kwargs = app.config.add_to_history.call_args.kwargs
    assert kwargs["source"] == "file"
    assert kwargs["provider"] == "apple"
    app.hud.show_success.assert_called_once()


def test_transcribe_audio_file_surfaces_decode_error(monkeypatch):
    """A FileTranscriptionError should be turned into a user-facing error."""
    from whisper_hud.file_transcription import FileTranscriptionError

    app = _build_recording_app()
    app._ensure_cloud_credentials_ready = MagicMock(return_value=True)
    app._pick_audio_file = MagicMock(return_value="/tmp/clip.mp3")
    app._resolve_vocabulary = MagicMock(return_value=None)
    app._reset_title_after_delay = MagicMock()
    monkeypatch.setattr("whisper_hud.app.validate_audio_file", lambda path: (True, ""))
    monkeypatch.setattr("whisper_hud.app.threading.Thread", ImmediateThread)

    def boom(path, **kwargs):
        raise FileTranscriptionError("Could not decode that audio file.")

    monkeypatch.setattr("whisper_hud.app.transcribe_file", boom)

    app._transcribe_audio_file(None)

    app.hud.show_error.assert_called_once_with("File transcription failed")
    assert app._notify.call_args.args[1] == "File Transcription Failed"
