"""
Streaming panel for live transcription/translation display.

A larger overlay panel that shows live text as it streams from the API.
Features:
- Two sections: Transcription (top), Translation (bottom when enabled)
- Uses NSTextView for multi-line scrollable text
- Semi-transparent dark background
- Auto-dismisses after completion
"""

import threading
import time
from enum import Enum
from typing import Optional

from .logging_config import get_logger

logger = get_logger("streaming_panel")

try:
    from AppKit import (
        NSWindow, NSView, NSColor, NSFont,
        NSWindowStyleMaskBorderless, NSBackingStoreBuffered,
        NSFloatingWindowLevel, NSScreen, NSTextField, NSWorkspace, NSButton,
        NSMakeRect,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorStationary,
        NSScrollView, NSTextView
    )
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGNullWindowID,
        kCGWindowListOptionOnScreenOnly,
    )
    from PyObjCTools import AppHelper
    from objc import super as objc_super
    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False
    CGWindowListCopyWindowInfo = None
    logger.warning("PyObjC not available, streaming panel will use console")


class StreamingPanelState(Enum):
    """Streaming panel display states."""
    HIDDEN = "hidden"
    TRANSCRIBING = "transcribing"
    TRANSLATING = "translating"
    COMPLETE = "complete"


if HAS_APPKIT:
    class StreamingPanelWindow(NSWindow):
        """Borderless window that can dismiss on Escape or focus loss."""

        def canBecomeKeyWindow(self):
            return True

        def canBecomeMainWindow(self):
            return False

        def setDismissHandler_(self, handler):
            self._dismiss_handler = handler

        def setDismissOnResign_(self, should_dismiss):
            self._dismiss_on_resign = should_dismiss

        def keyDown_(self, event):
            if event and getattr(event, "keyCode", lambda: None)() == 53:
                dismiss = getattr(self, "_dismiss_handler", None)
                if dismiss:
                    dismiss()
                return
            objc_super(StreamingPanelWindow, self).keyDown_(event)

        def resignKeyWindow(self):
            objc_super(StreamingPanelWindow, self).resignKeyWindow()
            if getattr(self, "_dismiss_on_resign", False):
                dismiss = getattr(self, "_dismiss_handler", None)
                if dismiss:
                    dismiss()

    class StreamingPanelContentView(NSView):
        """Content view that keeps clicks inside the panel from dismissing it."""

        def mouseDown_(self, event):
            objc_super(StreamingPanelContentView, self).mouseDown_(event)


