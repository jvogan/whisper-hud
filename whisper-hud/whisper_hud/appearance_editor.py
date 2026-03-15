"""
Appearance Editor for WhisperHUD Widget.

A multi-step wizard for customizing widget colors and icons:
- Step 1: Color customization per state
- Step 2: Custom icon upload with circle crop preview
- Step 3: Preview all states

Uses PyObjC for native macOS UI.
"""

from copy import deepcopy
from typing import Callable, Optional

from .config import Config
from .logging_config import get_logger

logger = get_logger("appearance_editor")

try:
    from AppKit import (
        NSWindow,
        NSView,
        NSButton,
        NSTextField,
        NSColor,
        NSFont,
        NSWindowStyleMaskTitled,
        NSWindowStyleMaskClosable,
        NSBackingStoreBuffered,
        NSScreen,
        NSMakeRect,
        NSColorWell,
        NSSlider,
        NSBezierPath,
        NSOpenPanel,
        NSApplication,
        NSTextAlignmentCenter,
        NSBezelStyleRounded,
        NSCompositingOperationSourceOver,
        NSZeroRect,
        NSControlStateValueOn,
        NSControlStateValueOff,
        NSObject,
        NSAlert,
    )
    from PyObjCTools import AppHelper
    from objc import super as objc_super

    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False


# States to configure
WIDGET_STATES = ["idle", "recording", "processing", "success", "error"]
STATE_LABELS = {
    "idle": "Idle",
    "recording": "Recording",
    "processing": "Processing",
    "success": "Success",
    "error": "Error",
}


def _get_default_widget_appearance() -> dict:
    """Return a fresh copy of the factory-default appearance config."""
    default_factory = Config.__dataclass_fields__["widget_appearance"].default_factory
    return deepcopy(default_factory())


def _hex_to_nscolor(hex_color: str) -> "NSColor":
    """Convert hex color string to NSColor."""
    if not HAS_APPKIT:
        return None
    try:
        hex_color = hex_color.lstrip("#")
        if len(hex_color) >= 6:
            r = int(hex_color[0:2], 16) / 255.0
            g = int(hex_color[2:4], 16) / 255.0
            b = int(hex_color[4:6], 16) / 255.0
            return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 1.0)
    except Exception:
        pass
    return NSColor.whiteColor()


def _nscolor_to_hex(color: "NSColor") -> str:
    """Convert NSColor to hex string."""
    if not HAS_APPKIT or not color:
        return "#FFFFFF"
    try:
        # Convert to RGB color space
        rgb_color = color.colorUsingColorSpaceName_("NSCalibratedRGBColorSpace")
        if rgb_color:
            r = int(rgb_color.redComponent() * 255)
            g = int(rgb_color.greenComponent() * 255)
            b = int(rgb_color.blueComponent() * 255)
            return f"#{r:02X}{g:02X}{b:02X}"
    except Exception:
        pass
    return "#FFFFFF"


