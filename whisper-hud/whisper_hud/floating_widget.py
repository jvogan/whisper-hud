"""
Floating widget for WhisperHUD.

A small, draggable window that shows recording status
and allows click-to-record as an alternative to the hotkey.
Supports customizable colors and icons.
"""

import threading
from typing import Callable, Optional
from enum import Enum

try:
    from AppKit import (
        NSWindow, NSView, NSColor, NSBezierPath,
        NSWindowStyleMaskBorderless, NSBackingStoreBuffered,
        NSFloatingWindowLevel, NSScreen,
        NSMakeRect, NSTrackingArea,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorStationary,
        NSTrackingMouseEnteredAndExited, NSTrackingActiveAlways,
        NSTrackingInVisibleRect,
        NSCursor, NSCompositingOperationSourceOver,
        NSZeroRect
    )
    from PyObjCTools import AppHelper
    from objc import super as objc_super
    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False


def _hex_to_nscolor(hex_color: str) -> 'NSColor':
    """Convert hex color string to NSColor."""
    if not HAS_APPKIT:
        return None

    try:
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 6:
            r = int(hex_color[0:2], 16) / 255.0
            g = int(hex_color[2:4], 16) / 255.0
            b = int(hex_color[4:6], 16) / 255.0
            return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 0.95)
        elif len(hex_color) == 8:
            r = int(hex_color[0:2], 16) / 255.0
            g = int(hex_color[2:4], 16) / 255.0
            b = int(hex_color[4:6], 16) / 255.0
            a = int(hex_color[6:8], 16) / 255.0
            return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)
    except Exception:
        pass

    # Fallback to default gray
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(0.14, 0.14, 0.18, 0.92)