class StreamingPanel:
    """
    Large overlay panel for live streaming display.

    Shows transcription and translation text as it streams from APIs.
    """

    # Panel dimensions
    WIDTH = 500
    HEIGHT = 280
    CORNER_RADIUS = 16
    PADDING = 16

    def __init__(self):
        self._window: Optional[NSWindow] = None
        self._close_button: Optional[NSButton] = None
        self._transcription_label: Optional[NSTextField] = None
        self._transcription_text: Optional[NSTextView] = None
        self._translation_label: Optional[NSTextField] = None
        self._translation_text: Optional[NSTextView] = None
        self._state = StreamingPanelState.HIDDEN
        self._dismiss_timer: Optional[threading.Timer] = None
        self._enabled = True
        self._lock = threading.Lock()
        self._show_translation = False
        # Throttling for streaming updates (~15 updates/sec)
        self._last_transcription_update = 0.0
        self._last_translation_update = 0.0
        self._update_interval = 0.066  # ~15 updates/sec
        self._pending_transcription: Optional[str] = None
        self._pending_translation: Optional[str] = None
        self._latest_transcription = ""

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the streaming panel."""
        self._enabled = enabled
        if not enabled:
            self.hide()

    def _ensure_window(self):
        """Create window if needed (must be called on main thread)."""
        if not HAS_APPKIT:
            return

        if self._window is not None:
            self._update_window_frame()
            return

        screen = self._screen_for_frontmost_window()
        frame = self._window_frame_for_screen(screen)
        if frame is None:
            return

        # Create borderless window
        self._window = StreamingPanelWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False
        )
        self._window.setDismissHandler_(self._handle_manual_dismiss)
        self._window.setDismissOnResign_(False)

        # Configure window
        self._window.setLevel_(NSFloatingWindowLevel + 1)
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(NSColor.clearColor())
        self._window.setHasShadow_(True)
        # Allow mouse events so users can select and copy text
        self._window.setIgnoresMouseEvents_(False)
        self._window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
        )

        # Create rounded background view
        content = StreamingPanelContentView.alloc().initWithFrame_(frame)
        self._window.setContentView_(content)
        content.setWantsLayer_(True)
        layer = content.layer()
        layer.setBackgroundColor_(
            NSColor.colorWithCalibratedWhite_alpha_(0.08, 0.95).CGColor()
        )
        layer.setCornerRadius_(self.CORNER_RADIUS)
        self._create_close_button(content)

        # Create transcription section
        self._create_transcription_section(content)

        # Create translation section (initially hidden)
        self._create_translation_section(content)

    def _rect_components(self, rect):
        """Return rect components for AppKit and Quartz dict rectangles."""
        if rect is None:
            return 0.0, 0.0, 0.0, 0.0
        if isinstance(rect, dict):
            return (
                float(rect.get("X", 0.0)),
                float(rect.get("Y", 0.0)),
                float(rect.get("Width", 0.0)),
                float(rect.get("Height", 0.0)),
            )
        return (
            float(rect.origin.x),
            float(rect.origin.y),
            float(rect.size.width),
            float(rect.size.height),
        )

    def _intersection_area(self, rect_a, rect_b):
        """Return overlap area between two rectangles."""
        ax, ay, aw, ah = self._rect_components(rect_a)
        bx, by, bw, bh = self._rect_components(rect_b)
        left = max(ax, bx)
        right = min(ax + aw, bx + bw)
        bottom = max(ay, by)
        top = min(ay + ah, by + bh)
        if right <= left or top <= bottom:
            return 0.0
        return (right - left) * (top - bottom)

    def _screen_for_frontmost_window(self):
        """Return the screen containing the frontmost application window."""
        if not HAS_APPKIT:
            return None

        main_screen = NSScreen.mainScreen()
        screens = list(NSScreen.screens() or [])
        if len(screens) <= 1:
            return main_screen

        try:
            workspace = NSWorkspace.sharedWorkspace()
            app = workspace.frontmostApplication() if workspace else None
            pid = app.processIdentifier() if app else None
            if not pid or not CGWindowListCopyWindowInfo:
                return main_screen

            windows = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID) or []
            best_screen = main_screen
            best_overlap = 0.0
            for window in windows:
                if window.get("kCGWindowOwnerPID") != pid:
                    continue
                bounds = window.get("kCGWindowBounds")
                if not bounds:
                    continue

                for screen in screens:
                    overlap = self._intersection_area(bounds, screen.visibleFrame())
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_screen = screen

                if best_overlap > 0:
                    return best_screen
        except Exception:
            logger.debug("Falling back to main screen for streaming panel placement", exc_info=True)

        return main_screen

    def _window_frame_for_screen(self, screen):
        """Calculate a centered panel frame clamped to the visible screen."""
        if not screen:
            return None

        screen_rect = screen.visibleFrame()
        screen_x, screen_y, screen_width, screen_height = self._rect_components(screen_rect)
        width = min(self.WIDTH, screen_width)
        height = min(self.HEIGHT, screen_height)

        x = screen_x + (screen_width - width) / 2
        y = screen_y + (screen_height - height) / 2 + 50

        min_x = screen_x
        max_x = screen_x + screen_width - width
        min_y = screen_y
        max_y = screen_y + screen_height - height
        x = min(max(x, min_x), max_x)
        y = min(max(y, min_y), max_y)
        return NSMakeRect(x, y, width, height)

    def _update_window_frame(self):
        """Move the panel to the active screen while keeping it visible."""
        if not self._window:
            return

        screen = self._screen_for_frontmost_window()
        frame = self._window_frame_for_screen(screen)
        if frame is None:
            return
        self._window.setFrame_display_(frame, False)

    def _create_close_button(self, content):
        """Create a manual dismiss button."""
        self._close_button = NSButton.alloc().initWithFrame_(
            NSMakeRect(self.WIDTH - self.PADDING - 28, self.HEIGHT - self.PADDING - 22, 28, 22)
        )
        self._close_button.setTitle_("×")
        self._close_button.setBezelStyle_(1)
        self._close_button.setBordered_(False)
        self._close_button.setFont_(NSFont.systemFontOfSize_weight_(18, 0.5))
        self._close_button.setContentTintColor_(NSColor.colorWithCalibratedWhite_alpha_(0.85, 1.0))
        self._close_button.setTarget_(self)
        self._close_button.setAction_("closePanel:")
        content.addSubview_(self._close_button)

    def _create_transcription_section(self, content):
        """Create the transcription display section."""
        y_offset = self.HEIGHT - self.PADDING - 24

        # Transcription label
        self._transcription_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(self.PADDING, y_offset, self.WIDTH - 2 * self.PADDING, 24)
        )
        self._transcription_label.setBezeled_(False)
        self._transcription_label.setDrawsBackground_(False)
        self._transcription_label.setEditable_(False)
        self._transcription_label.setSelectable_(False)
        self._transcription_label.setTextColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.5, 0.7, 1.0, 1.0)
        )
        self._transcription_label.setFont_(NSFont.systemFontOfSize_weight_(13, 0.5))
        self._transcription_label.setStringValue_("Transcription")
        content.addSubview_(self._transcription_label)

        # Transcription text area (scrollable)
        text_height = 90
        y_offset -= text_height + 4

        scroll_view = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(self.PADDING, y_offset, self.WIDTH - 2 * self.PADDING, text_height)
        )
        scroll_view.setHasVerticalScroller_(True)
        scroll_view.setHasHorizontalScroller_(False)
        scroll_view.setAutohidesScrollers_(True)
        scroll_view.setBorderType_(0)  # No border
        scroll_view.setDrawsBackground_(False)

        # Text view inside scroll view (selectable for copy/paste)
        text_view_frame = NSMakeRect(0, 0, self.WIDTH - 2 * self.PADDING - 10, text_height)
        self._transcription_text = NSTextView.alloc().initWithFrame_(text_view_frame)
        self._transcription_text.setDrawsBackground_(False)
        self._transcription_text.setTextColor_(NSColor.whiteColor())
        self._transcription_text.setFont_(NSFont.systemFontOfSize_(15))
        self._transcription_text.setEditable_(False)
        self._transcription_text.setSelectable_(True)  # Allow text selection

        scroll_view.setDocumentView_(self._transcription_text)
        content.addSubview_(scroll_view)

    def _create_translation_section(self, content):
        """Create the translation display section."""
        y_offset = self.HEIGHT / 2 - 20

        # Translation label
        self._translation_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(self.PADDING, y_offset, self.WIDTH - 2 * self.PADDING, 24)
        )
        self._translation_label.setBezeled_(False)
        self._translation_label.setDrawsBackground_(False)
        self._translation_label.setEditable_(False)
        self._translation_label.setSelectable_(False)
        self._translation_label.setTextColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.5, 1.0, 0.7, 1.0)
        )
        self._translation_label.setFont_(NSFont.systemFontOfSize_weight_(13, 0.5))
        self._translation_label.setStringValue_("Translation")
        self._translation_label.setHidden_(True)
        content.addSubview_(self._translation_label)

        # Translation text area
        text_height = 90
        y_offset -= text_height + 4

        scroll_view = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(self.PADDING, y_offset, self.WIDTH - 2 * self.PADDING, text_height)
        )
        scroll_view.setHasVerticalScroller_(True)
        scroll_view.setHasHorizontalScroller_(False)
        scroll_view.setAutohidesScrollers_(True)
        scroll_view.setBorderType_(0)
        scroll_view.setDrawsBackground_(False)
        scroll_view.setHidden_(True)
        self._translation_scroll = scroll_view

        text_view_frame = NSMakeRect(0, 0, self.WIDTH - 2 * self.PADDING - 10, text_height)
        self._translation_text = NSTextView.alloc().initWithFrame_(text_view_frame)
        self._translation_text.setDrawsBackground_(False)
        self._translation_text.setTextColor_(NSColor.whiteColor())
        self._translation_text.setFont_(NSFont.systemFontOfSize_(15))
        self._translation_text.setEditable_(False)
        self._translation_text.setSelectable_(True)  # Allow text selection

        scroll_view.setDocumentView_(self._translation_text)
        content.addSubview_(scroll_view)

    def show_transcribing(self, show_translation: bool = False):
        """Show panel in transcribing state."""
        if not self._enabled:
            return
        self._show_translation = show_translation
        self._show("Transcribing...", StreamingPanelState.TRANSCRIBING)

    def _has_text_selection(self, text_view) -> bool:
        """Check if the text view has an active text selection."""
        if not text_view:
            return False
        try:
            selected_range = text_view.selectedRange()
            return selected_range.length > 0
        except Exception:
            return False

    def update_transcription(self, text: str):
        """Update the transcription text with throttling."""
        self._latest_transcription = text
        if not HAS_APPKIT or not self._enabled:
            logger.info(f"Transcription length: {len(text)} chars")
            return

        # Throttle updates to prevent UI lag
        current = time.time()
        if current - self._last_transcription_update < self._update_interval:
            # Store pending text - will be shown on next allowed update
            self._pending_transcription = text
            return
        self._last_transcription_update = current
        self._pending_transcription = None

        def _update():
            if self._transcription_text:
                self._transcription_text.setString_(text)
                # Only auto-scroll if user doesn't have text selected
                if not self._has_text_selection(self._transcription_text):
                    self._transcription_text.scrollRangeToVisible_(
                        (len(text), 0)
                    )

        try:
            AppHelper.callAfter(_update)
        except Exception:
            pass

    def show_translating(self):
        """Show that translation is in progress."""
        if not self._enabled:
            return
        self._state = StreamingPanelState.TRANSLATING

        def _update():
            if self._translation_label:
                self._translation_label.setStringValue_("Translating...")

        try:
            AppHelper.callAfter(_update)
        except Exception:
            pass

    def update_translation(self, text: str):
        """Update the translation text with throttling."""
        if not HAS_APPKIT or not self._enabled:
            logger.info(f"Translation length: {len(text)} chars")
            return

        # Throttle updates to prevent UI lag
        current = time.time()
        if current - self._last_translation_update < self._update_interval:
            # Store pending text - will be shown on next allowed update
            self._pending_translation = text
            return
        self._last_translation_update = current
        self._pending_translation = None

        def _update():
            if self._translation_text:
                self._translation_text.setString_(text)
                # Only auto-scroll if user doesn't have text selected
                if not self._has_text_selection(self._translation_text):
                    self._translation_text.scrollRangeToVisible_(
                        (len(text), 0)
                    )

        try:
            AppHelper.callAfter(_update)
        except Exception:
            pass

    def _flush_pending_updates(self):
        """Flush any pending throttled updates to ensure final text is shown."""
        if not HAS_APPKIT:
            return

        pending_trans = self._pending_transcription
        pending_transl = self._pending_translation
        self._pending_transcription = None
        self._pending_translation = None

        def _update():
            if pending_trans and self._transcription_text:
                self._transcription_text.setString_(pending_trans)
                self._transcription_text.scrollRangeToVisible_((len(pending_trans), 0))
            if pending_transl and self._translation_text:
                self._translation_text.setString_(pending_transl)
                self._translation_text.scrollRangeToVisible_((len(pending_transl), 0))

        if pending_trans or pending_transl:
            try:
                AppHelper.callAfter(_update)
            except Exception:
                pass

    def _auto_dismiss_delay_for_text(self, auto_dismiss: float) -> float:
        """Return completion dismiss delay based on the final transcription length."""
        word_count = len(self._latest_transcription.split())
        if word_count == 0:
            return auto_dismiss
        return 3.0 + 0.5 * (word_count // 10)

    def show_complete(self, auto_dismiss: float = 2.0):
        """Show completion and schedule dismiss."""
        if not self._enabled:
            return
        self._state = StreamingPanelState.COMPLETE

        # Flush any pending updates so final text is shown
        self._flush_pending_updates()

        def _update():
            if self._transcription_label:
                self._transcription_label.setTextColor_(
                    NSColor.colorWithCalibratedRed_green_blue_alpha_(0.4, 0.9, 0.5, 1.0)
                )
                label_text = self._transcription_label.stringValue()
                if not label_text.startswith("✓"):
                    self._transcription_label.setStringValue_("✓ Complete")

        try:
            AppHelper.callAfter(_update)
        except Exception:
            pass

        dismiss_delay = self._auto_dismiss_delay_for_text(auto_dismiss)
        if dismiss_delay > 0:
            self._schedule_dismiss(dismiss_delay)

    def _schedule_dismiss(self, delay: float):
        """Schedule panel dismissal."""
        with self._lock:
            if self._dismiss_timer:
                self._dismiss_timer.cancel()
            self._dismiss_timer = threading.Timer(delay, self.hide)
            self._dismiss_timer.start()

    def _show(self, status: str, state: StreamingPanelState):
        """Show window with given state."""
        if not HAS_APPKIT:
            logger.info(f"StreamingPanel: {status}")
            return

        with self._lock:
            self._state = state

            # Cancel any pending dismiss
            if self._dismiss_timer:
                self._dismiss_timer.cancel()
                self._dismiss_timer = None

        # Reset throttle timers for new session
        self._last_transcription_update = 0.0
        self._last_translation_update = 0.0
        self._pending_transcription = None
        self._pending_translation = None
        self._latest_transcription = ""

        def _update():
            self._ensure_window()
            if not self._window:
                return

            # Reset text
            if self._transcription_text:
                self._transcription_text.setString_("")
            if self._translation_text:
                self._translation_text.setString_("")

            # Reset label colors
            if self._transcription_label:
                self._transcription_label.setTextColor_(
                    NSColor.colorWithCalibratedRed_green_blue_alpha_(0.5, 0.7, 1.0, 1.0)
                )
                self._transcription_label.setStringValue_("Transcription")

            if self._translation_label:
                self._translation_label.setStringValue_("Translation")

            # Show/hide translation section
            if self._translation_label:
                self._translation_label.setHidden_(not self._show_translation)
            if hasattr(self, '_translation_scroll'):
                self._translation_scroll.setHidden_(not self._show_translation)

            self._update_window_frame()
            self._window.setDismissOnResign_(True)
            self._window.makeKeyAndOrderFront_(None)

        try:
            AppHelper.callAfter(_update)
        except Exception:
            pass

    def _handle_manual_dismiss(self):
        """Dismiss the panel from Escape, outside clicks, or the close button."""
        if self._state != StreamingPanelState.HIDDEN:
            self.hide()

    def closePanel_(self, _sender):
        """Objective-C action for the close button."""
        self._handle_manual_dismiss()

    def hide(self):
        """Hide the streaming panel."""
        with self._lock:
            self._state = StreamingPanelState.HIDDEN
            if self._dismiss_timer:
                self._dismiss_timer.cancel()
                self._dismiss_timer = None

        if not HAS_APPKIT:
            return

        def _hide():
            if self._window:
                if hasattr(self._window, "setDismissOnResign_"):
                    self._window.setDismissOnResign_(False)
                self._window.orderOut_(None)

        try:
            AppHelper.callAfter(_hide)
        except Exception:
            pass

    def get_state(self) -> StreamingPanelState:
        """Get current panel state."""
        return self._state


# Console fallback for when AppKit is not available
class ConsoleStreamingPanel:
    """Fallback streaming panel that prints to console."""

    def __init__(self):
        self._enabled = True
        self._state = StreamingPanelState.HIDDEN
        # Throttling for streaming updates (~15 updates/sec)
        self._last_transcription_update = 0.0
        self._last_translation_update = 0.0
        self._update_interval = 0.066

    def set_enabled(self, enabled: bool):
        self._enabled = enabled

    def show_transcribing(self, show_translation: bool = False):
        if self._enabled:
            logger.info("StreamingPanel: Transcribing...")
        self._state = StreamingPanelState.TRANSCRIBING
        # Reset throttle timers for new session
        self._last_transcription_update = 0.0
        self._last_translation_update = 0.0

    def update_transcription(self, text: str):
        if not self._enabled:
            return
        # Throttle updates
        current = time.time()
        if current - self._last_transcription_update < self._update_interval:
            return
        self._last_transcription_update = current
        logger.info(f"Transcription length: {len(text)} chars")

    def show_translating(self):
        if self._enabled:
            logger.info("StreamingPanel: Translating...")
        self._state = StreamingPanelState.TRANSLATING

    def update_translation(self, text: str):
        if not self._enabled:
            return
        # Throttle updates
        current = time.time()
        if current - self._last_translation_update < self._update_interval:
            return
        self._last_translation_update = current
        logger.info(f"Translation length: {len(text)} chars")

    def show_complete(self, auto_dismiss: float = 2.0):
        if self._enabled:
            logger.info("StreamingPanel: Complete")
        self._state = StreamingPanelState.COMPLETE

    def hide(self):
        self._state = StreamingPanelState.HIDDEN

    def get_state(self) -> StreamingPanelState:
        return self._state


def create_streaming_panel() -> StreamingPanel:
    """Create appropriate streaming panel based on available libraries."""
    if HAS_APPKIT:
        return StreamingPanel()
    return ConsoleStreamingPanel()