if HAS_APPKIT:

    class PreviewWidgetView(NSView):
        """Preview widget that displays current appearance."""

        def initWithFrame_(self, frame):
            self = objc_super(PreviewWidgetView, self).initWithFrame_(frame)
            if self is None:
                return None

            self._bg_color = "#232329"
            self._icon_color = "#66A5FF"
            self._custom_icon = None
            self._use_custom_shape = False  # Whether icon has custom shape (non-circle)

            self.setWantsLayer_(True)
            return self

        def setColors_iconColor_(self, bg_color, icon_color):
            self._bg_color = bg_color
            self._icon_color = icon_color
            self.setNeedsDisplay_(True)

        def setCustomIcon_(self, icon):
            self._custom_icon = icon
            self.setNeedsDisplay_(True)

        def setUseCustomShape_(self, use_custom):
            self._use_custom_shape = use_custom
            self.setNeedsDisplay_(True)

        def drawRect_(self, rect):
            bounds = self.bounds()
            size = min(bounds.size.width, bounds.size.height)

            # Center the circle
            x = (bounds.size.width - size) / 2
            y = (bounds.size.height - size) / 2

            # For custom shapes, use minimal background
            if self._custom_icon and self._use_custom_shape:
                # Clear background for custom shape
                NSColor.clearColor().set()
                NSBezierPath.fillRect_(bounds)

                # Subtle glow behind icon
                bg_color = _hex_to_nscolor(self._bg_color)
                glow_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    bg_color.redComponent(), bg_color.greenComponent(), bg_color.blueComponent(), 0.3
                )
                glow_color.setFill()
                glow_rect = NSMakeRect(x, y, size, size)
                glow_path = NSBezierPath.bezierPathWithOvalInRect_(glow_rect)
                glow_path.fill()
            else:
                # Draw background circle
                circle_rect = NSMakeRect(x, y, size, size)
                path = NSBezierPath.bezierPathWithOvalInRect_(circle_rect)

                bg_color = _hex_to_nscolor(self._bg_color)
                bg_color.setFill()
                path.fill()

            # Draw icon (inner circle or custom icon)
            icon_size = size * 0.45
            icon_offset = (size - icon_size) / 2
            icon_rect = NSMakeRect(x + icon_offset, y + icon_offset, icon_size, icon_size)

            if self._custom_icon:
                self._custom_icon.drawInRect_fromRect_operation_fraction_(
                    icon_rect, NSZeroRect, NSCompositingOperationSourceOver, 1.0
                )
            else:
                icon_path = NSBezierPath.bezierPathWithOvalInRect_(icon_rect)
                icon_color = _hex_to_nscolor(self._icon_color)
                icon_color.setFill()
                icon_path.fill()

    class EditorDelegate(NSObject):
        """Delegate class to handle UI actions (must inherit from NSObject for PyObjC)."""

        def initWithEditor_(self, editor):
            self = objc_super(EditorDelegate, self).init()
            if self is None:
                return None
            self._editor = editor
            return self

        def colorWellChanged_(self, sender):
            self._editor.handleColorWellChanged(sender)

        def browseForIcon_(self, sender):
            self._editor.handleBrowseForIcon()

        def clearIcon_(self, sender):
            self._editor.handleClearIcon()

        def tintCheckboxChanged_(self, sender):
            self._editor.handleTintCheckboxChanged(sender)

        def tintSliderChanged_(self, sender):
            self._editor.handleTintSliderChanged(sender)

        def shapeModeChanged_(self, sender):
            self._editor.handleShapeModeChanged(sender)

        def goBack_(self, sender):
            self._editor.handleGoBack()

        def goNext_(self, sender):
            self._editor.handleGoNext()

        def cancel_(self, sender):
            self._editor.handleCancel()

        def save_(self, sender):
            self._editor.handleSave()

        def resetToDefaults_(self, sender):
            self._editor.handleResetToDefaults()


