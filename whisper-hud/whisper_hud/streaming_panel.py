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
from typing import Optional
from enum import Enum

from .logging_config import get_logger

logger = get_logger("streaming_panel")

try:
    from AppKit import (
        NSWindow, NSColor, NSFont,
        NSWindowStyleMaskBorderless, NSBackingStoreBuffered,
        NSFloatingWindowLevel, NSScreen, NSTextField,
        NSMakeRect,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorStationary,
        NSScrollView, NSTextView
    )
    from PyObjCTools import AppHelper
    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False
    logger.warning("PyObjC not available, streaming panel will use console")


class StreamingPanelState(Enum):
    """Streaming panel display states."""
    HIDDEN = "hidden"
    TRANSCRIBING = "transcribing"
    TRANSLATING = "translating"
    COMPLETE = "complete"


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

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the streaming panel."""
        self._enabled = enabled
        if not enabled:
            self.hide()

    def _ensure_window(self):
        """Create window if needed (must be called on main thread)."""
        if not HAS_APPKIT or self._window is not None:
            return

        # Position in center of screen
        screen = NSScreen.mainScreen()
        if not screen:
            return
        screen_rect = screen.visibleFrame()
        x = screen_rect.origin.x + (screen_rect.size.width - self.WIDTH) / 2
        y = screen_rect.origin.y + (screen_rect.size.height - self.HEIGHT) / 2 + 50

        # Create borderless window
        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, self.WIDTH, self.HEIGHT),
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
        content = self._window.contentView()
        content.setWantsLayer_(True)
        layer = content.layer()
        layer.setBackgroundColor_(
            NSColor.colorWithCalibratedWhite_alpha_(0.08, 0.95).CGColor()
        )
        layer.setCornerRadius_(self.CORNER_RADIUS)

        # Create transcription section
        self._create_transcription_section(content)

        # Create translation section (initially hidden)
        self._create_translation_section(content)

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

        # Text view inside scroll view
        text_view_frame = NSMakeRect(0, 0, self.WIDTH - 2 * self.PADDING - 10, text_height)
        self._transcription_text = NSTextView.alloc().initWithFrame_(text_view_frame)
        self._transcription_text.setDrawsBackground_(False)
        self._transcription_text.setTextColor_(NSColor.whiteColor())
        self._transcription_text.setFont_(NSFont.systemFontOfSize_(15))
        self._transcription_text.setEditable_(False)
        self._transcription_text.setSelectable_(False)

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
        self._translation_text.setSelectable_(False)

        scroll_view.setDocumentView_(self._translation_text)
        content.addSubview_(scroll_view)

    def show_transcribing(self, show_translation: bool = False):
        """Show panel in transcribing state."""
        if not self._enabled:
            return
        self._show_translation = show_translation
        self._show("Transcribing...", StreamingPanelState.TRANSCRIBING)

    def update_transcription(self, text: str):
        """Update the transcription text with throttling."""
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
                # Scroll to bottom
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
                # Scroll to bottom
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

        if auto_dismiss > 0:
            self._schedule_dismiss(auto_dismiss)

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

            self._window.orderFront_(None)

        try:
            AppHelper.callAfter(_update)
        except Exception:
            pass

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
