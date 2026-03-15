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
import math
from enum import Enum
from typing import Optional

import pyperclip

from .logging_config import get_logger

logger = get_logger("streaming_panel")

try:
    from AppKit import (
        NSWindow,
        NSView,
        NSColor,
        NSFont,
        NSWindowStyleMaskBorderless,
        NSBackingStoreBuffered,
        NSFloatingWindowLevel,
        NSScreen,
        NSTextField,
        NSWorkspace,
        NSButton,
        NSMakeRect,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorStationary,
        NSScrollView,
        NSTextView,
        NSAccessibilityStaticTextRole,
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
    HEADER_HEIGHT = 26
    LABEL_HEIGHT = 24
    SECTION_SPACING = 16
    LABEL_TO_TEXT_GAP = 4
    MIN_TEXT_HEIGHT = 90
    TEXT_INSET = 10
    MAX_SCREEN_HEIGHT_RATIO = 0.6
    COPY_FEEDBACK_DURATION = 1.0
    AX_STATIC_TEXT_ROLE = NSAccessibilityStaticTextRole if HAS_APPKIT else "AXStaticText"
    AX_BUTTON_ROLE = "AXButton"

    def __init__(self):
        self._window: Optional[NSWindow] = None
        self._close_button: Optional[NSButton] = None
        self._copy_button: Optional[NSButton] = None
        self._transcription_label: Optional[NSTextField] = None
        self._transcription_text: Optional[NSTextView] = None
        self._transcription_scroll: Optional[NSScrollView] = None
        self._translation_label: Optional[NSTextField] = None
        self._translation_text: Optional[NSTextView] = None
        self._translation_scroll: Optional[NSScrollView] = None
        self._state = StreamingPanelState.HIDDEN
        self._dismiss_timer: Optional[threading.Timer] = None
        self._copy_feedback_timer: Optional[threading.Timer] = None
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
        self._latest_translation = ""

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
            frame, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
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
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary
        )

        # Create rounded background view
        content = StreamingPanelContentView.alloc().initWithFrame_(frame)
        self._window.setContentView_(content)
        content.setWantsLayer_(True)
        layer = content.layer()
        layer.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.08, 0.95).CGColor())
        layer.setCornerRadius_(self.CORNER_RADIUS)
        self._set_accessibility_attr(self._window, "setAccessibilityLabel_", "Transcription result")
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
        height = min(self._target_panel_height_for_screen(screen), screen_height)

        x = screen_x + (screen_width - width) / 2
        y = screen_y + (screen_height - height) / 2 + 50

        min_x = screen_x
        max_x = screen_x + screen_width - width
        min_y = screen_y
        max_y = screen_y + screen_height - height
        x = min(max(x, min_x), max_x)
        y = min(max(y, min_y), max_y)
        return NSMakeRect(x, y, width, height)

    def _max_panel_height_for_screen(self, screen) -> float:
        """Return the maximum panel height for the given screen."""
        if not screen:
            return float(self.HEIGHT)
        _, _, _, screen_height = self._rect_components(screen.visibleFrame())
        return max(float(self.HEIGHT), screen_height * self.MAX_SCREEN_HEIGHT_RATIO)

    def _estimated_text_height(self, text: str, width: float) -> float:
        """Estimate the document height for wrapped text."""
        if width <= 0:
            return float(self.MIN_TEXT_HEIGHT)
        chars_per_line = max(1, int(width / 7.5))
        lines = 0
        for raw_line in (text or "").splitlines() or [""]:
            lines += max(1, int(math.ceil(len(raw_line) / chars_per_line)))
        return max(float(self.MIN_TEXT_HEIGHT), lines * 22.0 + self.TEXT_INSET)

    def _measured_text_height(self, text_view, text: str, width: float) -> float:
        """Measure text height using AppKit when available, otherwise estimate."""
        if text_view:
            try:
                layout_manager = text_view.layoutManager()
                text_container = text_view.textContainer()
                if layout_manager and text_container:
                    text_container.setContainerSize_((width, 10_000_000.0))
                    text_container.setWidthTracksTextView_(True)
                    layout_manager.ensureLayoutForTextContainer_(text_container)
                    used_rect = layout_manager.usedRectForTextContainer_(text_container)
                    return max(float(self.MIN_TEXT_HEIGHT), float(used_rect.size.height) + self.TEXT_INSET)
            except Exception:
                logger.debug("Falling back to estimated text height", exc_info=True)
        return self._estimated_text_height(text, width)

    def _base_panel_chrome_height(self) -> float:
        """Return the height used by non-scrollable chrome."""
        base = self.PADDING * 2 + self.HEADER_HEIGHT + self.LABEL_TO_TEXT_GAP
        if self._show_translation:
            base += self.SECTION_SPACING + self.LABEL_HEIGHT + self.LABEL_TO_TEXT_GAP
        return float(base)

    def _target_panel_height_for_screen(self, screen) -> float:
        """Return the desired panel height for current content on the target screen."""
        content_width = self.WIDTH - 2 * self.PADDING - self.TEXT_INSET
        transcription_height = self._measured_text_height(
            self._transcription_text, self._latest_transcription, content_width
        )
        total_height = self._base_panel_chrome_height() + transcription_height
        if self._show_translation:
            translation_height = self._measured_text_height(
                self._translation_text, self._latest_translation, content_width
            )
            total_height += translation_height
        return min(max(float(self.HEIGHT), total_height), self._max_panel_height_for_screen(screen))

    def _section_viewport_heights(self, panel_height: float):
        """Return viewport heights for the visible text sections."""
        content_width = self.WIDTH - 2 * self.PADDING - self.TEXT_INSET
        desired = [self._measured_text_height(self._transcription_text, self._latest_transcription, content_width)]
        if self._show_translation:
            desired.append(self._measured_text_height(self._translation_text, self._latest_translation, content_width))

        minimums = [float(self.MIN_TEXT_HEIGHT)] * len(desired)
        available = max(float(sum(minimums)), panel_height - self._base_panel_chrome_height())
        heights = minimums[:]
        extras = [max(0.0, want - minimum) for want, minimum in zip(desired, minimums)]
        remaining = max(0.0, available - sum(minimums))
        total_extra = sum(extras)
        if total_extra <= 0 or remaining <= 0:
            return heights

        for idx, extra in enumerate(extras):
            share = remaining * (extra / total_extra)
            heights[idx] += min(extra, share)

        leftover = available - sum(heights)
        for idx, extra in enumerate(extras):
            if leftover <= 0:
                break
            room = extra - (heights[idx] - minimums[idx])
            if room <= 0:
                continue
            delta = min(room, leftover)
            heights[idx] += delta
            leftover -= delta
        return heights

    def _set_text_view_document_height(self, text_view, height: float):
        """Resize the text view document so the scroll view can scroll when needed."""
        if not text_view:
            return
        frame = text_view.frame()
        text_view.setFrame_(
            NSMakeRect(frame.origin.x, frame.origin.y, frame.size.width, max(height, frame.size.height))
        )

    def _layout_content(self, panel_height: Optional[float] = None):
        """Lay out controls for the current panel height."""
        if not self._window:
            return

        if panel_height is None:
            panel_height = self._window.frame().size.height

        content = self._window.contentView()
        if not content:
            return

        content.setFrame_(NSMakeRect(0, 0, self.WIDTH, panel_height))

        button_y = panel_height - self.PADDING - self.HEADER_HEIGHT
        close_x = self.WIDTH - self.PADDING - 28
        copy_x = close_x - 76 - 8
        label_width = copy_x - self.PADDING - 8

        if self._transcription_label:
            self._transcription_label.setFrame_(NSMakeRect(self.PADDING, button_y, label_width, self.LABEL_HEIGHT))
        if self._copy_button:
            self._copy_button.setFrame_(NSMakeRect(copy_x, button_y, 76, self.HEADER_HEIGHT))
        if self._close_button:
            self._close_button.setFrame_(NSMakeRect(close_x, button_y, 28, 22))

        viewport_heights = self._section_viewport_heights(panel_height)
        transcription_height = viewport_heights[0]
        translation_height = viewport_heights[1] if self._show_translation and len(viewport_heights) > 1 else 0.0
        content_width = self.WIDTH - 2 * self.PADDING
        document_width = content_width - self.TEXT_INSET

        transcription_y = button_y - self.LABEL_TO_TEXT_GAP - transcription_height
        if self._transcription_scroll:
            self._transcription_scroll.setFrame_(
                NSMakeRect(self.PADDING, transcription_y, content_width, transcription_height)
            )
        self._set_text_view_document_height(
            self._transcription_text,
            self._measured_text_height(self._transcription_text, self._latest_transcription, document_width),
        )

        translation_label_y = transcription_y - self.SECTION_SPACING - self.LABEL_HEIGHT
        translation_text_y = translation_label_y - self.LABEL_TO_TEXT_GAP - translation_height
        if self._translation_label:
            self._translation_label.setFrame_(
                NSMakeRect(self.PADDING, translation_label_y, content_width, self.LABEL_HEIGHT)
            )
            self._translation_label.setHidden_(not self._show_translation)
        if self._translation_scroll:
            self._translation_scroll.setFrame_(
                NSMakeRect(self.PADDING, translation_text_y, content_width, translation_height)
            )
            self._translation_scroll.setHidden_(not self._show_translation)
        self._set_text_view_document_height(
            self._translation_text,
            self._measured_text_height(self._translation_text, self._latest_translation, document_width),
        )

    def _resize_panel_to_fit_content(self):
        """Resize the panel to fit current content up to the per-screen maximum."""
        if not self._window:
            return

        screen = self._screen_for_frontmost_window()
        frame = self._window_frame_for_screen(screen)
        if frame is None:
            return
        self._window.setFrame_display_(frame, False)
        self._layout_content(frame.size.height)

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
        self._set_accessibility_attr(
            self._close_button,
            "setAccessibilityLabel_",
            "Dismiss transcription panel",
        )
        content.addSubview_(self._close_button)

        self._copy_button = NSButton.alloc().initWithFrame_(
            NSMakeRect(self.WIDTH - self.PADDING - 112, self.HEIGHT - self.PADDING - self.HEADER_HEIGHT, 76, 26)
        )
        self._copy_button.setTitle_("Copy")
        self._copy_button.setBezelStyle_(1)
        self._copy_button.setTarget_(self)
        self._copy_button.setAction_("copyTranscription:")
        self._set_accessibility_attr(
            self._copy_button,
            "setAccessibilityLabel_",
            "Copy transcription to clipboard",
        )
        content.addSubview_(self._copy_button)

    def _create_transcription_section(self, content):
        """Create the transcription display section."""
        y_offset = self.HEIGHT - self.PADDING - self.HEADER_HEIGHT

        # Transcription label
        self._transcription_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(self.PADDING, y_offset, self.WIDTH - 2 * self.PADDING, 24)
        )
        self._transcription_label.setBezeled_(False)
        self._transcription_label.setDrawsBackground_(False)
        self._transcription_label.setEditable_(False)
        self._transcription_label.setSelectable_(False)
        self._transcription_label.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.5, 0.7, 1.0, 1.0))
        self._transcription_label.setFont_(NSFont.systemFontOfSize_weight_(13, 0.5))
        self._transcription_label.setStringValue_("Transcription")
        content.addSubview_(self._transcription_label)

        # Transcription text area (scrollable)
        text_height = 90
        y_offset -= text_height + self.LABEL_TO_TEXT_GAP

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
        self._set_text_accessibility(self._transcription_text, "")

        scroll_view.setDocumentView_(self._transcription_text)
        content.addSubview_(scroll_view)
        self._transcription_scroll = scroll_view

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
        self._translation_label.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.5, 1.0, 0.7, 1.0))
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
        self._set_text_accessibility(self._translation_text, "")

        scroll_view.setDocumentView_(self._translation_text)
        content.addSubview_(scroll_view)

    def _set_accessibility_attr(self, target, setter_name: str, value) -> None:
        """Set accessibility metadata when the AppKit object supports it."""
        if not target:
            return
        setter = getattr(target, setter_name, None)
        if setter:
            setter(value)

    def _set_text_accessibility(self, text_view, text: str) -> None:
        """Keep text views discoverable to VoiceOver as static text."""
        label = text or "No transcription text yet"
        self._set_accessibility_attr(text_view, "setAccessibilityRole_", self.AX_STATIC_TEXT_ROLE)
        self._set_accessibility_attr(text_view, "setAccessibilityLabel_", label)

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
                self._set_text_accessibility(self._transcription_text, text)
                self._resize_panel_to_fit_content()
                # Only auto-scroll if user doesn't have text selected
                if not self._has_text_selection(self._transcription_text):
                    self._transcription_text.scrollRangeToVisible_((len(text), 0))

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
        self._latest_translation = text
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
                self._set_text_accessibility(self._translation_text, text)
                self._resize_panel_to_fit_content()
                # Only auto-scroll if user doesn't have text selected
                if not self._has_text_selection(self._translation_text):
                    self._translation_text.scrollRangeToVisible_((len(text), 0))

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
                self._set_text_accessibility(self._transcription_text, pending_trans)
                self._transcription_text.scrollRangeToVisible_((len(pending_trans), 0))
            if pending_transl and self._translation_text:
                self._translation_text.setString_(pending_transl)
                self._set_text_accessibility(self._translation_text, pending_transl)
                self._translation_text.scrollRangeToVisible_((len(pending_transl), 0))
            if pending_trans or pending_transl:
                self._resize_panel_to_fit_content()

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
        self._latest_translation = ""

        def _update():
            self._ensure_window()
            if not self._window:
                return

            # Reset text
            if self._transcription_text:
                self._transcription_text.setString_("")
                self._set_text_accessibility(self._transcription_text, "")
            if self._translation_text:
                self._translation_text.setString_("")
                self._set_text_accessibility(self._translation_text, "")
            self._reset_copy_button_title()

            # Reset label colors
            if self._transcription_label:
                self._transcription_label.setTextColor_(
                    NSColor.colorWithCalibratedRed_green_blue_alpha_(0.5, 0.7, 1.0, 1.0)
                )
                self._transcription_label.setStringValue_("Transcription")

            if self._translation_label:
                self._translation_label.setStringValue_("Translation")

            # Show/hide translation section
            self._resize_panel_to_fit_content()
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

    def _reset_copy_button_title(self):
        """Reset the copy button title to its default label."""
        if self._copy_button:
            self._copy_button.setTitle_("Copy")

    def _show_copy_feedback(self):
        """Show a brief copy confirmation on the button."""
        if self._copy_button:
            self._copy_button.setTitle_("Copied!")

        with self._lock:
            if self._copy_feedback_timer:
                self._copy_feedback_timer.cancel()
            self._copy_feedback_timer = threading.Timer(self.COPY_FEEDBACK_DURATION, self._restore_copy_button)
            self._copy_feedback_timer.start()

    def _restore_copy_button(self):
        """Restore the copy button title on the main thread."""
        with self._lock:
            self._copy_feedback_timer = None

        if not HAS_APPKIT:
            return

        try:
            AppHelper.callAfter(self._reset_copy_button_title)
        except Exception:
            pass

    def copyTranscription_(self, _sender):
        """Objective-C action for copying the current transcription."""
        pyperclip.copy(self._latest_transcription)
        if HAS_APPKIT and self._enabled:
            self._show_copy_feedback()

    def hide(self):
        """Hide the streaming panel."""
        with self._lock:
            self._state = StreamingPanelState.HIDDEN
            if self._dismiss_timer:
                self._dismiss_timer.cancel()
                self._dismiss_timer = None
            if self._copy_feedback_timer:
                self._copy_feedback_timer.cancel()
                self._copy_feedback_timer = None

        if not HAS_APPKIT:
            return

        def _hide():
            self._reset_copy_button_title()
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
