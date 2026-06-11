"""
Floating widget for WhisperHUD.

A small, draggable window that shows recording status
and allows click-to-record as an alternative to the hotkey.
Supports customizable colors and icons.
"""

from __future__ import annotations

import math
import threading
from enum import Enum
from typing import Callable, Optional

from .logging_config import get_logger

logger = get_logger("floating_widget")

try:
    import AppKit
    from PyObjCTools import AppHelper
    from objc import super as objc_super

    NSWindow = AppKit.NSWindow
    NSView = AppKit.NSView
    NSColor = AppKit.NSColor
    NSBezierPath = AppKit.NSBezierPath
    NSWindowStyleMaskBorderless = AppKit.NSWindowStyleMaskBorderless
    NSBackingStoreBuffered = AppKit.NSBackingStoreBuffered
    NSFloatingWindowLevel = AppKit.NSFloatingWindowLevel
    NSScreen = AppKit.NSScreen
    NSMakeRect = AppKit.NSMakeRect
    NSTrackingArea = AppKit.NSTrackingArea
    NSWindowCollectionBehaviorCanJoinAllSpaces = AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
    NSWindowCollectionBehaviorStationary = AppKit.NSWindowCollectionBehaviorStationary
    NSTrackingMouseEnteredAndExited = AppKit.NSTrackingMouseEnteredAndExited
    NSTrackingActiveAlways = AppKit.NSTrackingActiveAlways
    NSTrackingInVisibleRect = AppKit.NSTrackingInVisibleRect
    NSCursor = AppKit.NSCursor
    NSCompositingOperationSourceOver = AppKit.NSCompositingOperationSourceOver
    NSZeroRect = AppKit.NSZeroRect
    NSGraphicsContext = getattr(AppKit, "NSGraphicsContext", None)
    NSImageInterpolationNone = getattr(AppKit, "NSImageInterpolationNone", 1)
    NSSound = getattr(AppKit, "NSSound", None)
    NSLineCapStyleRound = getattr(AppKit, "NSLineCapStyleRound", 1)
    NSLineJoinStyleRound = getattr(AppKit, "NSLineJoinStyleRound", 1)
    NSMenu = AppKit.NSMenu
    NSMenuItem = AppKit.NSMenuItem
    NSAccessibilityButtonRole = getattr(AppKit, "NSAccessibilityButtonRole", "AXButton")
    NSAccessibilityImageRole = getattr(AppKit, "NSAccessibilityImageRole", "AXImage")
    NSAccessibilityCreatedNotification = getattr(AppKit, "NSAccessibilityCreatedNotification", "AXCreated")
    NSAccessibilityFocusedUIElementChangedNotification = getattr(
        AppKit,
        "NSAccessibilityFocusedUIElementChangedNotification",
        "AXFocusedUIElementChanged",
    )
    NSAccessibilityValueChangedNotification = getattr(
        AppKit,
        "NSAccessibilityValueChangedNotification",
        "AXValueChanged",
    )
    NSAccessibilityPostNotification = getattr(AppKit, "NSAccessibilityPostNotification", None)
    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False


def _hex_to_nscolor(hex_color: str) -> "NSColor":
    """Convert hex color string to NSColor."""
    if not HAS_APPKIT:
        return None

    try:
        hex_color = hex_color.lstrip("#")
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
    SUCCESS = "success"
    ERROR = "error"


DEFAULT_WIDGET_RIGHT_MARGIN = 20
DEFAULT_WIDGET_BOTTOM_MARGIN = 100

# How long the transient success/error states stay visible before reverting to idle.
SUCCESS_REVERT_SECONDS = 1.2
ERROR_REVERT_SECONDS = 2.0


