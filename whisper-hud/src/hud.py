"""
Floating HUD window for recording/processing feedback.

Uses PyObjC for native macOS window with:
- Recording indicator (pulsing red)
- Processing indicator (spinning)
- Success indicator (checkmark, auto-dismiss)
- Error indicator (message)

Positioned in the top-center of the screen.
"""

import threading
import time
from typing import Optional
from enum import Enum

try:
    from AppKit import (
        NSWindow, NSView, NSColor, NSFont, NSBezierPath,
        NSWindowStyleMaskBorderless, NSBackingStoreBuffered,
        NSFloatingWindowLevel, NSScreen, NSTextField,
        NSMakeRect, NSApplication, NSTimer,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorStationary
    )
    from Quartz import CABasicAnimation, CAShapeLayer, CALayer
    from PyObjCTools import AppHelper
    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False
    print("Warning: PyObjC not available, HUD will use menu bar only")


class HUDState(Enum):
    """HUD display states."""
    HIDDEN = "hidden"
    RECORDING = "recording"
    PROCESSING = "processing"
    SUCCESS = "success"
    ERROR = "error"


class HUD:
    """
    Floating HUD for visual feedback.

    States:
    - recording: Red pulsing indicator, "Recording..."
    - processing: Spinning indicator, "Transcribing..."
    - success: Green checkmark, auto-dismiss after 1s
    - error: Red indicator with message
    """

    def __init__(self):
        self._window: Optional[NSWindow] = None
        self._label: Optional[NSTextField] = None
        self._indicator_view: Optional[NSView] = None
        self._state = HUDState.HIDDEN
        self._dismiss_timer: Optional[threading.Timer] = None
        self._enabled = True
        self._lock = threading.Lock()

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the HUD."""
        self._enabled = enabled
        if not enabled:
            self.hide()

    def _ensure_window(self):
        """Create window if needed (must be called on main thread)."""
        if not HAS_APPKIT or self._window is not None:
            return

        # Window dimensions
        width, height = 200, 44
        corner_radius = 12

        # Position in top-center of screen
        screen = NSScreen.mainScreen()
        if not screen:
            return
        screen_rect = screen.visibleFrame()
        x = screen_rect.origin.x + (screen_rect.size.width - width) / 2
        y = screen_rect.origin.y + screen_rect.size.height - height - 80

        # Create borderless window
        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, width, height),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False
        )

        # Configure window
        self._window.setLevel_(NSFloatingWindowLevel + 1)
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(NSColor.clearColor())
        self._window.setHasShadow_(True)
        self._window.setIgnoresMouseEvents_(True)
        self._window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces |
            NSWindowCollectionBehaviorStationary
        )

        # Create rounded background view
        content = self._window.contentView()
        content.setWantsLayer_(True)
        layer = content.layer()
        layer.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.1, 0.92).CGColor())
        layer.setCornerRadius_(corner_radius)

        # Create indicator circle (left side)
        self._indicator_view = NSView.alloc().initWithFrame_(NSMakeRect(14, 14, 16, 16))
        self._indicator_view.setWantsLayer_(True)
        indicator_layer = self._indicator_view.layer()
        indicator_layer.setCornerRadius_(8)
        content.addSubview_(self._indicator_view)

        # Create text label
        self._label = NSTextField.alloc().initWithFrame_(NSMakeRect(40, 10, 150, 24))
        self._label.setBezeled_(False)
        self._label.setDrawsBackground_(False)
        self._label.setEditable_(False)
        self._label.setSelectable_(False)
        self._label.setTextColor_(NSColor.whiteColor())
        self._label.setFont_(NSFont.systemFontOfSize_weight_(14, 0.3))  # Medium weight
        content.addSubview_(self._label)

    def show_recording(self):
        """Show recording state."""
        if not self._enabled:
            return
        self._show("Recording...", HUDState.RECORDING)

    def show_processing(self):
        """Show processing state."""
        if not self._enabled:
            return
        self._show("Transcribing...", HUDState.PROCESSING)

    def show_success(self, text: str = "Done!", auto_dismiss: float = 1.2):
        """Show success and auto-dismiss."""
        if not self._enabled:
            return
        self._show(text, HUDState.SUCCESS)
        if auto_dismiss > 0:
            self._schedule_dismiss(auto_dismiss)

    def show_error(self, message: str = "Error"):
        """Show error state."""
        if not self._enabled:
            return
        # Truncate long messages
        display_msg = message[:25] + "..." if len(message) > 28 else message
        self._show(display_msg, HUDState.ERROR)
        self._schedule_dismiss(3.0)

    def _schedule_dismiss(self, delay: float):
        """Schedule HUD dismissal."""
        with self._lock:
            if self._dismiss_timer:
                self._dismiss_timer.cancel()
            self._dismiss_timer = threading.Timer(delay, self.hide)
            self._dismiss_timer.start()

    def _show(self, text: str, state: HUDState):
        """Show window with given text and state."""
        if not HAS_APPKIT:
            print(f"[HUD] {text}")
            return

        with self._lock:
            self._state = state

            # Cancel any pending dismiss
            if self._dismiss_timer:
                self._dismiss_timer.cancel()
                self._dismiss_timer = None

        def _update():
            self._ensure_window()
            if not self._window or not self._label or not self._indicator_view:
                return

            self._label.setStringValue_(text)

            # Set indicator color based on state
            indicator_layer = self._indicator_view.layer()

            if state == HUDState.RECORDING:
                indicator_layer.setBackgroundColor_(NSColor.redColor().CGColor())
            elif state == HUDState.PROCESSING:
                indicator_layer.setBackgroundColor_(NSColor.systemYellowColor().CGColor())
            elif state == HUDState.SUCCESS:
                indicator_layer.setBackgroundColor_(NSColor.systemGreenColor().CGColor())
            elif state == HUDState.ERROR:
                indicator_layer.setBackgroundColor_(NSColor.systemRedColor().CGColor())

            self._window.orderFront_(None)

        # Must run on main thread
        try:
            AppHelper.callAfter(_update)
        except Exception:
            pass  # App might be shutting down

    def hide(self):
        """Hide the HUD window."""
        with self._lock:
            self._state = HUDState.HIDDEN
            if self._dismiss_timer:
                self._dismiss_timer.cancel()
                self._dismiss_timer = None

        if not HAS_APPKIT:
            return

        def _hide():
            if self._window:
                self._window.orderOut_(None)

        try:
            AppHelper.callAfter(_hide)
        except Exception:
            pass

    def get_state(self) -> HUDState:
        """Get current HUD state."""
        return self._state


# Simpler fallback HUD that just prints to console
class ConsoleHUD:
    """Fallback HUD that prints to console."""

    def __init__(self):
        self._enabled = True

    def set_enabled(self, enabled: bool):
        self._enabled = enabled

    def show_recording(self):
        if self._enabled:
            print("[HUD] Recording...")

    def show_processing(self):
        if self._enabled:
            print("[HUD] Transcribing...")

    def show_success(self, text: str = "Done!", auto_dismiss: float = 1.0):
        if self._enabled:
            print(f"[HUD] {text}")

    def show_error(self, message: str = "Error"):
        if self._enabled:
            print(f"[HUD] Error: {message}")

    def hide(self):
        pass

    def get_state(self) -> HUDState:
        return HUDState.HIDDEN


def create_hud() -> HUD:
    """Create appropriate HUD based on available libraries."""
    if HAS_APPKIT:
        return HUD()
    return ConsoleHUD()
