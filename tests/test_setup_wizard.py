from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from whisper_hud.setup_wizard import SetupWizard, WizardStep
import whisper_hud.setup_wizard as setup_wizard


class _FakeContentView:
    def __init__(self):
        self.subviews = []

    def addSubview_(self, view):
        self.subviews.append(view)


class _FakeButtonCell:
    def __init__(self):
        self.wraps = None
        self.uses_single_line_mode = None
        self.scrollable = None
        self.line_break_mode = None

    def setWraps_(self, value):
        self.wraps = value

    def setUsesSingleLineMode_(self, value):
        self.uses_single_line_mode = value

    def setScrollable_(self, value):
        self.scrollable = value

    def setLineBreakMode_(self, value):
        self.line_break_mode = value


class _FakeButton:
    def __init__(self, frame):
        self.frame = frame
        self.title = None
        self.attributed_title = None
        self.bezel_style = None
        self.target = None
        self.action = None
        self.state = None
        self._cell = _FakeButtonCell()

    def setTitle_(self, value):
        self.title = value

    def setAttributedTitle_(self, value):
        self.attributed_title = value

    def setBezelStyle_(self, value):
        self.bezel_style = value

    def setTarget_(self, value):
        self.target = value

    def setAction_(self, value):
        self.action = value

    def setState_(self, value):
        self.state = value

    def cell(self):
        return self._cell

    def setFrame_(self, frame):
        self.frame = frame


class _FakeButtonFactory:
    def alloc(self):
        return self

    def initWithFrame_(self, frame):
        return _FakeButton(frame)


def test_get_step_sequence_defaults_to_local_path():
    wizard = SetupWizard()

    assert wizard._get_step_sequence() == [
        WizardStep.WELCOME,
        WizardStep.TRANSCRIPTION_MODE,
        WizardStep.LOCAL_SETUP,
        WizardStep.PERMISSIONS,
        WizardStep.TRANSLATION,
        WizardStep.COMPLETE,
    ]


def test_get_step_progress_tracks_cloud_flow_when_navigating_back():
    wizard = SetupWizard()
    wizard._transcription_mode = "cloud"

    assert wizard._get_step_progress(WizardStep.CLOUD_SETUP) == (3, 6)
    assert wizard._get_step_progress(WizardStep.PERMISSIONS) == (4, 6)
    assert wizard._get_step_progress(WizardStep.TRANSLATION) == (5, 6)
    assert wizard._get_step_progress(WizardStep.COMPLETE) == (6, 6)


def test_add_step_progress_renders_label_and_dots(monkeypatch):
    wizard = SetupWizard()
    wizard._transcription_mode = "cloud"
    wizard._content_view = _FakeContentView()

    labels = []

    def fake_label(text, frame, **kwargs):
        view = SimpleNamespace(text=text, frame=frame, kwargs=kwargs)
        labels.append(view)
        return view

    monkeypatch.setattr(wizard, "_create_label", fake_label)
    monkeypatch.setattr(wizard, "_secondary_text_color", lambda: "secondary")
    monkeypatch.setattr(wizard, "_accent_text_color", lambda: "accent")

    wizard._add_step_progress(WizardStep.TRANSLATION)

    assert [label.text for label in labels] == ["Step 5 of 6", "● ● ● ● ● ○"]
    assert wizard._content_view.subviews == labels


def test_skip_translation_disables_translation_and_advances():
    wizard = SetupWizard()
    wizard._translation_enabled = True
    shown_steps = []
    wizard._show_step = shown_steps.append

    wizard._skip_translation_setup()

    assert wizard._translation_enabled is False
    assert shown_steps == [WizardStep.COMPLETE]


def test_detect_dark_mode_uses_effective_appearance(monkeypatch):
    wizard = SetupWizard()

    class _Appearance:
        def __init__(self, match):
            self._match = match

        def bestMatchFromAppearancesWithNames_(self, _names):
            return self._match

    class _Application:
        def __init__(self, appearance):
            self._appearance = appearance

        def effectiveAppearance(self):
            return self._appearance

    monkeypatch.setattr(setup_wizard, "NSAppearanceNameAqua", "aqua", raising=False)
    monkeypatch.setattr(setup_wizard, "NSAppearanceNameDarkAqua", "dark", raising=False)
    monkeypatch.setattr(
        setup_wizard,
        "NSApplication",
        SimpleNamespace(sharedApplication=lambda: _Application(_Appearance("dark"))),
        raising=False,
    )

    assert wizard._detect_dark_mode() is True

    monkeypatch.setattr(
        setup_wizard,
        "NSApplication",
        SimpleNamespace(sharedApplication=lambda: _Application(_Appearance("aqua"))),
        raising=False,
    )

    assert wizard._detect_dark_mode() is False


