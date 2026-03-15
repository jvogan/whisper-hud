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

from .logging_config import get_logger

logger = get_logger("hud")

try:
    from AppKit import (
        NSWindow, NSView, NSColor, NSFont,
        NSWindowStyleMaskBorderless, NSBackingStoreBuffered,
        NSFloatingWindowLevel, NSScreen, NSTextField,
        NSMakeRect,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorStationary
    )
    from PyObjCTools import AppHelper
    from objc import super as objc_super
    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False
    logger.warning("PyObjC not available, HUD will use menu bar only")


class HUDState(Enum):
    """HUD display states."""
    HIDDEN = "hidden"
    RECORDING = "recording"
    PROCESSING = "processing"
    SUCCESS = "success"
    ERROR = "error"


if HAS_APPKIT:
    class HUDContentView(NSView):
        """Content view that lets the full HUD surface dismiss error state on click."""

        def initWithFrame_onClick_(self, frame, on_click):
            self = objc_super(HUDContentView, self).initWithFrame_(frame)
            if self is None:
                return None
            self._on_click = on_click
            return self

        def mouseDown_(self, event):
            if self._on_click:
                self._on_click()


def _hex_to_cgcolor(hex_color: str):
    """Convert hex color string to CGColor via NSColor."""
    if not HAS_APPKIT:
        return None

    try:
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 6:
            r = int(hex_color[0:2], 16) / 255.0
            g = int(hex_color[2:4], 16) / 255.0
            b = int(hex_color[4:6], 16) / 255.0
            return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 1.0).CGColor()
    except Exception:
        pass
    return None


