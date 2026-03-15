from types import SimpleNamespace

from whisper_hud.setup_wizard import SetupWizard, WizardStep
import whisper_hud.setup_wizard as setup_wizard


class _FakeContentView:
    def __init__(self):
        self.subviews = []

    def addSubview_(self, view):
        self.subviews.append(view)


def test_get_step_sequence_defaults_to_local_path():
    wizard = SetupWizard()

    assert wizard._get_step_sequence() == [
        WizardStep.WELCOME,
        WizardStep.TRANSCRIPTION_MODE,
        WizardStep.LOCAL_SETUP,
        WizardStep.TRANSLATION,
        WizardStep.COMPLETE,
    ]


def test_get_step_progress_tracks_cloud_flow_when_navigating_back():
    wizard = SetupWizard()
    wizard._transcription_mode = "cloud"

    assert wizard._get_step_progress(WizardStep.CLOUD_SETUP) == (3, 5)
    assert wizard._get_step_progress(WizardStep.TRANSLATION) == (4, 5)
    assert wizard._get_step_progress(WizardStep.COMPLETE) == (5, 5)


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

    assert [label.text for label in labels] == ["Step 4 of 5", "● ● ● ● ○"]
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