def test_create_provider_button_uses_wrapped_title_and_keeps_minimum_height(monkeypatch):
    wizard = SetupWizard()

    frame = SimpleNamespace(
        origin=SimpleNamespace(x=0, y=0),
        size=SimpleNamespace(width=280, height=40),
    )
    recorded = {}

    monkeypatch.setattr(setup_wizard, "NSButton", _FakeButtonFactory(), raising=False)
    monkeypatch.setattr(setup_wizard, "HAS_APPKIT", False, raising=False)
    monkeypatch.setattr(
        wizard,
        "_apply_wrapped_button_title",
        lambda button, text, button_frame, font_size, align=0, minimum_height=None: recorded.update(
            {
                "button": button,
                "text": text,
                "frame": button_frame,
                "font_size": font_size,
                "minimum_height": minimum_height,
            }
        )
        or button,
    )

    button = wizard._create_provider_button(
        "OpenAI Whisper",
        "Requires API key",
        frame,
        selected=True,
        action=lambda: None,
    )

    assert button.bezel_style == 1
    assert button.state == 1
    assert recorded["text"] == "OpenAI Whisper\nRequires API key"
    assert recorded["font_size"] == 13
    assert recorded["minimum_height"] == 40


def test_apply_wrapped_button_title_expands_height_for_multiline(monkeypatch):
    wizard = SetupWizard()
    frame = SimpleNamespace(
        origin=SimpleNamespace(x=0, y=0),
        size=SimpleNamespace(width=180, height=40),
    )
    button = _FakeButton(frame)

    monkeypatch.setattr(setup_wizard, "HAS_APPKIT", False, raising=False)

    wizard._apply_wrapped_button_title(
        button,
        "Cloud\nFast & Accurate\n\nUses API (OpenAI or Gemini)\nRequires internet connection\nPay per use or free tier",
        frame,
        font_size=13,
        minimum_height=40,
    )

    assert button.title.startswith("Cloud\nFast & Accurate")
    assert button.frame.size.height > 40
    assert button.cell().wraps is True
    assert button.cell().uses_single_line_mode is False
    assert button.cell().scrollable is False


def test_apply_wrapped_button_title_keeps_single_line_height(monkeypatch):
    wizard = SetupWizard()
    frame = SimpleNamespace(
        origin=SimpleNamespace(x=0, y=0),
        size=SimpleNamespace(width=220, height=32),
    )
    button = _FakeButton(frame)

    monkeypatch.setattr(setup_wizard, "HAS_APPKIT", False, raising=False)

    wizard._apply_wrapped_button_title(
        button,
        "Next",
        frame,
        font_size=13,
        minimum_height=32,
    )

    assert button.frame.size.height == 32


class _FakeTimer:
    instances = []

    def __init__(self, interval, callback):
        self.interval = interval
        self.callback = callback
        self.cancelled = False
        self.started = False
        self.daemon = False
        _FakeTimer.instances.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


class _ImmediateThread:
    def __init__(self, target=None, daemon=None):
        self._target = target
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True
        if self._target:
            self._target()


class _FakeSpinner:
    def __init__(self):
        self.hidden = None
        self.started = 0
        self.stopped = 0

    def setHidden_(self, hidden):
        self.hidden = hidden

    def startAnimation_(self, _sender):
        self.started += 1

    def stopAnimation_(self, _sender):
        self.stopped += 1


class _FakeLabel:
    def __init__(self):
        self.value = None
        self.color = None

    def setStringValue_(self, value):
        self.value = value

    def setTextColor_(self, color):
        self.color = color


class _FakeSimpleButton:
    def __init__(self):
        self.enabled = None

    def setEnabled_(self, enabled):
        self.enabled = enabled


def _attach_cloud_controls(wizard):
    wizard._api_key_spinner = _FakeSpinner()
    wizard._api_key_status_icon = _FakeLabel()
    wizard._api_key_status_label = _FakeLabel()
    wizard._skip_validation_button = _FakeSimpleButton()
    wizard._next_button = _FakeSimpleButton()