class HUD:
    """
    Floating HUD for visual feedback.

    States:
    - recording: Red pulsing indicator, "Recording..."
    - processing: Spinning indicator, "Transcribing..."
    - success: Green checkmark, auto-dismiss after 1s
    - error: Red indicator with message

    Supports customizable indicator colors via appearance config.
    """

    # Default indicator colors
    DEFAULT_COLORS = {
        "recording": "#F85149",  # Red
        "processing": "#F0883E",  # Orange/Yellow
        "success": "#3FB950",    # Green
        "error": "#F85149"       # Red
    }

    def __init__(self):
        self._window: Optional[NSWindow] = None
        self._label: Optional[NSTextField] = None
        self._indicator_view: Optional[NSView] = None
        self._level_bars: list = []  # Audio level indicator bars
        self._state = HUDState.HIDDEN
        self._dismiss_timer: Optional[threading.Timer] = None
        self._enabled = True
        self._lock = threading.Lock()
        self._last_level_update = 0.0  # Throttle level updates
        self._appearance_config: Optional[dict] = None

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the HUD."""
        self._enabled = enabled
        if not enabled:
            self.hide()

    def set_appearance(self, appearance_config: dict) -> None:
        """Set the appearance configuration for customizable colors."""
        self._appearance_config = appearance_config

    def _get_indicator_color(self, state: HUDState):
        """Get the indicator color for a state, respecting appearance config."""
        if not HAS_APPKIT:
            return None

        # Map HUD states to widget states for color lookup
        state_map = {
            HUDState.RECORDING: "recording",
            HUDState.PROCESSING: "processing",
            HUDState.SUCCESS: "success",
            HUDState.ERROR: "error"
        }

        state_name = state_map.get(state)
        if not state_name:
            return NSColor.redColor().CGColor()

        # Check appearance config for custom color
        if self._appearance_config:
            colors = self._appearance_config.get("colors", {})
            state_colors = colors.get(state_name, {})
            hex_color = state_colors.get("background")
            if hex_color:
                cgcolor = _hex_to_cgcolor(hex_color)
                if cgcolor:
                    return cgcolor

        # Fall back to default colors
        hex_color = self.DEFAULT_COLORS.get(state_name, "#F85149")
        cgcolor = _hex_to_cgcolor(hex_color)
        if cgcolor:
            return cgcolor

        # Ultimate fallback to system colors
        color_map = {
            HUDState.RECORDING: NSColor.redColor(),
            HUDState.PROCESSING: NSColor.systemYellowColor(),
            HUDState.SUCCESS: NSColor.systemGreenColor(),
            HUDState.ERROR: NSColor.systemRedColor()
        }
        return color_map.get(state, NSColor.redColor()).CGColor()

    def _ensure_window(self):
        """Create window if needed (must be called on main thread)."""
        if not HAS_APPKIT or self._window is not None:
            return

        # Window dimensions (wider to accommodate level bars and longer error messages)
        width, height = 260, 44
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
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
        )

        # Create rounded background view
        content = HUDContentView.alloc().initWithFrame_onClick_(
            NSMakeRect(0, 0, width, height),
            self._handle_click,
        )
        self._window.setContentView_(content)
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

        # Create text label (wider to accommodate longer error messages)
        self._label = NSTextField.alloc().initWithFrame_(NSMakeRect(40, 10, 160, 24))
        self._label.setBezeled_(False)
        self._label.setDrawsBackground_(False)
        self._label.setEditable_(False)
        self._label.setSelectable_(False)
        self._label.setTextColor_(NSColor.whiteColor())
        self._label.setFont_(NSFont.systemFontOfSize_weight_(14, 0.3))  # Medium weight
        content.addSubview_(self._label)

        # Create audio level bars (5 bars on the right side)
        self._level_bars = []
        bar_width = 4
        bar_spacing = 2
        bar_start_x = 205
        bar_base_y = 12
        for i in range(5):
            bar_height = 6 + i * 4  # Increasing heights: 6, 10, 14, 18, 22
            bar_y = bar_base_y + (20 - bar_height) // 2  # Center vertically
            bar = NSView.alloc().initWithFrame_(
                NSMakeRect(bar_start_x + i * (bar_width + bar_spacing), bar_y, bar_width, bar_height)
            )
            bar.setWantsLayer_(True)
            bar_layer = bar.layer()
            bar_layer.setCornerRadius_(2)
            bar_layer.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.3, 1.0).CGColor())
            bar.setHidden_(True)  # Hidden by default, shown during recording
            content.addSubview_(bar)
            self._level_bars.append(bar)

    def show_recording(self):
        """Show recording state."""
        if not self._enabled:
            return
        self._show("Recording...", HUDState.RECORDING, show_level_bars=True)

    def update_audio_level(self, level: float):
        """
        Update the audio level indicator.

        Args:
            level: Normalized audio level from 0.0 to 1.0
        """
        if not self._enabled or self._state != HUDState.RECORDING:
            return

        if not HAS_APPKIT or not self._level_bars:
            return

        # Throttle updates to max 15/second
        current_time = time.time()
        if current_time - self._last_level_update < 0.066:
            return
        self._last_level_update = current_time

        def _update_bars():
            if not self._level_bars:
                return

            # Map level (0-1) to number of lit bars (0-5)
            # Use square root for better perception of loudness changes
            # Higher multiplier makes quiet sounds more visible
            import math
            num_lit = int(min(5, math.sqrt(level) * 8)) if level > 0.02 else 0

            for i, bar in enumerate(self._level_bars):
                bar_layer = bar.layer()
                if i < num_lit:
                    # Lit bar - color based on level
                    if i < 2:
                        color = NSColor.systemGreenColor()
                    elif i < 4:
                        color = NSColor.systemYellowColor()
                    else:
                        color = NSColor.systemOrangeColor()
                    bar_layer.setBackgroundColor_(color.CGColor())
                else:
                    # Unlit bar - dim gray
                    bar_layer.setBackgroundColor_(
                        NSColor.colorWithCalibratedWhite_alpha_(0.3, 1.0).CGColor()
                    )

        try:
            AppHelper.callAfter(_update_bars)
        except Exception:
            pass

    def show_processing(self, text: str = "Transcribing..."):
        """Show processing state."""
        if not self._enabled:
            return
        self._show(text, HUDState.PROCESSING, show_level_bars=False)

    def show_success(self, text: str = "Done!", auto_dismiss: float = 1.2):
        """Show success and auto-dismiss."""
        if not self._enabled:
            return
        self._show(text, HUDState.SUCCESS)
        if auto_dismiss > 0:
            self._schedule_dismiss(auto_dismiss)

    def show_error(self, message: str = "Error"):
        """Show error state with dynamic dismiss time."""
        if not self._enabled:
            return
        # Truncate long messages (45 chars is readable in the HUD width)
        display_msg = message[:45] + "..." if len(message) > 48 else message
        self._show(display_msg, HUDState.ERROR)
        # Dynamic dismiss: base 3s + 0.5s per 20 chars, capped at 8s
        dismiss_time = 3.0 + (len(message) / 40)
        self._schedule_dismiss(min(dismiss_time, 8.0))

    def _handle_click(self):
        """Dismiss the HUD immediately when the error banner is clicked."""
        if self._state == HUDState.ERROR:
            self.hide()

    def _schedule_dismiss(self, delay: float):
        """Schedule HUD dismissal."""
        with self._lock:
            if self._dismiss_timer:
                self._dismiss_timer.cancel()
            self._dismiss_timer = threading.Timer(delay, self.hide)
            self._dismiss_timer.start()

    def _show(self, text: str, state: HUDState, show_level_bars: bool = False):
        """Show window with given text and state."""
        if not HAS_APPKIT:
            logger.info(f"HUD state: {state.value}")
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
            self._window.setIgnoresMouseEvents_(state != HUDState.ERROR)

            # Set indicator color based on state (using appearance config)
            indicator_layer = self._indicator_view.layer()
            indicator_color = self._get_indicator_color(state)
            indicator_layer.setBackgroundColor_(indicator_color)

            # Show/hide level bars
            for bar in self._level_bars:
                bar.setHidden_(not show_level_bars)
                if show_level_bars:
                    # Reset to dim state
                    bar.layer().setBackgroundColor_(
                        NSColor.colorWithCalibratedWhite_alpha_(0.3, 1.0).CGColor()
                    )

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
                self._window.setIgnoresMouseEvents_(True)
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
        self._state = HUDState.HIDDEN

    def set_enabled(self, enabled: bool):
        self._enabled = enabled

    def show_recording(self):
        if self._enabled:
            logger.info("HUD: recording")
        self._state = HUDState.RECORDING

    def show_processing(self, text: str = "Transcribing..."):
        if self._enabled:
            logger.info("HUD: processing")
        self._state = HUDState.PROCESSING

    def show_success(self, text: str = "Done!", auto_dismiss: float = 1.0):
        if self._enabled:
            logger.info("HUD: success")
        self._state = HUDState.SUCCESS

    def show_error(self, message: str = "Error"):
        if self._enabled:
            logger.error("HUD: error")
        self._state = HUDState.ERROR

    def update_audio_level(self, level: float):
        """Update audio level (no-op for console HUD)."""
        pass

    def hide(self):
        self._state = HUDState.HIDDEN

    def get_state(self) -> HUDState:
        return self._state


def create_hud() -> HUD:
    """Create appropriate HUD based on available libraries."""
    if HAS_APPKIT:
        return HUD()
    return ConsoleHUD()