class AppearanceEditorWindow:
    """
    Appearance editor window with multi-step wizard.
    """

    def __init__(self, config, image_processor, on_save: Callable, on_cancel: Callable):
        self._config = config
        self._image_processor = image_processor
        self._on_save = on_save
        self._on_cancel = on_cancel

        self._window: Optional[NSWindow] = None
        self._current_step = 1
        self._max_steps = 2  # Simplified to 2 steps: Colors and Icon

        # Working copy of appearance config
        self._working_config = deepcopy(config.widget_appearance)
        self._apply_missing_defaults()

        # UI elements
        self._color_wells = {}
        self._preview_views = {}
        self._selected_state = "idle"
        self._icon_path_field = None
        self._tint_checkbox = None
        self._tint_slider = None
        self._icon_preview = None
        self._shape_mode_buttons = {}  # Radio buttons for shape mode

        # Create delegate for handling actions
        self._delegate = None

    def _apply_missing_defaults(self):
        """Backfill any missing appearance settings from the factory defaults."""

        def _merge_defaults(target, defaults):
            for key, value in defaults.items():
                if key not in target:
                    target[key] = deepcopy(value)
                    continue

                if isinstance(value, dict) and isinstance(target[key], dict):
                    _merge_defaults(target[key], value)

        _merge_defaults(self._working_config, _get_default_widget_appearance())

    def show(self):
        """Show the editor window."""
        if not HAS_APPKIT:
            logger.error("AppKit not available, cannot show editor")
            return

        def _create_and_show():
            self._create_window()
            self._show_step(1)
            self._window.makeKeyAndOrderFront_(None)
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

        AppHelper.callAfter(_create_and_show)

    def _create_window(self):
        """Create the editor window."""
        # Create delegate for handling actions
        self._delegate = EditorDelegate.alloc().initWithEditor_(self)

        # Window size
        width, height = 640, 480

        # Center on screen
        screen = NSScreen.mainScreen()
        if screen:
            screen_rect = screen.visibleFrame()
            x = screen_rect.origin.x + (screen_rect.size.width - width) / 2
            y = screen_rect.origin.y + (screen_rect.size.height - height) / 2
        else:
            x, y = 100, 100

        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, width, height),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False,
        )
        self._window.setTitle_("Customize Appearance")
        self._window.setReleasedWhenClosed_(False)

    def _clear_content(self):
        """Clear the window content."""
        if self._window:
            content = self._window.contentView()
            for subview in list(content.subviews()):
                subview.removeFromSuperview()

    def _show_step(self, step: int):
        """Show a specific step of the wizard."""
        self._current_step = step
        self._clear_content()

        if step == 1:
            self._build_colors_step()
        elif step == 2:
            self._build_icon_step()

    def _build_colors_step(self):
        """Build Step 1: Color customization."""
        content = self._window.contentView()
        width = self._window.frame().size.width
        height = self._window.frame().size.height

        # Title
        title = NSTextField.alloc().initWithFrame_(NSMakeRect(20, height - 50, width - 40, 30))
        title.setStringValue_("Step 1: Customize Colors")
        title.setFont_(NSFont.boldSystemFontOfSize_(18))
        title.setBezeled_(False)
        title.setDrawsBackground_(False)
        title.setEditable_(False)
        title.setSelectable_(False)
        content.addSubview_(title)

        # Subtitle
        subtitle = NSTextField.alloc().initWithFrame_(NSMakeRect(20, height - 75, width - 40, 20))
        subtitle.setStringValue_("Set background and icon colors for each widget state")
        subtitle.setFont_(NSFont.systemFontOfSize_(12))
        subtitle.setTextColor_(NSColor.secondaryLabelColor())
        subtitle.setBezeled_(False)
        subtitle.setDrawsBackground_(False)
        subtitle.setEditable_(False)
        subtitle.setSelectable_(False)
        content.addSubview_(subtitle)

        # State color editors
        y_pos = height - 120
        colors = self._working_config.get("colors", {})

        for state in WIDGET_STATES:
            state_colors = colors.get(state, {})
            bg_color = state_colors.get("background", "#232329")
            icon_color = state_colors.get("icon", "#66A5FF")

            # State label
            label = NSTextField.alloc().initWithFrame_(NSMakeRect(20, y_pos, 100, 24))
            label.setStringValue_(STATE_LABELS.get(state, state.title()))
            label.setFont_(NSFont.systemFontOfSize_(13))
            label.setBezeled_(False)
            label.setDrawsBackground_(False)
            label.setEditable_(False)
            label.setSelectable_(False)
            content.addSubview_(label)

            # Background color well
            bg_label = NSTextField.alloc().initWithFrame_(NSMakeRect(130, y_pos, 80, 24))
            bg_label.setStringValue_("Background:")
            bg_label.setFont_(NSFont.systemFontOfSize_(11))
            bg_label.setBezeled_(False)
            bg_label.setDrawsBackground_(False)
            bg_label.setEditable_(False)
            bg_label.setSelectable_(False)
            content.addSubview_(bg_label)

            bg_well = NSColorWell.alloc().initWithFrame_(NSMakeRect(210, y_pos, 44, 24))
            bg_well.setColor_(_hex_to_nscolor(bg_color))
            bg_well.setTarget_(self._delegate)
            bg_well.setAction_("colorWellChanged:")
            bg_well.setTag_(hash(f"{state}_bg") & 0x7FFFFFFF)
            content.addSubview_(bg_well)
            self._color_wells[f"{state}_bg"] = bg_well

            # Icon color well
            icon_label = NSTextField.alloc().initWithFrame_(NSMakeRect(270, y_pos, 50, 24))
            icon_label.setStringValue_("Icon:")
            icon_label.setFont_(NSFont.systemFontOfSize_(11))
            icon_label.setBezeled_(False)
            icon_label.setDrawsBackground_(False)
            icon_label.setEditable_(False)
            icon_label.setSelectable_(False)
            content.addSubview_(icon_label)

            icon_well = NSColorWell.alloc().initWithFrame_(NSMakeRect(320, y_pos, 44, 24))
            icon_well.setColor_(_hex_to_nscolor(icon_color))
            icon_well.setTarget_(self._delegate)
            icon_well.setAction_("colorWellChanged:")
            icon_well.setTag_(hash(f"{state}_icon") & 0x7FFFFFFF)
            content.addSubview_(icon_well)
            self._color_wells[f"{state}_icon"] = icon_well

            # Preview widget
            preview = PreviewWidgetView.alloc().initWithFrame_(NSMakeRect(400, y_pos - 10, 44, 44))
            preview.setColors_iconColor_(bg_color, icon_color)
            content.addSubview_(preview)
            self._preview_views[state] = preview

            y_pos -= 55

        # Navigation buttons
        self._add_navigation_buttons(content, height, show_back=False, show_next=True)

    def _build_icon_step(self):
        """Build Step 2: Custom icon configuration."""
        content = self._window.contentView()
        width = self._window.frame().size.width
        height = self._window.frame().size.height

        # Title
        title = NSTextField.alloc().initWithFrame_(NSMakeRect(20, height - 50, width - 40, 30))
        title.setStringValue_("Step 2: Custom Icon (Optional)")
        title.setFont_(NSFont.boldSystemFontOfSize_(18))
        title.setBezeled_(False)
        title.setDrawsBackground_(False)
        title.setEditable_(False)
        title.setSelectable_(False)
        content.addSubview_(title)

        # Subtitle
        subtitle = NSTextField.alloc().initWithFrame_(NSMakeRect(20, height - 75, width - 40, 20))
        subtitle.setStringValue_("Upload a custom image to replace the default circle icon")
        subtitle.setFont_(NSFont.systemFontOfSize_(12))
        subtitle.setTextColor_(NSColor.secondaryLabelColor())
        subtitle.setBezeled_(False)
        subtitle.setDrawsBackground_(False)
        subtitle.setEditable_(False)
        subtitle.setSelectable_(False)
        content.addSubview_(subtitle)

        # Current icon path
        custom_icon = self._working_config.get("custom_icon", {})
        current_path = custom_icon.get("path", "")
        current_shape_mode = custom_icon.get("shape_mode", "auto")

        path_label = NSTextField.alloc().initWithFrame_(NSMakeRect(20, height - 120, 100, 24))
        path_label.setStringValue_("Icon file:")
        path_label.setFont_(NSFont.systemFontOfSize_(13))
        path_label.setBezeled_(False)
        path_label.setDrawsBackground_(False)
        path_label.setEditable_(False)
        path_label.setSelectable_(False)
        content.addSubview_(path_label)

        self._icon_path_field = NSTextField.alloc().initWithFrame_(NSMakeRect(120, height - 120, 350, 24))
        self._icon_path_field.setStringValue_(current_path if current_path else "No custom icon")
        self._icon_path_field.setFont_(NSFont.systemFontOfSize_(11))
        self._icon_path_field.setEditable_(False)
        self._icon_path_field.setSelectable_(True)
        content.addSubview_(self._icon_path_field)

        # Browse button
        browse_btn = NSButton.alloc().initWithFrame_(NSMakeRect(480, height - 122, 80, 28))
        browse_btn.setTitle_("Browse...")
        browse_btn.setBezelStyle_(NSBezelStyleRounded)
        browse_btn.setTarget_(self._delegate)
        browse_btn.setAction_("browseForIcon:")
        content.addSubview_(browse_btn)

        # Clear button
        clear_btn = NSButton.alloc().initWithFrame_(NSMakeRect(565, height - 122, 55, 28))
        clear_btn.setTitle_("Clear")
        clear_btn.setBezelStyle_(NSBezelStyleRounded)
        clear_btn.setTarget_(self._delegate)
        clear_btn.setAction_("clearIcon:")
        content.addSubview_(clear_btn)

        # Shape mode section
        shape_label = NSTextField.alloc().initWithFrame_(NSMakeRect(20, height - 155, 100, 24))
        shape_label.setStringValue_("Icon Shape:")
        shape_label.setFont_(NSFont.systemFontOfSize_(13))
        shape_label.setBezeled_(False)
        shape_label.setDrawsBackground_(False)
        shape_label.setEditable_(False)
        shape_label.setSelectable_(False)
        content.addSubview_(shape_label)

        # Shape mode radio buttons
        shape_modes = [
            ("auto", "Auto", "Detect best shape automatically"),
            ("circle", "Circle", "Crop to circle (default)"),
            ("alpha", "Alpha", "Use PNG transparency"),
            ("subject", "Subject", "AI background removal"),
        ]

        # Check if rembg is available
        has_rembg = self._image_processor.is_rembg_available()

        self._shape_mode_buttons = {}
        x_pos = 120
        for mode_id, mode_label, mode_desc in shape_modes:
            btn = NSButton.alloc().initWithFrame_(NSMakeRect(x_pos, height - 155, 100, 20))
            btn.setButtonType_(4)  # Radio button
            btn.setTitle_(mode_label)
            btn.setFont_(NSFont.systemFontOfSize_(11))
            btn.setState_(NSControlStateValueOn if mode_id == current_shape_mode else NSControlStateValueOff)
            btn.setTarget_(self._delegate)
            btn.setAction_("shapeModeChanged:")
            btn.setTag_(hash(mode_id) & 0x7FFFFFFF)

            # Disable "subject" if rembg not available
            if mode_id == "subject" and not has_rembg:
                btn.setEnabled_(False)
                btn.setToolTip_("Install 'rembg' package for AI background removal")
            else:
                btn.setToolTip_(mode_desc)

            content.addSubview_(btn)
            self._shape_mode_buttons[mode_id] = btn
            x_pos += 110

        # Rembg availability note
        if not has_rembg:
            note = NSTextField.alloc().initWithFrame_(NSMakeRect(120, height - 175, 400, 14))
            note.setStringValue_("Note: Install 'rembg' package for AI subject extraction")
            note.setFont_(NSFont.systemFontOfSize_(10))
            note.setTextColor_(NSColor.secondaryLabelColor())
            note.setBezeled_(False)
            note.setDrawsBackground_(False)
            note.setEditable_(False)
            note.setSelectable_(False)
            content.addSubview_(note)

        # Tinting options (moved down to accommodate shape mode)
        apply_tint = custom_icon.get("apply_state_tint", True)
        tint_opacity = custom_icon.get("tint_opacity", 0.3)

        self._tint_checkbox = NSButton.alloc().initWithFrame_(NSMakeRect(20, height - 200, 250, 24))
        self._tint_checkbox.setButtonType_(3)  # Switch/checkbox
        self._tint_checkbox.setTitle_("Apply state color tint to icon")
        self._tint_checkbox.setState_(NSControlStateValueOn if apply_tint else NSControlStateValueOff)
        self._tint_checkbox.setTarget_(self._delegate)
        self._tint_checkbox.setAction_("tintCheckboxChanged:")
        content.addSubview_(self._tint_checkbox)

        # Tint opacity slider
        opacity_label = NSTextField.alloc().initWithFrame_(NSMakeRect(40, height - 230, 100, 20))
        opacity_label.setStringValue_("Tint opacity:")
        opacity_label.setFont_(NSFont.systemFontOfSize_(11))
        opacity_label.setBezeled_(False)
        opacity_label.setDrawsBackground_(False)
        opacity_label.setEditable_(False)
        opacity_label.setSelectable_(False)
        content.addSubview_(opacity_label)

        self._tint_slider = NSSlider.alloc().initWithFrame_(NSMakeRect(140, height - 230, 200, 20))
        self._tint_slider.setMinValue_(0.0)
        self._tint_slider.setMaxValue_(1.0)
        self._tint_slider.setDoubleValue_(tint_opacity)
        self._tint_slider.setTarget_(self._delegate)
        self._tint_slider.setAction_("tintSliderChanged:")
        content.addSubview_(self._tint_slider)

        # Icon preview area (moved down)
        preview_label = NSTextField.alloc().initWithFrame_(NSMakeRect(20, height - 275, 100, 20))
        preview_label.setStringValue_("Preview:")
        preview_label.setFont_(NSFont.boldSystemFontOfSize_(13))
        preview_label.setBezeled_(False)
        preview_label.setDrawsBackground_(False)
        preview_label.setEditable_(False)
        preview_label.setSelectable_(False)
        content.addSubview_(preview_label)

        # Show previews for each state
        x_pos = 20
        for state in WIDGET_STATES:
            state_label = NSTextField.alloc().initWithFrame_(NSMakeRect(x_pos, height - 305, 80, 16))
            state_label.setStringValue_(STATE_LABELS.get(state, state))
            state_label.setFont_(NSFont.systemFontOfSize_(10))
            state_label.setAlignment_(NSTextAlignmentCenter)
            state_label.setBezeled_(False)
            state_label.setDrawsBackground_(False)
            state_label.setEditable_(False)
            state_label.setSelectable_(False)
            content.addSubview_(state_label)

            colors = self._working_config.get("colors", {}).get(state, {})
            preview = PreviewWidgetView.alloc().initWithFrame_(NSMakeRect(x_pos + 10, height - 385, 60, 60))
            preview.setColors_iconColor_(colors.get("background", "#232329"), colors.get("icon", "#66A5FF"))

            # Load custom icon preview if enabled
            if current_path and custom_icon.get("enabled", False):
                icon_image = self._image_processor.get_preview(
                    current_path,
                    60,
                    colors.get("icon", "") if apply_tint and state != "idle" else "",
                    tint_opacity if apply_tint else 0,
                    current_shape_mode,
                )
                preview.setCustomIcon_(icon_image)

            content.addSubview_(preview)
            self._preview_views[f"icon_{state}"] = preview

            x_pos += 120

        # Navigation buttons
        self._add_navigation_buttons(content, height, show_back=True, show_next=False, show_save=True)

    def _add_navigation_buttons(self, content, height, show_back=True, show_next=True, show_save=False):
        """Add navigation buttons at the bottom."""
        y = 20

        # Cancel button
        cancel_btn = NSButton.alloc().initWithFrame_(NSMakeRect(20, y, 80, 32))
        cancel_btn.setTitle_("Cancel")
        cancel_btn.setBezelStyle_(NSBezelStyleRounded)
        cancel_btn.setTarget_(self._delegate)
        cancel_btn.setAction_("cancel:")
        content.addSubview_(cancel_btn)

        reset_btn = NSButton.alloc().initWithFrame_(NSMakeRect(110, y, 140, 32))
        reset_btn.setTitle_("Reset to Defaults")
        reset_btn.setBezelStyle_(NSBezelStyleRounded)
        reset_btn.setTarget_(self._delegate)
        reset_btn.setAction_("resetToDefaults:")
        content.addSubview_(reset_btn)

        if show_back:
            back_btn = NSButton.alloc().initWithFrame_(NSMakeRect(440, y, 80, 32))
            back_btn.setTitle_("Back")
            back_btn.setBezelStyle_(NSBezelStyleRounded)
            back_btn.setTarget_(self._delegate)
            back_btn.setAction_("goBack:")
            content.addSubview_(back_btn)

        if show_next:
            next_btn = NSButton.alloc().initWithFrame_(NSMakeRect(540, y, 80, 32))
            next_btn.setTitle_("Next")
            next_btn.setBezelStyle_(NSBezelStyleRounded)
            next_btn.setKeyEquivalent_("\r")  # Enter key
            next_btn.setTarget_(self._delegate)
            next_btn.setAction_("goNext:")
            content.addSubview_(next_btn)

        if show_save:
            save_btn = NSButton.alloc().initWithFrame_(NSMakeRect(540, y, 80, 32))
            save_btn.setTitle_("Save")
            save_btn.setBezelStyle_(NSBezelStyleRounded)
            save_btn.setKeyEquivalent_("\r")
            save_btn.setTarget_(self._delegate)
            save_btn.setAction_("save:")
            content.addSubview_(save_btn)

    # Action handlers (called by EditorDelegate)
    def handleColorWellChanged(self, sender):
        """Handle color well change."""
        color = sender.color()
        hex_color = _nscolor_to_hex(color)

        # Find which color well changed
        for key, well in self._color_wells.items():
            if well == sender:
                parts = key.rsplit("_", 1)
                if len(parts) == 2:
                    state, color_type = parts
                    if state not in self._working_config["colors"]:
                        self._working_config["colors"][state] = {}

                    if color_type == "bg":
                        self._working_config["colors"][state]["background"] = hex_color
                    elif color_type == "icon":
                        self._working_config["colors"][state]["icon"] = hex_color

                    # Update preview
                    if state in self._preview_views:
                        colors = self._working_config["colors"][state]
                        self._preview_views[state].setColors_iconColor_(
                            colors.get("background", "#232329"), colors.get("icon", "#66A5FF")
                        )
                    self._update_icon_previews()
                break

    def handleBrowseForIcon(self):
        """Open file browser for custom icon."""
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(True)
        panel.setCanChooseDirectories_(False)
        panel.setAllowsMultipleSelection_(False)
        panel.setAllowedFileTypes_(["png", "jpg", "jpeg", "gif", "heic", "webp", "tiff", "bmp"])
        panel.setTitle_("Select Custom Icon")

        if panel.runModal() == 1:  # NSOKButton
            url = panel.URL()
            if url:
                path = url.path()

                # Validate the image
                is_valid, error = self._image_processor.validate_image(path)
                if not is_valid:
                    alert = NSAlert.alloc().init()
                    alert.setMessageText_("Invalid Image")
                    alert.setInformativeText_(error)
                    alert.runModal()
                    return

                # Import the image
                success, dest_path, error = self._image_processor.import_image(path)
                if success:
                    self._working_config["custom_icon"]["enabled"] = True
                    self._working_config["custom_icon"]["path"] = dest_path
                    self._icon_path_field.setStringValue_(dest_path)
                    self._update_icon_previews()
                else:
                    alert = NSAlert.alloc().init()
                    alert.setMessageText_("Import Failed")
                    alert.setInformativeText_(error)
                    alert.runModal()

    def handleClearIcon(self):
        """Clear the custom icon."""
        self._working_config["custom_icon"]["enabled"] = False
        self._working_config["custom_icon"]["path"] = ""
        self._icon_path_field.setStringValue_("No custom icon")
        self._update_icon_previews()

    def handleTintCheckboxChanged(self, sender):
        """Handle tint checkbox change."""
        apply_tint = sender.state() == NSControlStateValueOn
        self._working_config["custom_icon"]["apply_state_tint"] = apply_tint
        self._update_icon_previews()

    def handleTintSliderChanged(self, sender):
        """Handle tint slider change."""
        opacity = sender.doubleValue()
        self._working_config["custom_icon"]["tint_opacity"] = opacity
        self._update_icon_previews()

    def handleShapeModeChanged(self, sender):
        """Handle shape mode radio button change."""
        # Find which button was clicked
        selected_mode = None
        for mode_id, btn in self._shape_mode_buttons.items():
            if btn == sender:
                selected_mode = mode_id
                btn.setState_(NSControlStateValueOn)
            else:
                btn.setState_(NSControlStateValueOff)

        if selected_mode:
            self._working_config["custom_icon"]["shape_mode"] = selected_mode
            self._update_icon_previews()

    def _update_icon_previews(self):
        """Update icon preview views."""
        custom_icon = self._working_config.get("custom_icon", {})
        path = custom_icon.get("path", "")
        apply_tint = custom_icon.get("apply_state_tint", True)
        tint_opacity = custom_icon.get("tint_opacity", 0.3)
        shape_mode = custom_icon.get("shape_mode", "auto")

        # Determine if using custom shape (non-circle mode with enabled icon)
        use_custom_shape = path and custom_icon.get("enabled", False) and shape_mode != "circle"

        for state in WIDGET_STATES:
            key = f"icon_{state}"
            if key in self._preview_views:
                preview = self._preview_views[key]
                colors = self._working_config.get("colors", {}).get(state, {})
                preview.setColors_iconColor_(colors.get("background", "#232329"), colors.get("icon", "#66A5FF"))
                preview.setUseCustomShape_(use_custom_shape)

                if path and custom_icon.get("enabled", False):
                    tint_color = colors.get("icon", "") if apply_tint and state != "idle" else ""
                    icon_image = self._image_processor.get_preview(
                        path, 60, tint_color, tint_opacity if apply_tint else 0, shape_mode
                    )
                    preview.setCustomIcon_(icon_image)
                else:
                    preview.setCustomIcon_(None)

    def _confirm_reset_to_defaults(self) -> bool:
        """Ask the user to confirm resetting all appearance settings."""
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Reset Appearance")
        alert.setInformativeText_(
            "Restore all appearance settings to their factory defaults?\n\n"
            "This resets colors, icon settings, and any other appearance customizations."
        )
        alert.addButtonWithTitle_("Reset")
        alert.addButtonWithTitle_("Cancel")
        return alert.runModal() == 1000

    def handleResetToDefaults(self):
        """Restore the working appearance config to factory defaults."""
        if not self._confirm_reset_to_defaults():
            return

        self._working_config = _get_default_widget_appearance()
        self._show_step(self._current_step)

    def handleGoBack(self):
        """Go to previous step."""
        if self._current_step > 1:
            self._show_step(self._current_step - 1)

    def handleGoNext(self):
        """Go to next step."""
        if self._current_step < self._max_steps:
            self._show_step(self._current_step + 1)

    def handleCancel(self):
        """Cancel and close the editor."""
        self._window.close()
        if self._on_cancel:
            self._on_cancel()

    def handleSave(self):
        """Save changes and close the editor."""
        appearance = deepcopy(self._working_config)
        if appearance != _get_default_widget_appearance():
            appearance["theme"] = "custom"

        self._config.widget_appearance = appearance
        self._config.save()

        self._image_processor.clear_cache()

        self._window.close()
        if self._on_save:
            self._on_save(self._config.widget_appearance)


def show_appearance_editor(config, image_processor, on_save: Callable = None, on_cancel: Callable = None):
    """
    Show the appearance editor window.

    Args:
        config: Config object
        image_processor: ImageProcessor instance
        on_save: Callback when saved
        on_cancel: Callback when cancelled

    Returns:
        AppearanceEditorWindow instance
    """
    if not HAS_APPKIT:
        logger.error("AppKit not available, cannot show appearance editor")
        return None

    editor = AppearanceEditorWindow(config, image_processor, on_save, on_cancel)
    editor.show()
    return editor
