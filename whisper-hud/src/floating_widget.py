"""
Floating widget for WhisperHUD.

A small, draggable window that shows recording status
and allows click-to-record as an alternative to the hotkey.
"""

import threading
from typing import Callable, Optional
from enum import Enum

try:
    from AppKit import (
        NSWindow, NSView, NSColor, NSFont, NSBezierPath,
        NSWindowStyleMaskBorderless, NSBackingStoreBuffered,
        NSFloatingWindowLevel, NSScreen, NSTextField,
        NSMakeRect, NSButton, NSTrackingArea,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorStationary,
        NSTrackingMouseEnteredAndExited, NSTrackingActiveAlways,
        NSTrackingInVisibleRect, NSEvent, NSLeftMouseDragged,
        NSApplication, NSImage, NSImageView, NSStackView,
        NSUserInterfaceLayoutOrientationHorizontal,
        NSLayoutAttributeCenterY, NSCursor
    )
    from Quartz import CGPoint
    from PyObjCTools import AppHelper
    from objc import super as objc_super
    import objc
    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False


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

        def initWithFrame_onClick_(self, frame, on_click):
            self = objc_super(WidgetView, self).initWithFrame_(frame)
            if self is None:
                return None

            self._on_click = on_click
            self._is_hovering = False
            self._state = WidgetState.IDLE
            self._initial_location = None
            self._mouse_down_time = None
            self._did_drag = False

            # Enable layer backing for smooth rendering
            self.setWantsLayer_(True)

            # Set up tracking area for hover effects
            self._setup_tracking()

            return self

        def _setup_tracking(self):
            options = (NSTrackingMouseEnteredAndExited |
                      NSTrackingActiveAlways |
                      NSTrackingInVisibleRect)
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

            # Draw rounded background
            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                self.bounds(), corner_radius, corner_radius
            )

            # Background color based on state
            if self._state == WidgetState.RECORDING:
                bg_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.85, 0.15, 0.15, 0.95)
            elif self._state == WidgetState.PROCESSING:
                bg_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.75, 0.55, 0.1, 0.95)
            else:
                if self._is_hovering:
                    bg_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.22, 0.22, 0.28, 0.95)
                else:
                    bg_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.14, 0.14, 0.18, 0.92)

            bg_color.setFill()
            path.fill()

            # Draw mic icon circle (centered)
            icon_rect = NSMakeRect(icon_offset, icon_offset, icon_size, icon_size)
            icon_path = NSBezierPath.bezierPathWithOvalInRect_(icon_rect)

            if self._state == WidgetState.RECORDING:
                NSColor.whiteColor().setFill()
            elif self._state == WidgetState.PROCESSING:
                NSColor.colorWithCalibratedRed_green_blue_alpha_(1, 1, 1, 0.9).setFill()
            else:
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0.4, 0.65, 1.0, 1.0).setFill()

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
            self._initial_location = event.locationInWindow()
            self._mouse_down_time = time.time()
            self._did_drag = False

        def mouseDragged_(self, event):
            if self._initial_location is None:
                return

            current = event.locationInWindow()
            dx = abs(current.x - self._initial_location.x)
            dy = abs(current.y - self._initial_location.y)

            # Only start dragging if moved more than 12 pixels
            # This prevents accidental drags when trying to click
            if dx > 12 or dy > 12:
                self._did_drag = True

            if not self._did_drag:
                return

            window = self.window()
            if window is None:
                return

            window_frame = window.frame()
            new_x = window_frame.origin.x + (current.x - self._initial_location.x)
            new_y = window_frame.origin.y + (current.y - self._initial_location.y)

            window.setFrameOrigin_((new_x, new_y))

        def mouseUp_(self, event):
            import time
            # Only trigger click if:
            # 1. We didn't drag
            # 2. Mouse was held for less than 0.3 seconds (not a long press for drag)
            if self._initial_location and not self._did_drag:
                hold_duration = time.time() - (self._mouse_down_time or 0)

                current = event.locationInWindow()
                dx = abs(current.x - self._initial_location.x)
                dy = abs(current.y - self._initial_location.y)

                # Click: minimal movement AND quick tap (< 0.3s) OR deliberate click (< 0.5s with no movement)
                is_click = (dx < 12 and dy < 12) and (hold_duration < 0.5)

                if is_click and self._on_click:
                    self._on_click()

            self._initial_location = None
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
        size: str = "medium"
    ):
        self._on_record_start = on_record_start
        self._on_record_stop = on_record_stop
        self._size = size if size in self.SIZES else "medium"
        self._window: Optional[NSWindow] = None
        self._view: Optional[WidgetView] = None
        self._state = WidgetState.IDLE
        self._visible = False
        self._lock = threading.Lock()
        self._position: Optional[tuple] = None  # Remember position

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
        self._window.setHasShadow_(True)
        self._window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces |
            NSWindowCollectionBehaviorStationary
        )
        self._window.setMovableByWindowBackground_(True)

        # Create custom view with size info
        self._view = WidgetView.alloc().initWithFrame_onClick_(
            NSMakeRect(0, 0, width, height),
            self._handle_click
        )
        self._view._dims = dims  # Pass dimensions to view
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

    def _update_view(self):
        """Update view state."""
        if self._view:
            def _update():
                if self._view:
                    self._view.setState_(self._state)
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


def create_floating_widget(
    on_record_start: Callable[[], None],
    on_record_stop: Callable[[], None],
    size: str = "medium"
) -> Optional[FloatingWidget]:
    """Create a floating widget if AppKit is available."""
    if HAS_APPKIT:
        return FloatingWidget(on_record_start, on_record_stop, size=size)
    return None
