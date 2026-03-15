from unittest.mock import MagicMock

from whisper_hud import appearance_editor


class FakePreview:
    def __init__(self):
        self.colors = []
        self.custom_shapes = []
        self.icons = []

    def setColors_iconColor_(self, background, icon):
        self.colors.append((background, icon))

    def setUseCustomShape_(self, enabled):
        self.custom_shapes.append(enabled)

    def setCustomIcon_(self, icon):
        self.icons.append(icon)


class FakeButton:
    @classmethod
    def alloc(cls):
        return cls()

    def initWithFrame_(self, frame):
        self.frame = frame
        self.title = None
        self.action = None
        self.target = None
        return self

    def setTitle_(self, title):
        self.title = title

    def setBezelStyle_(self, style):
        self.style = style

    def setTarget_(self, target):
        self.target = target

    def setAction_(self, action):
        self.action = action

    def setKeyEquivalent_(self, key):
        self.key = key


class FakeContentView:
    def __init__(self):
        self.subviews = []

    def addSubview_(self, view):
        self.subviews.append(view)


def _make_editor(mock_config):
    image_processor = MagicMock()
    image_processor.clear_cache = MagicMock()
    return appearance_editor.AppearanceEditorWindow(mock_config, image_processor, MagicMock(), MagicMock())


def test_add_navigation_buttons_includes_reset_button(mock_config, monkeypatch):
    editor = _make_editor(mock_config)
    content = FakeContentView()

    monkeypatch.setattr(appearance_editor, "NSButton", FakeButton)
    monkeypatch.setattr(appearance_editor, "NSMakeRect", lambda *args: args)
    monkeypatch.setattr(appearance_editor, "NSBezelStyleRounded", "rounded")

    editor._delegate = object()
    editor._add_navigation_buttons(content, 480, show_back=False, show_next=False, show_save=False)

    assert any(view.title == "Reset to Defaults" and view.action == "resetToDefaults:" for view in content.subviews)


def test_handle_reset_to_defaults_restores_factory_defaults(mock_config, monkeypatch):
    editor = _make_editor(mock_config)
    defaults = appearance_editor._get_default_widget_appearance()

    editor._working_config["theme"] = "custom"
    editor._working_config["colors"]["idle"]["background"] = "#010203"
    editor._working_config["custom_icon"]["enabled"] = True
    editor._working_config["font"] = {"family": "Mono"}
    editor._working_config["timing"] = {"fade_ms": 999}
    editor._current_step = 2
    editor._show_step = MagicMock()

    monkeypatch.setattr(editor, "_confirm_reset_to_defaults", lambda: True)

    editor.handleResetToDefaults()

    assert editor._working_config == defaults
    editor._show_step.assert_called_once_with(2)


def test_handle_reset_to_defaults_respects_cancel(mock_config, monkeypatch):
    editor = _make_editor(mock_config)
    original = appearance_editor.deepcopy(editor._working_config)
    editor._show_step = MagicMock()

    monkeypatch.setattr(editor, "_confirm_reset_to_defaults", lambda: False)

    editor.handleResetToDefaults()

    assert editor._working_config == original
    editor._show_step.assert_not_called()


def test_update_icon_previews_updates_all_five_states(mock_config):
    editor = _make_editor(mock_config)
    editor._working_config = appearance_editor._get_default_widget_appearance()
    editor._working_config["custom_icon"]["enabled"] = True
    editor._working_config["custom_icon"]["path"] = "/tmp/icon.png"
    editor._working_config["custom_icon"]["shape_mode"] = "alpha"

    previews = {f"icon_{state}": FakePreview() for state in appearance_editor.WIDGET_STATES}
    editor._preview_views = previews
    editor._image_processor.get_preview.side_effect = (
        lambda path, size, tint, opacity, shape: f"{path}|{tint}|{opacity}|{shape}"
    )

    editor._update_icon_previews()

    assert editor._image_processor.get_preview.call_count == len(appearance_editor.WIDGET_STATES)
    for state in appearance_editor.WIDGET_STATES:
        preview = previews[f"icon_{state}"]
        colors = editor._working_config["colors"][state]
        assert preview.colors[-1] == (colors["background"], colors["icon"])
        assert preview.custom_shapes[-1] is True
        assert preview.icons[-1] is not None


def test_handle_color_well_changed_updates_state_preview_and_icon_previews(mock_config, monkeypatch):
    editor = _make_editor(mock_config)
    sender = MagicMock()
    sender.color.return_value = object()

    state_preview = FakePreview()
    icon_preview = FakePreview()
    editor._color_wells = {"success_bg": sender}
    editor._preview_views = {"success": state_preview, "icon_success": icon_preview}
    editor._update_icon_previews = MagicMock()

    monkeypatch.setattr(appearance_editor, "_nscolor_to_hex", lambda color: "#ABCDEF")

    editor.handleColorWellChanged(sender)

    assert editor._working_config["colors"]["success"]["background"] == "#ABCDEF"
    assert state_preview.colors[-1] == ("#ABCDEF", "#FFFFFF")
    editor._update_icon_previews.assert_called_once_with()


def test_handle_save_persists_factory_defaults_without_forcing_custom_theme(mock_config):
    on_save = MagicMock()
    on_cancel = MagicMock()
    image_processor = MagicMock()
    window = MagicMock()

    editor = appearance_editor.AppearanceEditorWindow(mock_config, image_processor, on_save, on_cancel)
    editor._working_config = appearance_editor._get_default_widget_appearance()
    editor._window = window
    editor._config.save = MagicMock(return_value=True)

    editor.handleSave()

    assert editor._config.widget_appearance == appearance_editor._get_default_widget_appearance()
    assert editor._config.widget_appearance["theme"] == "default"
    editor._config.save.assert_called_once_with()
    image_processor.clear_cache.assert_called_once_with()
    window.close.assert_called_once_with()
    on_save.assert_called_once_with(editor._config.widget_appearance)