class TestSetupWizardApiKeyValidation:
    def setup_method(self):
        _FakeTimer.instances.clear()

    def test_api_key_validation_is_debounced_for_500ms(self):
        wizard = SetupWizard()
        wizard._current_step = WizardStep.CLOUD_SETUP
        wizard._selected_provider = "openai"
        wizard._api_key_field = MagicMock()
        wizard._api_key_field.stringValue.side_effect = ["sk-first", "sk-second"]
        _attach_cloud_controls(wizard)

        with patch("whisper_hud.setup_wizard.threading.Timer", _FakeTimer):
            wizard._handle_api_key_input_changed()
            first_timer = wizard._api_key_validation_timer
            wizard._handle_api_key_input_changed()

        assert len(_FakeTimer.instances) == 2
        assert first_timer.cancelled is True
        assert wizard._api_key_validation_timer is _FakeTimer.instances[-1]
        assert wizard._api_key_validation_timer.interval == 0.5
        assert wizard._next_button.enabled is False

    def test_api_key_validation_runs_in_background_and_enables_next_on_success(self):
        wizard = SetupWizard()
        wizard._current_step = WizardStep.CLOUD_SETUP
        wizard._selected_provider = "openai"
        wizard._api_key = "sk-valid"
        _attach_cloud_controls(wizard)
        request_id = wizard._next_api_key_validation_request_id()

        with patch.object(wizard, "_dispatch_to_main_thread", side_effect=lambda callback: callback()):
            with patch("whisper_hud.setup_wizard.threading.Thread", _ImmediateThread):
                with patch("whisper_hud.keychain.validate_api_key", return_value=(True, "")) as mock_validate:
                    wizard._begin_api_key_validation(request_id, "openai", "sk-valid")

        mock_validate.assert_called_once_with("openai", "sk-valid")
        assert wizard._api_key_validation_status == "valid"
        assert wizard._api_key_status_icon.value == "✓"
        assert wizard._api_key_status_label.value == "API key validated"
        assert wizard._api_key_spinner.hidden is True
        assert wizard._next_button.enabled is True

    def test_api_key_validation_can_be_skipped_after_invalid_result(self):
        wizard = SetupWizard()
        wizard._current_step = WizardStep.CLOUD_SETUP
        wizard._selected_provider = "gemini"
        wizard._api_key = "bad-key"
        _attach_cloud_controls(wizard)
        request_id = wizard._next_api_key_validation_request_id()

        with patch.object(wizard, "_dispatch_to_main_thread", side_effect=lambda callback: callback()):
            with patch("whisper_hud.setup_wizard.threading.Thread", _ImmediateThread):
                with patch("whisper_hud.keychain.validate_api_key", return_value=(False, "Invalid API key")):
                    wizard._begin_api_key_validation(request_id, "gemini", "bad-key")

        assert wizard._api_key_validation_status == "invalid"
        assert wizard._api_key_status_icon.value == "✗"
        assert wizard._api_key_status_label.value == "Invalid API key"
        assert wizard._next_button.enabled is False

        wizard._skip_api_key_validation()

        assert wizard._api_key_validation_status == "skipped"
        assert wizard._api_key_validation_acknowledged is True
        assert wizard._next_button.enabled is True

    def test_api_key_validation_skip_allows_continue(self):
        wizard = SetupWizard()
        wizard._current_step = WizardStep.CLOUD_SETUP
        wizard._selected_provider = "openai"
        wizard._api_key = "not-validated"
        wizard._api_key_validation_status = "skipped"
        wizard._api_key_validation_acknowledged = True
        wizard._api_key_field = MagicMock()
        wizard._api_key_field.stringValue.return_value = "not-validated"
        _attach_cloud_controls(wizard)

        with patch("whisper_hud.keychain.get_storage_mode", return_value="none"):
            with patch("whisper_hud.keychain.set_api_key", return_value=True) as mock_set:
                with patch.object(wizard, "_show_step") as mock_show_step:
                    wizard._validate_and_continue_cloud()

        mock_set.assert_called_once_with("openai", "not-validated")
        mock_show_step.assert_called_once_with(WizardStep.PERMISSIONS)


def test_permissions_step_blocks_when_microphone_denied():
    wizard = SetupWizard()
    wizard._permission_statuses = {
        "microphone": {
            "status": wizard.PERMISSION_STATUS_DENIED,
            "message": "blocked",
        },
        "accessibility": {
            "status": wizard.PERMISSION_STATUS_NOT_DETERMINED,
            "message": "later",
        },
    }

    assert wizard._can_continue_permissions_step() is False