class WidgetState(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    PROCESSING = "processing"


if HAS_APPKIT:
    class DraggableWindow(NSWindow):
        """A borderless window that can be dragged by clicking anywhere."""

        def canBecomeKeyWindow(self):
            return True

        def canBecomeMainWindow(self):
            return False

    class WidgetView(NSView):
        """Custom view for the floating widget with drag support."""

        def initWithFrame_onClick_onDragEnd_(self, frame, on_click, on_drag_end):
            self = objc_super(WidgetView, self).initWithFrame_(frame)
            if self is None:
                return None

            self._on_click = on_click
            self._on_drag_end = on_drag_end  # Callback when drag ends
            self._is_hovering = False
            self._state = WidgetState.IDLE
            self._initial_location = None
            self._mouse_down_time = None
            self._did_drag = False

            # Appearance configuration
            self._appearance_config = None
            self._custom_icon = None  # Cached custom icon image

            # Enable layer backing for smooth rendering
            self.setWantsLayer_(True)

            # Set up tracking area for hover effects
            self._setup_tracking()

            return self

        def setAppearance_(self, config):
            """Set the appearance configuration."""
            self._appearance_config = config
            self._custom_icon = None  # Clear cached icon
            self.setNeedsDisplay_(True)

        def setCustomIcon_(self, icon):
            """Set a custom icon image."""
            self._custom_icon = icon
            self.setNeedsDisplay_(True)

        def _getStateColors(self):
            """Get colors for the current state from appearance config."""
            state_name = self._state.value  # 'idle', 'recording', 'processing'

            # Default colors
            defaults = {
                "idle": {"background": "#232329", "icon": "#66A5FF", "background_hover": "#383840"},
                "recording": {"background": "#D92626", "icon": "#FFFFFF"},
                "processing": {"background": "#BF8C19", "icon": "#FFFFFF"}
            }

            if self._appearance_config and "colors" in self._appearance_config:
                colors = self._appearance_config["colors"]
                return colors.get(state_name, defaults.get(state_name, {}))

            return defaults.get(state_name, {})

        def _setup_tracking(self):
            options = (
                NSTrackingMouseEnteredAndExited
                | NSTrackingActiveAlways
                | NSTrackingInVisibleRect
            )
            tracking_area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
                self.bounds(),
                options,
                self,
                None
            )
            self.addTrackingArea_(tracking_area)

        def drawRect_(self, rect):
            # Get dimensions (default to medium if not set)
            dims = getattr(self, '_dims', (48, 48, 24, 22, 13))
            corner_radius = dims[2]
            icon_size = dims[3]
            icon_offset = dims[4]

            # Get colors from appearance config
            colors = self._getStateColors()

            # Check shape mode for custom icons
            shape_mode = "circle"
            use_custom_shape = False
            if self._appearance_config:
                custom_icon = self._appearance_config.get("custom_icon", {})
                if custom_icon.get("enabled", False):
                    shape_mode = custom_icon.get("shape_mode", "circle")
                    # Custom shape = non-circle mode with a custom icon
                    use_custom_shape = self._custom_icon and shape_mode != "circle"

            # For custom shapes, use minimal/transparent background
            if use_custom_shape:
                # Clear to transparent
                NSColor.clearColor().set()
                NSBezierPath.fillRect_(self.bounds())

                # Draw subtle state glow behind the icon when not idle
                if self._state != WidgetState.IDLE:
                    bg_hex = colors.get("background", "#D92626")
                    bg_color = _hex_to_nscolor(bg_hex)
                    # Create a soft glow with reduced opacity
                    glow_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
                        bg_color.redComponent(),
                        bg_color.greenComponent(),
                        bg_color.blueComponent(),
                        0.35  # Subtle glow
                    )
                    glow_color.setFill()
                    # Slightly larger circle behind the icon for glow effect
                    glow_inset = max(2, icon_offset - 4)
                    glow_size = icon_size + 8
                    glow_rect = NSMakeRect(glow_inset, glow_inset, glow_size, glow_size)
                    glow_path = NSBezierPath.bezierPathWithOvalInRect_(glow_rect)
                    glow_path.fill()
            else:
                # Standard rounded background
                path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    self.bounds(), corner_radius, corner_radius
                )

                # Background color based on state and hover
                if self._state == WidgetState.IDLE and self._is_hovering:
                    bg_hex = colors.get("background_hover", colors.get("background", "#383840"))
                else:
                    bg_hex = colors.get("background", "#232329")

                bg_color = _hex_to_nscolor(bg_hex)
                bg_color.setFill()
                path.fill()

            # Draw icon (custom or default circle)
            # For character packs (per_state + alpha), make icons larger to fill widget
            is_character_pack = False
            if self._appearance_config:
                custom_icon = self._appearance_config.get("custom_icon", {})
                is_character_pack = (
                    custom_icon.get("per_state", False)
                    and custom_icon.get("shape_mode") == "alpha"
                )

            if is_character_pack and self._custom_icon:
                # Character pack icons fill almost the entire widget (95%)
                widget_size = dims[0]  # Full widget width/height
                char_icon_size = int(widget_size * 0.95)
                char_offset = (widget_size - char_icon_size) // 2
                icon_rect = NSMakeRect(char_offset, char_offset, char_icon_size, char_icon_size)
            else:
                icon_rect = NSMakeRect(icon_offset, icon_offset, icon_size, icon_size)

            if self._custom_icon:
                # Draw custom icon
                self._custom_icon.drawInRect_fromRect_operation_fraction_(
                    icon_rect,
                    NSZeroRect,
                    NSCompositingOperationSourceOver,
                    1.0
                )
            else:
                # Draw default circle icon
                icon_path = NSBezierPath.bezierPathWithOvalInRect_(icon_rect)
                icon_hex = colors.get("icon", "#66A5FF")
                icon_color = _hex_to_nscolor(icon_hex)
                # Make icon fully opaque
                icon_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    icon_color.redComponent(),
                    icon_color.greenComponent(),
                    icon_color.blueComponent(),
                    1.0
                )
                icon_color.setFill()
                icon_path.fill()

        def mouseEntered_(self, event):
            self._is_hovering = True
            NSCursor.pointingHandCursor().set()
            self.setNeedsDisplay_(True)

        def mouseExited_(self, event):
            self._is_hovering = False
            NSCursor.arrowCursor().set()
            self.setNeedsDisplay_(True)

        def mouseDown_(self, event):
            import time
            # Store mouse position in screen coordinates for stable dragging
            window = self.window()
            if window:
                window_frame = window.frame()
                mouse_in_window = event.locationInWindow()
                self._initial_screen_x = window_frame.origin.x + mouse_in_window.x
                self._initial_screen_y = window_frame.origin.y + mouse_in_window.y
                self._initial_window_origin = (window_frame.origin.x, window_frame.origin.y)
            self._initial_location = event.locationInWindow()
            self._mouse_down_time = time.time()
            self._did_drag = False

        def mouseDragged_(self, event):
            if self._initial_location is None:
                return

            window = self.window()
            if window is None:
                return

            # Get current mouse position in screen coordinates
            window_frame = window.frame()
            mouse_in_window = event.locationInWindow()
            current_screen_x = window_frame.origin.x + mouse_in_window.x
            current_screen_y = window_frame.origin.y + mouse_in_window.y

            # Calculate movement from initial screen position
            dx = current_screen_x - getattr(self, '_initial_screen_x', current_screen_x)
            dy = current_screen_y - getattr(self, '_initial_screen_y', current_screen_y)

            # Only start dragging if moved more than 12 pixels
            # This prevents accidental drags when trying to click
            if abs(dx) > 12 or abs(dy) > 12:
                self._did_drag = True

            if not self._did_drag:
                return

            # Calculate new window position based on initial window origin + drag delta
            initial_origin = getattr(self, '_initial_window_origin', (0, 0))
            new_x = initial_origin[0] + dx
            new_y = initial_origin[1] + dy

            window.setFrameOrigin_((new_x, new_y))

        def mouseUp_(self, event):
            import time
            # Only trigger click if:
            # 1. We didn't drag
            # 2. Mouse was held for less than 0.5 seconds
            if self._initial_location and not self._did_drag:
                hold_duration = time.time() - (self._mouse_down_time or 0)

                # Click: no dragging occurred AND quick tap (< 0.5s)
                is_click = hold_duration < 0.5

                if is_click and self._on_click:
                    self._on_click()
            elif self._did_drag:
                # Notify that drag ended (for position persistence)
                if self._on_drag_end:
                    window = self.window()
                    if window:
                        frame = window.frame()
                        self._on_drag_end(frame.origin.x, frame.origin.y)

            # Reset all drag tracking state
            self._initial_location = None
            self._initial_screen_x = None
            self._initial_screen_y = None
            self._initial_window_origin = None
            self._mouse_down_time = None
            self._did_drag = False

        def setState_(self, state):
            self._state = state
            self.setNeedsDisplay_(True)