if HAS_APPKIT:

    class DraggableWindow(NSWindow):
        """A borderless window that can be dragged by clicking anywhere."""

        def canBecomeKeyWindow(self):
            return True

        def canBecomeMainWindow(self):
            return False

        def canBecomeVisibleWithoutLogin(self):
            return True

    class WidgetView(NSView):
        """Custom view for the floating widget with drag support."""

        def initWithFrame_onClick_onDragEnd_onResetPosition_(self, frame, on_click, on_drag_end, on_reset_position):
            self = objc_super(WidgetView, self).initWithFrame_(frame)
            if self is None:
                return None

            self._on_click = on_click
            self._on_drag_end = on_drag_end  # Callback when drag ends
            self._on_reset_position = on_reset_position
            self._is_hovering = False
            self._is_pressed = False
            self._state = WidgetState.IDLE
            self._initial_location = None
            self._mouse_down_time = None
            self._did_drag = False
            self._accessibility_role = NSAccessibilityButtonRole
            self._accessibility_label = "WhisperHUD - Idle"

            # Appearance configuration
            self._appearance_config = None
            self._custom_icon = None  # Cached custom icon image (single-frame)
            self._animation_phase = 0.0
            self._audio_level = 0.0  # Smoothed live mic level (0..1) while recording
            # Multi-frame sprite animation: when the active pack defines frames
            # for the current state these are drawn instead of _custom_icon.
            self._frames = []
            self._frame_index = 0

            # Enable layer backing for smooth rendering
            self.setWantsLayer_(True)

            # Set up tracking area for hover effects
            self._setup_tracking()

            return self

        def menuForEvent_(self, event):
            menu = NSMenu.alloc().initWithTitle_("Floating Widget")
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Reset Position",
                "resetPosition:",
                "",
            )
            item.setTarget_(self)
            menu.addItem_(item)
            return menu

        def resetPosition_(self, sender):
            if self._on_reset_position:
                self._on_reset_position()

        def setAppearance_(self, config):
            """Set the appearance configuration."""
            self._appearance_config = config
            self._custom_icon = None  # Clear cached icon
            self.setNeedsDisplay_(True)

        def setCustomIcon_(self, icon):
            """Set a custom icon image."""
            self._custom_icon = icon
            self.setNeedsDisplay_(True)

        def setFrames_(self, frames):
            """Set the multi-frame animation sequence for the current state."""
            self._frames = list(frames) if frames else []
            self._frame_index = 0
            self.setNeedsDisplay_(True)

        def setFrameIndex_(self, index):
            """Select which animation frame to draw."""
            self._frame_index = index
            self.setNeedsDisplay_(True)

        def _current_icon_image(self):
            """Return the image to blit: active animation frame or static icon."""
            if self._frames:
                if 0 <= self._frame_index < len(self._frames):
                    return self._frames[self._frame_index]
                return self._frames[0]
            return self._custom_icon

        def setAnimationPhase_(self, phase):
            """Update the animation phase used when drawing active states."""
            self._animation_phase = phase
            self.setNeedsDisplay_(True)

        def setAudioLevel_(self, level):
            """Store the live mic level; the animation tick redraws with it."""
            self._audio_level = level

        def _getStateColors(self):
            """Get colors for the current state from appearance config."""
            state_name = self._state.value  # 'idle', 'recording', 'processing'

            # Default colors
            defaults = {
                "idle": {"background": "#232329", "icon": "#66A5FF", "background_hover": "#383840"},
                "recording": {"background": "#D92626", "icon": "#FFFFFF"},
                "processing": {"background": "#BF8C19", "icon": "#FFFFFF"},
                "success": {"background": "#2E9E5B", "icon": "#FFFFFF"},
                "error": {"background": "#D92626", "icon": "#FFFFFF"},
            }

            if self._appearance_config and "colors" in self._appearance_config:
                colors = self._appearance_config["colors"]
                return colors.get(state_name, defaults.get(state_name, {}))

            return defaults.get(state_name, {})

        def _setup_tracking(self):
            options = NSTrackingMouseEnteredAndExited | NSTrackingActiveAlways | NSTrackingInVisibleRect
            tracking_area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
                self.bounds(), options, self, None
            )
            self.addTrackingArea_(tracking_area)

        def isAccessibilityElement(self):
            return True

        def accessibilityRole(self):
            return self._accessibility_role or NSAccessibilityImageRole

        def accessibilityLabel(self):
            return self._accessibility_label

        def accessibilityPerformPress(self):
            if self._on_click:
                self._on_click()
                return True
            return False

        def setAccessibilityLabelText_(self, label):
            self._accessibility_label = label
            setter = getattr(self, "setAccessibilityLabel_", None)
            if setter:
                setter(label)

        def drawRect_(self, rect):
            # Get dimensions (default to medium if not set)
            dims = getattr(self, "_dims", (48, 48, 24, 22, 13))
            corner_radius = dims[2]
            icon_size = dims[3]
            icon_offset = dims[4]
            animation_phase = getattr(self, "_animation_phase", 0.0)

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
                    glow_alpha = 0.35
                    if self._state == WidgetState.RECORDING:
                        glow_alpha = 0.24 + (0.18 * (0.5 + 0.5 * math.sin(animation_phase * math.tau)))
                    # Create a soft glow with reduced opacity
                    glow_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
                        bg_color.redComponent(), bg_color.greenComponent(), bg_color.blueComponent(), glow_alpha
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
            nearest_interpolation = False
            if self._appearance_config:
                custom_icon = self._appearance_config.get("custom_icon", {})
                is_character_pack = custom_icon.get("per_state", False) and custom_icon.get("shape_mode") == "alpha"
                nearest_interpolation = custom_icon.get("interpolation") == "nearest"

            icon_image = self._current_icon_image()

            if is_character_pack and icon_image:
                # Character pack icons fill almost the entire widget (95%)
                widget_size = dims[0]  # Full widget width/height
                char_icon_size = int(widget_size * 0.95)
                char_offset = (widget_size - char_icon_size) // 2
                icon_rect = NSMakeRect(char_offset, char_offset, char_icon_size, char_icon_size)
            else:
                icon_rect = NSMakeRect(icon_offset, icon_offset, icon_size, icon_size)

            # Subtle hover / pressed micro-interaction on the icon rect.
            interaction_scale = self._interaction_scale()
            if interaction_scale != 1.0:
                icon_rect = self._scaled_rect(icon_rect, interaction_scale)

            if icon_image:
                # Pixel-art packs request point sampling so the second resample
                # (this blit) does not blur crisp art the way the cached image's
                # first resample already avoided.
                if nearest_interpolation and NSGraphicsContext is not None:
                    gc = NSGraphicsContext.currentContext()
                    if gc is not None:
                        gc.setImageInterpolation_(NSImageInterpolationNone)

                # Draw custom icon (single frame or active animation frame)
                icon_image.drawInRect_fromRect_operation_fraction_(
                    icon_rect, NSZeroRect, NSCompositingOperationSourceOver, 1.0
                )
            else:
                # Draw default circle icon
                if self._state == WidgetState.PROCESSING:
                    self._draw_processing_spinner(icon_rect, colors, animation_phase)
                    return

                if self._state == WidgetState.SUCCESS:
                    self._draw_success_check(icon_rect, colors)
                    return

                if self._state == WidgetState.ERROR:
                    self._draw_error_mark(icon_rect, colors)
                    return

                if self._state == WidgetState.RECORDING:
                    icon_rect = self._scaled_rect(
                        icon_rect, 0.92 + (0.16 * (0.5 + 0.5 * math.sin(animation_phase * math.tau)))
                    )

                icon_path = NSBezierPath.bezierPathWithOvalInRect_(icon_rect)
                icon_hex = colors.get("icon", "#66A5FF")
                icon_color = _hex_to_nscolor(icon_hex)
                # Make icon fully opaque
                icon_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    icon_color.redComponent(), icon_color.greenComponent(), icon_color.blueComponent(), 1.0
                )
                icon_color.setFill()
                icon_path.fill()

                if self._state == WidgetState.RECORDING:
                    self._draw_recording_ring(icon_rect, icon_color, animation_phase)

        # Icon micro-interaction scales. Pressed takes priority over hover.
        HOVER_SCALE = 1.06
        PRESSED_SCALE = 0.94

        def _interaction_scale(self):
            """Scale factor for hover/press feedback on the icon (1.0 = none)."""
            if self._is_pressed:
                return self.PRESSED_SCALE
            if self._is_hovering:
                return self.HOVER_SCALE
            return 1.0

        def _scaled_rect(self, rect, scale):
            center_x = rect.origin.x + (rect.size.width / 2.0)
            center_y = rect.origin.y + (rect.size.height / 2.0)
            width = rect.size.width * scale
            height = rect.size.height * scale
            return NSMakeRect(center_x - (width / 2.0), center_y - (height / 2.0), width, height)

        def _draw_recording_ring(self, icon_rect, icon_color, animation_phase):
            pulse = 0.5 + 0.5 * math.sin(animation_phase * math.tau)
            # The live mic level rides on top of the steady pulse, so the
            # ring visibly swells and brightens while the user speaks.
            boost = min(1.0, max(0.0, self._audio_level) * 1.6)
            ring_rect = self._scaled_rect(icon_rect, 1.35 + (0.12 * pulse) + (0.28 * boost))
            ring_path = NSBezierPath.bezierPathWithOvalInRect_(ring_rect)
            ring_path.setLineWidth_(2.6 + (1.2 * boost))
            ring_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
                icon_color.redComponent(),
                icon_color.greenComponent(),
                icon_color.blueComponent(),
                min(0.65, 0.18 + (0.18 * pulse) + (0.30 * boost)),
            )
            ring_color.setStroke()
            ring_path.stroke()

        def _draw_processing_spinner(self, icon_rect, colors, animation_phase):
            icon_hex = colors.get("icon", "#FFFFFF")
            icon_color = _hex_to_nscolor(icon_hex)
            spinner_rect = self._scaled_rect(icon_rect, 1.08)
            start_angle = 90 - (animation_phase * 360.0)
            end_angle = start_angle - 250.0

            spinner_path = NSBezierPath.bezierPath()
            spinner_path.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
                (
                    spinner_rect.origin.x + (spinner_rect.size.width / 2.0),
                    spinner_rect.origin.y + (spinner_rect.size.height / 2.0),
                ),
                spinner_rect.size.width / 2.0,
                start_angle,
                end_angle,
                True,
            )
            spinner_path.setLineWidth_(3.0)
            spinner_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
                icon_color.redComponent(), icon_color.greenComponent(), icon_color.blueComponent(), 1.0
            )
            spinner_color.setStroke()
            spinner_path.stroke()

            center_dot = self._scaled_rect(icon_rect, 0.34)
            dot_path = NSBezierPath.bezierPathWithOvalInRect_(center_dot)
            spinner_color.setFill()
            dot_path.fill()

        def _opaque_icon_color(self, colors):
            """Return the state icon color forced to full opacity."""
            icon_hex = colors.get("icon", "#FFFFFF")
            icon_color = _hex_to_nscolor(icon_hex)
            return NSColor.colorWithCalibratedRed_green_blue_alpha_(
                icon_color.redComponent(), icon_color.greenComponent(), icon_color.blueComponent(), 1.0
            )

        def _draw_success_check(self, icon_rect, colors):
            """Draw a simple checkmark for the success state."""
            stroke_color = self._opaque_icon_color(colors)
            origin_x = icon_rect.origin.x
            origin_y = icon_rect.origin.y
            width = icon_rect.size.width
            height = icon_rect.size.height
            line_width = max(2.0, width * 0.14)

            # Three-point checkmark within the icon rect (origin is bottom-left).
            start = (origin_x + width * 0.22, origin_y + height * 0.52)
            elbow = (origin_x + width * 0.42, origin_y + height * 0.30)
            end = (origin_x + width * 0.78, origin_y + height * 0.72)

            check_path = NSBezierPath.bezierPath()
            check_path.moveToPoint_(start)
            check_path.lineToPoint_(elbow)
            check_path.lineToPoint_(end)
            check_path.setLineWidth_(line_width)
            check_path.setLineCapStyle_(NSLineCapStyleRound)
            check_path.setLineJoinStyle_(NSLineJoinStyleRound)
            stroke_color.setStroke()
            check_path.stroke()

        def _draw_error_mark(self, icon_rect, colors):
            """Draw a simple exclamation mark for the error state."""
            stroke_color = self._opaque_icon_color(colors)
            origin_x = icon_rect.origin.x
            origin_y = icon_rect.origin.y
            width = icon_rect.size.width
            height = icon_rect.size.height
            line_width = max(2.0, width * 0.16)
            center_x = origin_x + width * 0.5

            # Vertical stroke (origin is bottom-left, so the stem sits above the dot).
            stem_top = (center_x, origin_y + height * 0.82)
            stem_bottom = (center_x, origin_y + height * 0.38)

            stem_path = NSBezierPath.bezierPath()
            stem_path.moveToPoint_(stem_top)
            stem_path.lineToPoint_(stem_bottom)
            stem_path.setLineWidth_(line_width)
            stem_path.setLineCapStyle_(NSLineCapStyleRound)
            stroke_color.setStroke()
            stem_path.stroke()

            # Dot beneath the stem.
            dot_size = line_width
            dot_rect = NSMakeRect(
                center_x - (dot_size / 2.0),
                origin_y + height * 0.18 - (dot_size / 2.0),
                dot_size,
                dot_size,
            )
            dot_path = NSBezierPath.bezierPathWithOvalInRect_(dot_rect)
            stroke_color.setFill()
            dot_path.fill()

        def mouseEntered_(self, event):
            self._is_hovering = True
            NSCursor.pointingHandCursor().set()
            self.setNeedsDisplay_(True)

        def mouseExited_(self, event):
            self._is_hovering = False
            self._is_pressed = False
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
            # Pressed micro-interaction feedback.
            self._is_pressed = True
            self.setNeedsDisplay_(True)

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
            dx = current_screen_x - getattr(self, "_initial_screen_x", current_screen_x)
            dy = current_screen_y - getattr(self, "_initial_screen_y", current_screen_y)

            # Only start dragging if moved more than 12 pixels
            # This prevents accidental drags when trying to click
            if abs(dx) > 12 or abs(dy) > 12:
                self._did_drag = True

            if not self._did_drag:
                return

            # Calculate new window position based on initial window origin + drag delta
            initial_origin = getattr(self, "_initial_window_origin", (0, 0))
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
            # Release the pressed micro-interaction.
            self._is_pressed = False
            self.setNeedsDisplay_(True)

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
        on_position_changed: Optional[Callable[[float, float], None]] = None,
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
        self._animation_phase = 0.0
        self._animation_timer: Optional[threading.Timer] = None
        self._animation_generation = 0
        self._animation_interval = 1.0 / 15.0
        # Smoothed live mic level (0..1); recording visuals react to it.
        self._audio_level = 0.0
        # Multi-frame sprite animation state (manifest v2). When the active pack
        # defines frames for the current state, these drive the same timer loop:
        # the procedural _animation_phase is replaced by a frame index walk.
        self._state_frames: list = []
        self._state_fps = 0.0
        self._frame_index = 0
        self._state_loops = True  # transient states (success/error) play once
        self._last_sound_state: Optional[WidgetState] = None
        # Transient success/error states auto-revert to idle via this timer.
        # Structured like the animation timer so a future one-shot animation
        # can hook the same window/generation guard.
        self._revert_timer: Optional[threading.Timer] = None
        self._revert_generation = 0
        self._tooltip_provider = "Unknown"
        self._tooltip_hotkey = ""
        self._tooltip_mode = "push_to_talk"
        self._accessibility_label = self._build_accessibility_label(self._state)

    def _get_dimensions(self):
        """Get current size dimensions."""
        return self.SIZES.get(self._size, self.SIZES["medium"])

    def _get_default_position(self) -> Optional[tuple[float, float]]:
        """Return the default position on the primary monitor."""
        if not HAS_APPKIT:
            return None

        screen = NSScreen.mainScreen()
        if not screen:
            return None

        screen_rect = screen.visibleFrame()
        width, _height = self._get_dimensions()[0:2]
        x = screen_rect.origin.x + screen_rect.size.width - width - DEFAULT_WIDGET_RIGHT_MARGIN
        y = screen_rect.origin.y + DEFAULT_WIDGET_BOTTOM_MARGIN
        return (x, y)

    def _ensure_window(self):
        """Create window if needed."""
        if not HAS_APPKIT or self._window is not None:
            return

        dims = self._get_dimensions()
        width, height = dims[0], dims[1]

        default_position = self._get_default_position()
        if not default_position:
            return

        if self._position:
            x, y = self._position
        else:
            x, y = default_position

        # Create borderless, draggable window
        self._window = DraggableWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, width, height), NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
        )

        # Configure window
        self._window.setLevel_(NSFloatingWindowLevel)
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(NSColor.clearColor())
        # Disable shadow for cleaner look and to prevent ghosting during drag
        self._window.setHasShadow_(False)
        self._window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary
        )
        self._window.setMovableByWindowBackground_(True)

        # Create custom view with size info and drag end callback
        self._view = WidgetView.alloc().initWithFrame_onClick_onDragEnd_onResetPosition_(
            NSMakeRect(0, 0, width, height),
            self._handle_click,
            self._handle_drag_end,
            self.reset_position,
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
        self._update_tooltip()
        self._apply_accessibility_metadata()
        self._update_animation_phase()

    def _handle_click(self):
        """Handle click on widget.

        Drive the transition through the public ``set_recording`` /
        ``set_processing`` API so the animation timer, per-state sound, and
        accessibility notification fire on the click path too. The lock is
        released before calling those methods (they acquire it themselves), and
        ``_state`` is NOT pre-mutated so the later app-callback
        ``set_recording()`` / ``set_processing()`` simply dedups to a no-op
        instead of swallowing the animation start.
        """
        with self._lock:
            current = self._state
        if current == WidgetState.IDLE:
            self.set_recording()
            if self._on_record_start:
                threading.Thread(target=self._on_record_start, daemon=True).start()
        elif current == WidgetState.RECORDING:
            self.set_processing()
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
                    self._apply_accessibility_metadata()
                    # Update custom icon for new state
                    self._update_custom_icon()

            AppHelper.callAfter(_update)

    def _build_accessibility_label(self, state: WidgetState) -> str:
        state_labels = {
            WidgetState.IDLE: "Idle",
            WidgetState.RECORDING: "Recording",
            WidgetState.PROCESSING: "Processing",
            WidgetState.SUCCESS: "Success",
            WidgetState.ERROR: "Error",
        }
        return f"WhisperHUD - {state_labels.get(state, 'Idle')}"

    def _apply_accessibility_metadata(self):
        if not HAS_APPKIT:
            return

        label = self._build_accessibility_label(self._state)
        self._accessibility_label = label

        if self._view:
            self._view.setAccessibilityLabelText_(label)
            role_setter = getattr(self._view, "setAccessibilityRole_", None)
            if role_setter:
                role_setter(NSAccessibilityButtonRole)

        if self._window:
            window_role_setter = getattr(self._window, "setAccessibilityRole_", None)
            if window_role_setter:
                window_role_setter(NSAccessibilityButtonRole)
            window_label_setter = getattr(self._window, "setAccessibilityLabel_", None)
            if window_label_setter:
                window_label_setter(label)

    def _post_accessibility_notification(self):
        if not HAS_APPKIT or NSAccessibilityPostNotification is None:
            return

        element = self._view or self._window
        if not element:
            return

        NSAccessibilityPostNotification(element, NSAccessibilityValueChangedNotification)
        NSAccessibilityPostNotification(element, NSAccessibilityFocusedUIElementChangedNotification)

    def _update_animation_phase(self):
        """Push the current animation phase to the view."""
        if not HAS_APPKIT or not self._view:
            return

        def _update():
            if self._view:
                self._view.setAnimationPhase_(self._animation_phase)

        AppHelper.callAfter(_update)

    def _cancel_animation_timer_locked(self):
        if self._animation_timer:
            self._animation_timer.cancel()
            self._animation_timer = None

    def _cancel_revert_timer_locked(self):
        """Cancel any pending auto-revert and invalidate in-flight callbacks."""
        self._revert_generation += 1
        if self._revert_timer:
            self._revert_timer.cancel()
            self._revert_timer = None

    def _schedule_revert_locked(self, delay: float):
        """Schedule a one-shot revert to idle after ``delay`` seconds."""
        self._cancel_revert_timer_locked()
        generation = self._revert_generation
        timer = threading.Timer(delay, self._revert_to_idle, args=(generation,))
        timer.daemon = True
        self._revert_timer = timer
        timer.start()

    def _revert_to_idle(self, generation: int):
        """Timer callback: return to idle unless a newer state change intervened."""
        with self._lock:
            if generation != self._revert_generation:
                return
            self._revert_timer = None
        # Reuse the normal idle transition (cancels timers, updates view/a11y).
        self.set_idle()

    # States whose frame animations loop forever vs. play exactly once.
    _LOOPING_STATES = {WidgetState.IDLE, WidgetState.RECORDING, WidgetState.PROCESSING}

    def _load_state_frames_locked(self):
        """Load the active pack's frame sequence for the current state.

        Populates ``_state_frames`` / ``_state_fps`` / ``_state_loops`` and
        pushes the frame list to the view. Falls back to an empty list (static
        icon / procedural animation) when the pack defines no frames.
        """
        self._state_frames = []
        self._state_fps = 0.0
        self._frame_index = 0
        # Transient states play once; everything else loops.
        self._state_loops = self._state in self._LOOPING_STATES

        if not self._image_processor or not self._appearance_config:
            self._push_frames_to_view([])
            return

        custom_icon = self._appearance_config.get("custom_icon", {})
        if not custom_icon.get("enabled", False):
            self._push_frames_to_view([])
            return

        dims = self._get_dimensions()
        icon_size = dims[3]
        state_name = self._state.value
        try:
            frames = self._image_processor.get_frames_for_state(state_name, icon_size)
        except Exception as exc:  # best-effort; never break the widget on render
            logger.debug(f"Failed to load animation frames for {state_name}: {exc}")
            frames = []

        if frames:
            self._state_frames = list(frames)
            animations = custom_icon.get("animations", {})
            state_anim = animations.get(state_name, {}) if isinstance(animations, dict) else {}
            self._state_fps = state_anim.get("fps", 0.0) if isinstance(state_anim, dict) else 0.0

        self._push_frames_to_view(self._state_frames)

    def _push_frames_to_view(self, frames):
        """Send the frame list to the view on the main thread."""
        if not HAS_APPKIT or not self._view:
            return

        view = self._view
        frames_copy = list(frames)

        def _apply():
            if self._view is view:
                self._view.setFrames_(frames_copy)

        AppHelper.callAfter(_apply)

    def _update_frame_index(self):
        """Push the current frame index to the view on the main thread."""
        if not HAS_APPKIT or not self._view:
            return

        view = self._view
        index = self._frame_index

        def _apply():
            if self._view is view:
                self._view.setFrameIndex_(index)

        AppHelper.callAfter(_apply)

    def _has_frame_animation_locked(self) -> bool:
        return len(self._state_frames) > 1

    def _current_animation_interval_locked(self) -> float:
        """Timer interval for the current state's animation.

        Frame sequences honour the pack's fps; procedural states keep the
        default 1/15s cadence. While recording, the live mic level speeds
        up frame playback (up to 2x) so pack characters react to the voice.
        """
        if self._has_frame_animation_locked() and self._state_fps > 0:
            interval = 1.0 / self._state_fps
            if self._state == WidgetState.RECORDING and self._audio_level > 0.0:
                interval = max(interval / (1.0 + min(1.0, self._audio_level)), 1.0 / 30.0)
            return interval
        return self._animation_interval

    def _state_uses_animation(self) -> bool:
        # Any state with a multi-frame sequence animates (including IDLE, the
        # idle-breathing hero case); procedural recording/processing also do.
        if self._has_frame_animation_locked():
            return True
        return self._state in {WidgetState.RECORDING, WidgetState.PROCESSING}

    def _restart_animation_for_state_locked(self):
        self._animation_generation += 1
        self._cancel_animation_timer_locked()
        # (Re)load frames for the new state before deciding whether to animate.
        self._load_state_frames_locked()

        if not self._state_uses_animation() or not self._visible:
            self._animation_phase = 0.0
            self._update_animation_phase()
            return

        self._animation_phase = 0.0
        self._update_animation_phase()
        if self._has_frame_animation_locked():
            self._update_frame_index()
        self._schedule_animation_tick_locked()

    def _schedule_animation_tick_locked(self):
        timer = threading.Timer(
            self._current_animation_interval_locked(),
            self._animation_tick,
            args=(self._animation_generation,),
        )
        timer.daemon = True
        self._animation_timer = timer
        timer.start()

    def _animation_tick(self, generation: int):
        advance_phase = False
        advance_frame = False
        with self._lock:
            if generation != self._animation_generation:
                return
            if not self._state_uses_animation() or not self._visible:
                self._animation_timer = None
                return

            if self._has_frame_animation_locked():
                next_index = self._frame_index + 1
                if next_index >= len(self._state_frames):
                    if self._state_loops:
                        self._frame_index = 0
                    else:
                        # One-shot transition: hold the final frame and stop;
                        # the revert timer returns the widget to idle.
                        self._frame_index = len(self._state_frames) - 1
                        self._animation_timer = None
                        self._update_frame_index()
                        return
                else:
                    self._frame_index = next_index
                advance_frame = True
            else:
                self._animation_phase = (self._animation_phase + 0.12) % 1.0
                advance_phase = True

            self._animation_timer = None
            self._schedule_animation_tick_locked()

        if advance_frame:
            self._update_frame_index()
        if advance_phase:
            self._update_animation_phase()

    def _build_tooltip_text(self) -> str:
        provider = self._tooltip_provider or "Unknown"
        hotkey = self._tooltip_hotkey or "Not set"
        action = "Hold" if self._tooltip_mode == "push_to_talk" else "Press"
        return f"Provider: {provider}\nHotkey: {action} {hotkey}"

    def _update_tooltip(self):
        if not HAS_APPKIT or not self._view:
            return

        tooltip = self._build_tooltip_text()

        def _apply_tooltip():
            if self._view:
                self._view.setToolTip_(tooltip)

        AppHelper.callAfter(_apply_tooltip)

    def set_tooltip_context(self, provider_name: str, hotkey_display: str, hotkey_mode: str):
        """Update tooltip metadata shown when the widget is hovered."""
        self._tooltip_provider = provider_name or "Unknown"
        self._tooltip_hotkey = hotkey_display or "Not set"
        self._tooltip_mode = hotkey_mode or "push_to_talk"
        self._update_tooltip()

    def set_state(self, state: WidgetState):
        """Set widget state."""
        with self._lock:
            if state == self._state:
                return
            # Any explicit state change cancels a pending success/error revert.
            self._cancel_revert_timer_locked()
            self._state = state
            self._accessibility_label = self._build_accessibility_label(state)
            if state != WidgetState.RECORDING:
                self._audio_level = 0.0
                self._push_audio_level_to_view(0.0)
            self._restart_animation_for_state_locked()
            self._update_view()
        self._post_accessibility_notification()
        self._trigger_state_sound(state)

    def set_audio_level(self, level: float) -> None:
        """Feed the live mic level (0..1); recording visuals breathe with it.

        Called from the recording level-monitor thread at ~20Hz. The value is
        lightly smoothed so the ring swells rather than flickers.
        """
        try:
            level = max(0.0, min(1.0, float(level)))
        except (TypeError, ValueError):
            return
        with self._lock:
            if self._state != WidgetState.RECORDING:
                return
            self._audio_level = (0.55 * self._audio_level) + (0.45 * level)
            smoothed = self._audio_level
        self._push_audio_level_to_view(smoothed)

    def _push_audio_level_to_view(self, level: float) -> None:
        """Forward the level to the view on the main thread (no redraw)."""
        if not HAS_APPKIT or not self._view:
            return

        view = self._view

        def _apply():
            if self._view is view:
                view.setAudioLevel_(level)

        AppHelper.callAfter(_apply)

    def _set_transient_state(self, state: WidgetState, revert_after: float):
        """Enter a transient state that auto-reverts to idle after a delay."""
        with self._lock:
            changed = state != self._state
            if changed:
                self._state = state
                self._accessibility_label = self._build_accessibility_label(state)
                self._restart_animation_for_state_locked()
                self._update_view()
            # Schedule the revert even if the state was already set, so repeated
            # calls keep the widget visible for the full window.
            self._schedule_revert_locked(revert_after)
        if changed:
            self._post_accessibility_notification()
            self._trigger_state_sound(state)

    def _state_sound_path(self, state: WidgetState) -> Optional[str]:
        """Resolve the active pack's sound file for a state, if any."""
        if not self._appearance_config:
            return None
        custom_icon = self._appearance_config.get("custom_icon", {})
        if not custom_icon.get("enabled", False):
            return None
        sounds = custom_icon.get("sounds", {})
        if not isinstance(sounds, dict):
            return None
        return sounds.get(state.value) or None

    def _sound_enabled(self) -> bool:
        """Whether sounds may play, gated read-only on the completion-sound toggle.

        The widget never owns config; it reaches the existing ``play_sound``
        flag through the image processor it was wired with (read-only).
        """
        processor = self._image_processor
        config = getattr(processor, "_config", None) if processor is not None else None
        if config is None:
            return False
        return bool(getattr(config, "play_sound", False))

    def _trigger_state_sound(self, state: WidgetState):
        """Best-effort: play the pack's per-state sound on entering ``state``.

        Never blocks the UI thread and never raises; failures are debug-logged.
        Gated on the existing completion-sound preference.
        """
        sound_path = self._state_sound_path(state)
        if not sound_path:
            return
        if not self._sound_enabled():
            return
        threading.Thread(target=self._play_sound_file, args=(sound_path,), daemon=True).start()

    def _play_sound_file(self, sound_path: str):
        """Play a sound file via NSSound, falling back to ``afplay``.

        ``NSSound.play()`` is asynchronous and the Python wrapper is the sole
        owner of the NSSound, so GC could dealloc it mid-playback and truncate
        the clip. This method runs on a dedicated daemon thread, so we keep the
        ``sound`` reference alive on this stack frame by sleeping for the clip's
        duration (bounded to avoid hung threads on bad durations).
        """
        try:
            if NSSound is not None:
                sound = NSSound.alloc().initWithContentsOfFile_byReference_(sound_path, True)
                if sound is not None:
                    sound.play()
                    import time

                    try:
                        dur = float(sound.duration())
                    except Exception:
                        dur = 0.0
                    # Hold the reference for the playback window; the bound keeps
                    # the thread from lingering on absurd or invalid durations.
                    time.sleep(min(dur + 0.25, 10.0))
                    return
            import subprocess

            subprocess.Popen(["afplay", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            logger.debug(f"Failed to play state sound {sound_path}: {exc}")

    def set_idle(self):
        """Set to idle state."""
        self.set_state(WidgetState.IDLE)

    def set_recording(self):
        """Set to recording state."""
        self.set_state(WidgetState.RECORDING)

    def set_processing(self):
        """Set to processing state."""
        self.set_state(WidgetState.PROCESSING)

    def set_success(self):
        """Flash the success state, then auto-revert to idle."""
        self._set_transient_state(WidgetState.SUCCESS, SUCCESS_REVERT_SECONDS)

    def set_error(self):
        """Flash the error state, then auto-revert to idle."""
        self._set_transient_state(WidgetState.ERROR, ERROR_REVERT_SECONDS)

    def show(self):
        """Show the widget."""
        if not HAS_APPKIT:
            return

        with self._lock:
            self._visible = True

        def _show():
            self._ensure_window()
            if self._window:
                self._window.orderFront_(None)
                if NSAccessibilityPostNotification is not None:
                    NSAccessibilityPostNotification(self._view or self._window, NSAccessibilityCreatedNotification)

        AppHelper.callAfter(_show)
        with self._lock:
            self._restart_animation_for_state_locked()

    def hide(self):
        """Hide the widget."""
        if not HAS_APPKIT:
            return

        with self._lock:
            self._visible = False
            self._cancel_revert_timer_locked()
            self._restart_animation_for_state_locked()

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

    def reset_position(self):
        """Reset the widget to its default position on the primary monitor."""
        default_position = self._get_default_position()
        if not default_position:
            return

        with self._lock:
            self._position = default_position

        def _reset():
            if self._window:
                self._window.setFrameOrigin_(default_position)

        if HAS_APPKIT:
            AppHelper.callAfter(_reset)

        if self._on_position_changed:
            self._on_position_changed(*default_position)

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

            # Reload any frame sequence for the new pack and (re)start animation
            # so an idle breathing loop begins as soon as the pack is applied.
            with self._lock:
                self._restart_animation_for_state_locked()

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
    on_position_changed: Optional[Callable[[float, float], None]] = None,
) -> Optional[FloatingWidget]:
    """Create a floating widget if AppKit is available."""
    if HAS_APPKIT:
        return FloatingWidget(
            on_record_start,
            on_record_stop,
            size=size,
            initial_position=initial_position,
            on_position_changed=on_position_changed,
        )
    return None