def test_permissions_step_allows_accessibility_denial():
    wizard = SetupWizard()
    wizard._permission_statuses = {
        "microphone": {
            "status": wizard.PERMISSION_STATUS_GRANTED,
            "message": "ready",
        },
        "accessibility": {
            "status": wizard.PERMISSION_STATUS_DENIED,
            "message": "blocked",
        },
    }

    assert wizard._can_continue_permissions_step() is True


def test_local_setup_advances_to_permissions():
    wizard = SetupWizard()
    shown_steps = []
    wizard._show_step = shown_steps.append

    wizard._continue_from_local_setup()

    assert shown_steps == [WizardStep.PERMISSIONS]


def test_go_back_from_translation_returns_to_permissions():
    wizard = SetupWizard()
    shown_steps = []
    wizard._show_step = shown_steps.append

    wizard._go_back_from_translation()

    assert shown_steps == [WizardStep.PERMISSIONS]


def test_open_permission_settings_uses_expected_deep_link(monkeypatch):
    wizard = SetupWizard()
    calls = []

    def fake_run(cmd, capture_output, timeout):
        calls.append((cmd, capture_output, timeout))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(setup_wizard.subprocess, "run", fake_run)

    assert wizard._open_permission_settings("microphone") is True
    assert wizard._open_permission_settings("accessibility") is True
    assert calls == [
        (["open", wizard.MICROPHONE_SETTINGS_URL], True, 5),
        (["open", wizard.ACCESSIBILITY_SETTINGS_URL], True, 5),
    ]


def test_accessibility_permission_state_defaults_to_not_determined(monkeypatch):
    wizard = SetupWizard()

    monkeypatch.setattr(setup_wizard, "HAS_ACCESSIBILITY_API", True, raising=False)
    monkeypatch.setattr(setup_wizard, "AXIsProcessTrusted", lambda: False, raising=False)

    state = wizard._get_accessibility_permission_state()

    assert state["status"] == wizard.PERMISSION_STATUS_NOT_DETERMINED


def test_accessibility_permission_state_changes_to_denied_after_settings_opened(monkeypatch):
    wizard = SetupWizard()
    wizard._permission_settings_opened.add("accessibility")

    monkeypatch.setattr(setup_wizard, "HAS_ACCESSIBILITY_API", True, raising=False)
    monkeypatch.setattr(setup_wizard, "AXIsProcessTrusted", lambda: False, raising=False)

    state = wizard._get_accessibility_permission_state()

    assert state["status"] == wizard.PERMISSION_STATUS_DENIED


def test_microphone_permission_state_maps_avfoundation_status(monkeypatch):
    wizard = SetupWizard()
    fake_capture_device = SimpleNamespace(authorizationStatusForMediaType_=lambda _media: 2)

    monkeypatch.setattr(setup_wizard, "HAS_AVFOUNDATION", True, raising=False)
    monkeypatch.setattr(setup_wizard, "AVCaptureDevice", fake_capture_device, raising=False)
    monkeypatch.setattr(setup_wizard, "AVMediaTypeAudio", "audio", raising=False)

    state = wizard._get_microphone_permission_state()

    assert state["status"] == wizard.PERMISSION_STATUS_DENIED


def test_window_did_become_key_refreshes_permissions_step(monkeypatch):
    wizard = SetupWizard()
    wizard._current_step = WizardStep.PERMISSIONS
    calls = []

    monkeypatch.setattr(wizard, "_refresh_permission_statuses", lambda: calls.append("refresh"))
    monkeypatch.setattr(wizard, "_show_step", lambda step: calls.append(step))

    wizard.windowDidBecomeKey_(None)

    assert calls == ["refresh", WizardStep.PERMISSIONS]


def test_finish_wizard_stops_when_microphone_denied(monkeypatch):
    wizard = SetupWizard()
    wizard._permission_statuses = {
        "microphone": {
            "status": wizard.PERMISSION_STATUS_DENIED,
            "message": "blocked",
        },
        "accessibility": {
            "status": wizard.PERMISSION_STATUS_GRANTED,
            "message": "ready",
        },
    }
    errors = []

    monkeypatch.setattr(wizard, "_refresh_permission_statuses", lambda: None)
    monkeypatch.setattr(wizard, "_show_error", errors.append)

    wizard._finish_wizard()

    assert errors == ["Microphone permission is required before finishing setup"]