class FloatingWidget:
    """
    Floating widget for recording control.

    Features:
    - Draggable anywhere on screen
    - Click to start/stop recording
    - Visual state indication
    - Stays on top of other windows
    - Configurable size (small, medium, large)
    - Customizable colors and icons
    """

    # Size presets: (width, height, corner_radius, icon_size, icon_offset)
    SIZES = {
        "small": (44, 44, 22, 20, 12),
        "medium": (64, 64, 32, 30, 17),
        "large": (88, 88, 44, 42, 23),
        "xlarge": (120, 120, 60, 56, 32),
    }

    def __init__(
        self,
        on_record_start: Callable[[], None],
        on_record_stop: Callable[[], None],
        size: str = "medium",
        initial_position: Optional[dict] = None,
        on_position_changed: Optional[Callable[[float, float], None]] = None
    ):
        self._on_record_start = on_record_start
        self._on_record_stop = on_record_stop
        self._size = size if size in self.SIZES else "medium"
        self._window: Optional[NSWindow] = None
        self._view: Optional[WidgetView] = None
        self._state = WidgetState.IDLE
        self._visible = False
        self._lock = threading.Lock()
        # Load initial position from config if provided
        if initial_position and "x" in initial_position and "y" in initial_position:
            self._position = (initial_position["x"], initial_position["y"])
        else:
            self._position = None
        self._on_position_changed = on_position_changed
        self._appearance_config: Optional[dict] = None
        self._image_processor = None

    def _get_dimensions(self):
        """Get current size dimensions."""
        return self.SIZES.get(self._size, self.SIZES["medium"])

    def _ensure_window(self):
        """Create window if needed."""
        if not HAS_APPKIT or self._window is not None:
            return

        dims = self._get_dimensions()
        width, height = dims[0], dims[1]

        # Default position - bottom right of screen
        screen = NSScreen.mainScreen()
        if not screen:
            return
        screen_rect = screen.visibleFrame()

        if self._position:
            x, y = self._position
        else:
            x = screen_rect.origin.x + screen_rect.size.width - width - 20
            y = screen_rect.origin.y + 100

        # Create borderless, draggable window
        self._window = DraggableWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, width, height),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False
        )

        # Configure window
        self._window.setLevel_(NSFloatingWindowLevel)
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(NSColor.clearColor())
        # Disable shadow for cleaner look and to prevent ghosting during drag
        self._window.setHasShadow_(False)
        self._window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
        )
        self._window.setMovableByWindowBackground_(True)

        # Create custom view with size info and drag end callback
        self._view = WidgetView.alloc().initWithFrame_onClick_onDragEnd_(
            NSMakeRect(0, 0, width, height),
            self._handle_click,
            self._handle_drag_end
        )
        self._view._dims = dims  # Pass dimensions to view

        # Enable layer-backed drawing to fix transparency ghosting during drag
        self._view.setWantsLayer_(True)
        self._view.layer().setOpaque_(False)

        # Apply appearance config if set
        if self._appearance_config:
            self._view.setAppearance_(self._appearance_config)
            self._update_custom_icon()

        self._window.setContentView_(self._view)

    def _handle_click(self):
        """Handle click on widget."""
        with self._lock:
            if self._state == WidgetState.IDLE:
                self._state = WidgetState.RECORDING
                self._update_view()
                if self._on_record_start:
                    threading.Thread(target=self._on_record_start, daemon=True).start()
            elif self._state == WidgetState.RECORDING:
                self._state = WidgetState.PROCESSING
                self._update_view()
                if self._on_record_stop:
                    threading.Thread(target=self._on_record_stop, daemon=True).start()

    def _handle_drag_end(self, x: float, y: float):
        """Handle end of drag - save position."""
        self._position = (x, y)
        if self._on_position_changed:
            self._on_position_changed(x, y)

    def _update_view(self):
        """Update view state."""
        if self._view:
            def _update():
                if self._view:
                    self._view.setState_(self._state)
                    # Update custom icon for new state
                    self._update_custom_icon()
            AppHelper.callAfter(_update)

    def set_state(self, state: WidgetState):
        """Set widget state."""
        with self._lock:
            self._state = state
            self._update_view()

    def set_idle(self):
        """Set to idle state."""
        self.set_state(WidgetState.IDLE)

    def set_recording(self):
        """Set to recording state."""
        self.set_state(WidgetState.RECORDING)

    def set_processing(self):
        """Set to processing state."""
        self.set_state(WidgetState.PROCESSING)

    def show(self):
        """Show the widget."""
        if not HAS_APPKIT:
            return

        self._visible = True

        def _show():
            self._ensure_window()
            if self._window:
                self._window.orderFront_(None)

        AppHelper.callAfter(_show)

    def hide(self):
        """Hide the widget."""
        if not HAS_APPKIT:
            return

        self._visible = False

        def _hide():
            if self._window:
                self._window.orderOut_(None)

        AppHelper.callAfter(_hide)

    def toggle(self):
        """Toggle widget visibility."""
        if self._visible:
            self.hide()
        else:
            self.show()

    def is_visible(self) -> bool:
        """Check if widget is visible."""
        return self._visible

    def set_size(self, size: str):
        """Change widget size (small, medium, large)."""
        if size not in self.SIZES:
            return

        if size == self._size:
            return

        self._size = size

        if not HAS_APPKIT or not self._window:
            return

        def _resize():
            # Save current position
            if self._window:
                frame = self._window.frame()
                self._position = (frame.origin.x, frame.origin.y)

                # Close old window
                self._window.orderOut_(None)
                self._window = None
                self._view = None

            # Recreate with new size
            if self._visible:
                self._ensure_window()
                if self._window:
                    self._window.orderFront_(None)

        AppHelper.callAfter(_resize)

    def get_size(self) -> str:
        """Get current size."""
        return self._size

    def get_position(self) -> Optional[dict]:
        """Get current widget position as dict for config storage."""
        if self._position:
            return {"x": self._position[0], "y": self._position[1]}
        # If window exists, get current position
        if self._window:
            try:
                frame = self._window.frame()
                return {"x": frame.origin.x, "y": frame.origin.y}
            except Exception:
                pass
        return None

    def set_appearance(self, appearance_config: dict, image_processor=None):
        """
        Set the widget appearance configuration.

        Args:
            appearance_config: Dict with 'colors' and 'custom_icon' settings
            image_processor: Optional ImageProcessor for custom icons
        """
        self._appearance_config = appearance_config
        self._image_processor = image_processor

        if not HAS_APPKIT:
            return

        def _update_appearance():
            if self._view:
                self._view.setAppearance_(appearance_config)

                # Load custom icon if enabled
                if image_processor and appearance_config:
                    custom_icon_config = appearance_config.get("custom_icon", {})
                    if custom_icon_config.get("enabled", False):
                        dims = self._get_dimensions()
                        icon_size = dims[3]
                        state_name = self._state.value
                        icon = image_processor.get_icon_for_state(state_name, icon_size)
                        self._view.setCustomIcon_(icon)
                    else:
                        self._view.setCustomIcon_(None)
                else:
                    self._view.setCustomIcon_(None)

        AppHelper.callAfter(_update_appearance)

    def _update_custom_icon(self):
        """Update the custom icon for the current state."""
        if not HAS_APPKIT or not self._view:
            return

        if not self._image_processor or not self._appearance_config:
            return

        custom_icon_config = self._appearance_config.get("custom_icon", {})
        if not custom_icon_config.get("enabled", False):
            self._view.setCustomIcon_(None)
            return

        dims = self._get_dimensions()
        icon_size = dims[3]
        state_name = self._state.value
        icon = self._image_processor.get_icon_for_state(state_name, icon_size)
        self._view.setCustomIcon_(icon)


def create_floating_widget(
    on_record_start: Callable[[], None],
    on_record_stop: Callable[[], None],
    size: str = "medium",
    initial_position: Optional[dict] = None,
    on_position_changed: Optional[Callable[[float, float], None]] = None
) -> Optional[FloatingWidget]:
    """Create a floating widget if AppKit is available."""
    if HAS_APPKIT:
        return FloatingWidget(
            on_record_start,
            on_record_stop,
            size=size,
            initial_position=initial_position,
            on_position_changed=on_position_changed
        )
    return None
