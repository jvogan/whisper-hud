"""Tests for floating widget state visuals and tooltip metadata."""

from importlib import import_module, reload
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock


def _load_floating_widget_module(monkeypatch):
    appkit = ModuleType("AppKit")
    appkit.NSWindow = type("NSWindow", (), {})
    appkit.NSView = type("NSView", (), {})
    appkit.NSColor = MagicMock()
    appkit.NSBezierPath = MagicMock()
    appkit.NSWindowStyleMaskBorderless = 0
    appkit.NSBackingStoreBuffered = 0
    appkit.NSFloatingWindowLevel = 0
    appkit.NSScreen = MagicMock()
    appkit.NSMakeRect = lambda x, y, w, h: SimpleNamespace(
        origin=SimpleNamespace(x=x, y=y),
        size=SimpleNamespace(width=w, height=h),
    )
    appkit.NSTrackingArea = MagicMock()
    appkit.NSWindowCollectionBehaviorCanJoinAllSpaces = 0
    appkit.NSWindowCollectionBehaviorStationary = 0
    appkit.NSTrackingMouseEnteredAndExited = 0
    appkit.NSTrackingActiveAlways = 0
    appkit.NSTrackingInVisibleRect = 0
    appkit.NSCursor = MagicMock()
    appkit.NSCompositingOperationSourceOver = 0
    appkit.NSZeroRect = SimpleNamespace()
    appkit.NSMenu = MagicMock()
    appkit.NSMenuItem = MagicMock()
    appkit.NSAccessibilityButtonRole = "AXButton"
    appkit.NSAccessibilityImageRole = "AXImage"
    appkit.NSAccessibilityCreatedNotification = "AXCreated"
    appkit.NSAccessibilityFocusedUIElementChangedNotification = "AXFocusedUIElementChanged"
    appkit.NSAccessibilityValueChangedNotification = "AXValueChanged"
    appkit.NSAccessibilityPostNotification = MagicMock()

    pyobjc_tools = ModuleType("PyObjCTools")
    pyobjc_tools.AppHelper = SimpleNamespace(callAfter=lambda fn: fn())

    objc = ModuleType("objc")
    objc.super = super

    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    monkeypatch.setitem(sys.modules, "PyObjCTools", pyobjc_tools)
    monkeypatch.setitem(sys.modules, "objc", objc)

    module = import_module("whisper_hud.floating_widget")
    return reload(module)


class FakeTimer:
    """Threading.Timer test double that does not run asynchronously."""

    created = []

    def __init__(self, interval, function, args=None, kwargs=None):
        self.interval = interval
        self.function = function
        self.args = args or ()
        self.kwargs = kwargs or {}
        self.daemon = False
        self.started = False
        self.cancelled = False
        self.__class__.created.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


def test_widget_tooltip_shows_provider_and_hotkey(monkeypatch):
    floating_widget = _load_floating_widget_module(monkeypatch)
    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._view = MagicMock()

    widget.set_tooltip_context("OpenAI", "⌘⇧Space", "push_to_talk")

    widget._view.setToolTip_.assert_called_once_with("Provider: OpenAI\nHotkey: Hold ⌘⇧Space")


def test_widget_animation_timer_tracks_state_transitions(monkeypatch):
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._visible = True
    widget._view = MagicMock()

    widget.set_recording()

    assert widget._state == floating_widget.WidgetState.RECORDING
    assert len(FakeTimer.created) == 1
    recording_timer = FakeTimer.created[-1]
    assert recording_timer.started is True

    widget.set_processing()

    assert widget._state == floating_widget.WidgetState.PROCESSING
    assert recording_timer.cancelled is True
    assert len(FakeTimer.created) == 2
    processing_timer = FakeTimer.created[-1]
    assert processing_timer.started is True

    widget.set_idle()

    assert widget._state == floating_widget.WidgetState.IDLE
    assert processing_timer.cancelled is True
    widget._view.setAnimationPhase_.assert_called_with(0.0)


def test_widget_hide_cancels_animation_timer(monkeypatch):
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._visible = True
    widget._window = MagicMock()
    widget._view = MagicMock()

    widget.set_recording()
    active_timer = FakeTimer.created[-1]

    widget.hide()

    assert widget._visible is False
    assert active_timer.cancelled is True
    widget._window.orderOut_.assert_called_once_with(None)


def test_widget_reset_position_moves_to_primary_monitor_default(monkeypatch):
    floating_widget = _load_floating_widget_module(monkeypatch)
    screen_frame = SimpleNamespace(
        origin=SimpleNamespace(x=50, y=25),
        size=SimpleNamespace(width=1400, height=900),
    )
    floating_widget.NSScreen.mainScreen.return_value = SimpleNamespace(visibleFrame=lambda: screen_frame)

    on_position_changed = MagicMock()
    widget = floating_widget.FloatingWidget(
        lambda: None,
        lambda: None,
        size="medium",
        initial_position={"x": 100, "y": 200},
        on_position_changed=on_position_changed,
    )
    widget._window = MagicMock()

    widget.reset_position()

    expected_position = (
        screen_frame.origin.x
        + screen_frame.size.width
        - floating_widget.FloatingWidget.SIZES["medium"][0]
        - floating_widget.DEFAULT_WIDGET_RIGHT_MARGIN,
        screen_frame.origin.y + floating_widget.DEFAULT_WIDGET_BOTTOM_MARGIN,
    )
    assert widget._position == expected_position
    widget._window.setFrameOrigin_.assert_called_once_with(expected_position)
    on_position_changed.assert_called_once_with(*expected_position)


def test_widget_accessibility_label_tracks_state_changes(monkeypatch):
    floating_widget = _load_floating_widget_module(monkeypatch)
    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._view = MagicMock()
    widget._window = MagicMock()

    widget.set_recording()
    assert widget._accessibility_label == "WhisperHUD - Recording"
    widget._view.setAccessibilityLabelText_.assert_called_with("WhisperHUD - Recording")

    widget.set_processing()
    assert widget._accessibility_label == "WhisperHUD - Processing"
    widget._view.setAccessibilityLabelText_.assert_called_with("WhisperHUD - Processing")

    widget.set_idle()
    assert widget._accessibility_label == "WhisperHUD - Idle"
    widget._view.setAccessibilityLabelText_.assert_called_with("WhisperHUD - Idle")


def test_widget_posts_accessibility_notifications_on_state_change(monkeypatch):
    floating_widget = _load_floating_widget_module(monkeypatch)
    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._view = MagicMock()
    widget._window = MagicMock()

    floating_widget.NSAccessibilityPostNotification.reset_mock()

    widget.set_recording()

    assert floating_widget.NSAccessibilityPostNotification.call_count == 2
    floating_widget.NSAccessibilityPostNotification.assert_any_call(
        widget._view,
        floating_widget.NSAccessibilityValueChangedNotification,
    )
    floating_widget.NSAccessibilityPostNotification.assert_any_call(
        widget._view,
        floating_widget.NSAccessibilityFocusedUIElementChangedNotification,
    )


def test_widget_view_exposes_button_accessibility(monkeypatch):
    floating_widget = _load_floating_widget_module(monkeypatch)
    clicked = MagicMock()
    view = object.__new__(floating_widget.WidgetView)
    view._on_click = clicked
    view._accessibility_role = floating_widget.NSAccessibilityButtonRole
    view._accessibility_label = "WhisperHUD - Idle"

    assert view.isAccessibilityElement() is True
    assert view.accessibilityRole() == floating_widget.NSAccessibilityButtonRole
    assert view.accessibilityLabel() == "WhisperHUD - Idle"
    assert view.accessibilityPerformPress() is True
    clicked.assert_called_once_with()


def test_widget_state_enum_includes_success_and_error(monkeypatch):
    floating_widget = _load_floating_widget_module(monkeypatch)
    assert floating_widget.WidgetState.SUCCESS.value == "success"
    assert floating_widget.WidgetState.ERROR.value == "error"


def test_widget_set_success_enters_state_and_schedules_revert(monkeypatch):
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._visible = True
    widget._view = MagicMock()

    widget.set_success()

    assert widget._state == floating_widget.WidgetState.SUCCESS
    assert widget._accessibility_label == "WhisperHUD - Success"
    # Success does not animate, so the only timer created is the revert timer.
    assert len(FakeTimer.created) == 1
    revert_timer = FakeTimer.created[-1]
    assert revert_timer.started is True
    assert revert_timer.interval == floating_widget.SUCCESS_REVERT_SECONDS


def test_widget_set_error_schedules_longer_revert(monkeypatch):
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._visible = True
    widget._view = MagicMock()

    widget.set_error()

    assert widget._state == floating_widget.WidgetState.ERROR
    assert widget._accessibility_label == "WhisperHUD - Error"
    assert len(FakeTimer.created) == 1
    revert_timer = FakeTimer.created[-1]
    assert revert_timer.interval == floating_widget.ERROR_REVERT_SECONDS


def test_widget_revert_timer_returns_to_idle(monkeypatch):
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._visible = True
    widget._view = MagicMock()

    widget.set_success()
    revert_timer = FakeTimer.created[-1]

    # Simulate the scheduled revert firing.
    revert_timer.function(*revert_timer.args)

    assert widget._state == floating_widget.WidgetState.IDLE


def test_widget_explicit_state_change_cancels_pending_revert(monkeypatch):
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._visible = True
    widget._view = MagicMock()

    widget.set_success()
    revert_timer = FakeTimer.created[-1]

    # An explicit transition before the revert fires should cancel it.
    widget.set_recording()

    assert revert_timer.cancelled is True
    assert widget._state == floating_widget.WidgetState.RECORDING

    # Stale revert callbacks become no-ops once cancelled.
    revert_timer.function(*revert_timer.args)
    assert widget._state == floating_widget.WidgetState.RECORDING


def test_widget_hide_cancels_pending_revert(monkeypatch):
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._visible = True
    widget._window = MagicMock()
    widget._view = MagicMock()

    widget.set_error()
    revert_timer = FakeTimer.created[-1]

    widget.hide()

    assert revert_timer.cancelled is True
    # Stale revert callback must not flip an idle/hidden widget around.
    revert_timer.function(*revert_timer.args)
    assert widget._state == floating_widget.WidgetState.ERROR


def test_widget_success_then_error_keeps_widget_visible(monkeypatch):
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._visible = True
    widget._view = MagicMock()

    widget.set_success()
    success_timer = FakeTimer.created[-1]

    widget.set_error()

    # The first revert is cancelled and a fresh error-length revert is scheduled.
    assert success_timer.cancelled is True
    assert widget._state == floating_widget.WidgetState.ERROR
    error_timer = FakeTimer.created[-1]
    assert error_timer is not success_timer
    assert error_timer.interval == floating_widget.ERROR_REVERT_SECONDS


# ---------------------------------------------------------------------------
# Manifest v2: frame animation, one-shot transitions, hover/press, sounds
# ---------------------------------------------------------------------------


class _FakeFrameProcessor:
    """Image processor double returning canned frames per state."""

    def __init__(self, frames_by_state, play_sound=False):
        self._frames_by_state = frames_by_state
        self._config = SimpleNamespace(play_sound=play_sound)

    def get_icon_for_state(self, state, size):
        return f"icon::{state}"

    def get_frames_for_state(self, state, size):
        return list(self._frames_by_state.get(state, []))


def _frame_appearance(animations, sounds=None, interpolation="smooth"):
    """Build a widget appearance config that mimics a character pack."""
    return {
        "colors": {},
        "custom_icon": {
            "enabled": True,
            "per_state": True,
            "shape_mode": "alpha",
            "interpolation": interpolation,
            "animations": animations,
            "sounds": sounds or {},
            "character_pack": "test",
        },
    }


def test_state_uses_animation_includes_idle_with_frames(monkeypatch):
    """Any state with frames animates, including IDLE (idle-breathing loop)."""
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._visible = True
    widget._view = MagicMock()
    processor = _FakeFrameProcessor({"idle": ["f0", "f1", "f2"]})
    widget._appearance_config = _frame_appearance({"idle": {"frames": ["a", "b", "c"], "fps": 6}})
    widget._image_processor = processor

    # IDLE normally does not animate, but with frames it must.
    with widget._lock:
        widget._restart_animation_for_state_locked()

    assert widget._state_uses_animation() is True
    assert widget._state_frames == ["f0", "f1", "f2"]
    # A timer was scheduled to drive the frame walk.
    assert any(t.started for t in FakeTimer.created)


def test_frame_animation_advances_frame_index(monkeypatch):
    """The timer tick advances the frame index and loops for looping states."""
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._visible = True
    widget._view = MagicMock()
    widget._appearance_config = _frame_appearance({"recording": {"frames": ["a", "b"], "fps": 10}})
    widget._image_processor = _FakeFrameProcessor({"recording": ["f0", "f1"]})

    widget.set_recording()
    assert widget._frame_index == 0
    tick = FakeTimer.created[-1]

    # First tick advances to frame 1.
    tick.function(*tick.args)
    assert widget._frame_index == 1
    widget._view.setFrameIndex_.assert_called_with(1)

    # Next tick wraps back to 0 (looping state).
    tick2 = FakeTimer.created[-1]
    tick2.function(*tick2.args)
    assert widget._frame_index == 0


def test_frame_animation_uses_per_pack_fps_interval(monkeypatch):
    """The animation timer interval reflects the pack's fps for that state."""
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._visible = True
    widget._view = MagicMock()
    widget._appearance_config = _frame_appearance({"recording": {"frames": ["a", "b"], "fps": 4}})
    widget._image_processor = _FakeFrameProcessor({"recording": ["f0", "f1"]})

    widget.set_recording()
    animation_timer = FakeTimer.created[-1]
    # fps=4 -> interval 0.25s, not the default 1/15.
    assert abs(animation_timer.interval - 0.25) < 1e-9


def test_procedural_state_keeps_default_interval(monkeypatch):
    """A state without frames keeps the default 1/15s procedural cadence."""
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._visible = True
    widget._view = MagicMock()
    # No animations defined; recording falls back to procedural animation.
    widget._appearance_config = _frame_appearance({})
    widget._image_processor = _FakeFrameProcessor({})

    widget.set_recording()
    animation_timer = FakeTimer.created[-1]
    assert abs(animation_timer.interval - (1.0 / 15.0)) < 1e-9


def test_one_shot_success_plays_once_then_stops(monkeypatch):
    """SUCCESS frames play once, hold the final frame, and stop (no re-loop)."""
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._visible = True
    widget._view = MagicMock()
    widget._appearance_config = _frame_appearance({"success": {"frames": ["a", "b"], "fps": 10}})
    widget._image_processor = _FakeFrameProcessor({"success": ["f0", "f1"]})

    widget.set_success()
    assert widget._state_loops is False
    assert widget._frame_index == 0

    # Grab the animation tick timer (not the revert timer).
    anim_timers = [t for t in FakeTimer.created if t.function == widget._animation_tick]
    tick = anim_timers[-1]

    # First tick -> last frame (index 1), schedules another tick.
    tick.function(*tick.args)
    assert widget._frame_index == 1

    anim_timers = [t for t in FakeTimer.created if t.function == widget._animation_tick]
    tick2 = anim_timers[-1]
    timers_before = len([t for t in FakeTimer.created if t.function == widget._animation_tick])

    # Second tick is at the end: one-shot holds the last frame and does NOT
    # schedule another animation tick.
    tick2.function(*tick2.args)
    assert widget._frame_index == 1  # held on final frame
    timers_after = len([t for t in FakeTimer.created if t.function == widget._animation_tick])
    assert timers_after == timers_before  # no new animation tick scheduled


def test_view_interaction_scale_hover_and_press(monkeypatch):
    """Hover scales the icon up; press scales it down; press wins over hover."""
    floating_widget = _load_floating_widget_module(monkeypatch)
    view = object.__new__(floating_widget.WidgetView)
    view._is_hovering = False
    view._is_pressed = False

    assert view._interaction_scale() == 1.0

    view._is_hovering = True
    assert view._interaction_scale() == floating_widget.WidgetView.HOVER_SCALE

    view._is_pressed = True  # press takes priority
    assert view._interaction_scale() == floating_widget.WidgetView.PRESSED_SCALE


def test_per_state_sound_plays_when_enabled(monkeypatch):
    """Entering a state with a sound triggers playback when play_sound is on."""
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    played = []
    monkeypatch.setattr(
        floating_widget.FloatingWidget,
        "_play_sound_file",
        lambda self, path: played.append(path),
    )
    # Run the spawned thread body synchronously.
    monkeypatch.setattr(
        floating_widget.threading,
        "Thread",
        lambda target, args=(), daemon=None: SimpleNamespace(start=lambda: target(*args)),
    )

    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._visible = True
    widget._view = MagicMock()
    widget._appearance_config = _frame_appearance({}, sounds={"recording": "/p/blip.wav"})
    widget._image_processor = _FakeFrameProcessor({}, play_sound=True)

    widget.set_recording()
    assert played == ["/p/blip.wav"]


def test_per_state_sound_suppressed_when_disabled(monkeypatch):
    """Sounds are gated read-only on the completion-sound preference."""
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    played = []
    monkeypatch.setattr(
        floating_widget.FloatingWidget,
        "_play_sound_file",
        lambda self, path: played.append(path),
    )
    monkeypatch.setattr(
        floating_widget.threading,
        "Thread",
        lambda target, args=(), daemon=None: SimpleNamespace(start=lambda: target(*args)),
    )

    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._visible = True
    widget._view = MagicMock()
    widget._appearance_config = _frame_appearance({}, sounds={"recording": "/p/blip.wav"})
    widget._image_processor = _FakeFrameProcessor({}, play_sound=False)

    widget.set_recording()
    assert played == []


def test_play_sound_file_prefers_nssound(monkeypatch):
    """_play_sound_file uses NSSound when available, else afplay."""
    floating_widget = _load_floating_widget_module(monkeypatch)

    sound_instance = MagicMock()
    fake_nssound = MagicMock()
    fake_nssound.alloc.return_value.initWithContentsOfFile_byReference_.return_value = sound_instance
    monkeypatch.setattr(floating_widget, "NSSound", fake_nssound)

    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._play_sound_file("/p/blip.wav")

    fake_nssound.alloc.return_value.initWithContentsOfFile_byReference_.assert_called_once_with(
        "/p/blip.wav", True
    )
    sound_instance.play.assert_called_once_with()


def test_handle_click_idle_starts_recording_and_animates(monkeypatch):
    """Clicking from IDLE must transition to RECORDING via the public API.

    Regression guard: the click path used to mutate ``_state`` directly without
    restarting the animation, so the animation timer never armed and a later
    ``set_recording()`` no-op'd. It must now arm the timer, fire the
    on_record_start callback, and dedup a follow-up ``set_recording()``.
    """
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    # Run any spawned callback thread inline and record its target.
    started_targets = []

    def _fake_thread(target, args=(), daemon=None):
        started_targets.append(target)
        return SimpleNamespace(start=lambda: target(*args))

    monkeypatch.setattr(floating_widget.threading, "Thread", _fake_thread)

    record_calls = []
    widget = floating_widget.FloatingWidget(
        lambda: record_calls.append("start"),
        lambda: record_calls.append("stop"),
    )
    widget._visible = True
    widget._view = MagicMock()
    # Install a multi-frame pack so RECORDING/PROCESSING animate via frames.
    widget._appearance_config = _frame_appearance(
        {
            "recording": {"frames": ["a", "b"], "fps": 8},
            "processing": {"frames": ["c", "d"], "fps": 8},
        }
    )
    widget._image_processor = _FakeFrameProcessor(
        {"recording": ["r0", "r1"], "processing": ["p0", "p1"]}
    )

    widget._handle_click()

    assert widget._state == floating_widget.WidgetState.RECORDING
    # An animation timer was created and started on the click path.
    anim_timers = [t for t in FakeTimer.created if t.function == widget._animation_tick]
    assert len(anim_timers) == 1
    recording_timer = anim_timers[-1]
    assert recording_timer.started is True
    # The on_record_start callback fired on a (fake) thread.
    assert widget._on_record_start in started_targets
    assert record_calls == ["start"]

    # A subsequent app-callback set_recording() is a clean dedup no-op:
    # no new animation timer is armed.
    widget.set_recording()
    anim_timers_after = [t for t in FakeTimer.created if t.function == widget._animation_tick]
    assert len(anim_timers_after) == 1


def test_handle_click_recording_starts_processing_and_animates(monkeypatch):
    """A second click (from RECORDING) transitions to PROCESSING and re-arms."""
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    started_targets = []

    def _fake_thread(target, args=(), daemon=None):
        started_targets.append(target)
        return SimpleNamespace(start=lambda: target(*args))

    monkeypatch.setattr(floating_widget.threading, "Thread", _fake_thread)

    record_calls = []
    widget = floating_widget.FloatingWidget(
        lambda: record_calls.append("start"),
        lambda: record_calls.append("stop"),
    )
    widget._visible = True
    widget._view = MagicMock()
    widget._appearance_config = _frame_appearance(
        {
            "recording": {"frames": ["a", "b"], "fps": 8},
            "processing": {"frames": ["c", "d"], "fps": 8},
        }
    )
    widget._image_processor = _FakeFrameProcessor(
        {"recording": ["r0", "r1"], "processing": ["p0", "p1"]}
    )

    widget._handle_click()  # IDLE -> RECORDING
    assert widget._state == floating_widget.WidgetState.RECORDING
    recording_timer = [t for t in FakeTimer.created if t.function == widget._animation_tick][-1]

    widget._handle_click()  # RECORDING -> PROCESSING

    assert widget._state == floating_widget.WidgetState.PROCESSING
    # Previous recording animation timer was cancelled, a new one armed.
    assert recording_timer.cancelled is True
    anim_timers = [t for t in FakeTimer.created if t.function == widget._animation_tick]
    assert len(anim_timers) == 2
    assert anim_timers[-1].started is True
    # The on_record_stop callback fired.
    assert widget._on_record_stop in started_targets
    assert record_calls == ["start", "stop"]


def test_play_sound_file_holds_reference_for_duration(monkeypatch):
    """_play_sound_file sleeps for clip duration + 0.25s to keep NSSound alive."""
    floating_widget = _load_floating_widget_module(monkeypatch)

    sound_instance = MagicMock()
    sound_instance.duration.return_value = 1.5
    fake_nssound = MagicMock()
    fake_nssound.alloc.return_value.initWithContentsOfFile_byReference_.return_value = sound_instance
    monkeypatch.setattr(floating_widget, "NSSound", fake_nssound)

    sleeps = []
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda s: sleeps.append(s))

    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._play_sound_file("/p/blip.wav")

    sound_instance.play.assert_called_once_with()
    assert sleeps == [1.75]


def test_play_sound_file_caps_hold_duration(monkeypatch):
    """A long clip duration is capped so the holding thread cannot hang."""
    floating_widget = _load_floating_widget_module(monkeypatch)

    sound_instance = MagicMock()
    sound_instance.duration.return_value = 60.0
    fake_nssound = MagicMock()
    fake_nssound.alloc.return_value.initWithContentsOfFile_byReference_.return_value = sound_instance
    monkeypatch.setattr(floating_widget, "NSSound", fake_nssound)

    sleeps = []
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda s: sleeps.append(s))

    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._play_sound_file("/p/blip.wav")

    assert sleeps == [10.0]


def _reactive_widget(floating_widget):
    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._visible = True
    widget._view = MagicMock()
    widget._appearance_config = _frame_appearance({})
    widget._image_processor = _FakeFrameProcessor({})
    return widget


def test_audio_level_reacts_only_while_recording(monkeypatch):
    """The mic level is smoothed during recording and reset on leaving it."""
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    widget = _reactive_widget(floating_widget)

    # Ignored while idle.
    widget.set_audio_level(0.9)
    assert widget._audio_level == 0.0

    widget.set_recording()
    widget.set_audio_level(1.0)
    first = widget._audio_level
    assert 0.0 < first < 1.0  # smoothed, not a raw jump
    widget.set_audio_level(1.0)
    assert widget._audio_level > first  # converges upward while speaking
    widget._view.setAudioLevel_.assert_called()  # forwarded to the view

    # Leaving recording resets the level so the next turn starts quiet.
    widget.set_processing()
    assert widget._audio_level == 0.0
    widget._view.setAudioLevel_.assert_called_with(0.0)


def test_audio_level_clamps_and_rejects_garbage(monkeypatch):
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    widget = _reactive_widget(floating_widget)
    widget.set_recording()

    widget.set_audio_level(5.0)  # clamped to 1.0 before smoothing
    assert 0.0 < widget._audio_level <= 1.0
    before = widget._audio_level

    widget.set_audio_level("loud")  # garbage input is ignored
    assert widget._audio_level == before


def test_recording_frames_speed_up_with_voice(monkeypatch):
    """Live level shortens the frame interval, capped at 30fps equivalent."""
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._visible = True
    widget._view = MagicMock()
    widget._appearance_config = _frame_appearance({"recording": {"frames": ["a", "b"], "fps": 10}})
    widget._image_processor = _FakeFrameProcessor({"recording": ["f0", "f1"]})

    widget.set_recording()
    with widget._lock:
        base = widget._current_animation_interval_locked()
    assert abs(base - 0.1) < 1e-9

    widget.set_audio_level(1.0)
    with widget._lock:
        boosted = widget._current_animation_interval_locked()
    assert boosted < base

    # Even a saturated level can never push playback past 30fps.
    widget._audio_level = 1.0
    with widget._lock:
        assert widget._current_animation_interval_locked() >= (1.0 / 30.0) - 1e-9


def _quirk_widget(floating_widget, with_quirk=True):
    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._visible = True
    widget._view = MagicMock()
    animations = {"idle": {"frames": ["a", "b"], "fps": 4}}
    frames = {"idle": ["f0", "f1"]}
    if with_quirk:
        animations["idle_rare"] = {"frames": ["q0", "q1", "q2"], "fps": 10}
        frames["idle_rare"] = ["r0", "r1", "r2"]
    widget._appearance_config = _frame_appearance(animations)
    widget._image_processor = _FakeFrameProcessor(frames)
    return widget


def _quirk_timers(floating_widget_module):
    return [t for t in FakeTimer.created if t.interval == 60.0]


def test_idle_quirk_plays_once_after_quiet_stretch(monkeypatch):
    """idle_rare frames play one-shot after the random idle delay, then idle resumes."""
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    monkeypatch.setattr(floating_widget.random, "uniform", lambda a, b: 60.0)
    FakeTimer.created.clear()

    widget = _quirk_widget(floating_widget)
    with widget._lock:
        widget._restart_animation_for_state_locked()

    # The quirk timer is armed alongside the normal idle animation.
    assert len(_quirk_timers(floating_widget)) == 1
    assert widget._state_frames == ["f0", "f1"]

    # Fire it: the one-shot idle_rare sequence takes over, silently.
    quirk = _quirk_timers(floating_widget)[0]
    quirk.function(*quirk.args)
    assert widget._idle_quirk_active is True
    assert widget._state_frames == ["r0", "r1", "r2"]
    assert widget._state_loops is False
    assert widget._state_fps == 10

    # Walk the animation to completion: the last tick flips back to idle.
    for _ in range(3):
        tick = FakeTimer.created[-1]
        tick.function(*tick.args)

    assert widget._idle_quirk_active is False
    assert widget._state_frames == ["f0", "f1"]
    # A fresh quirk timer is armed for the next quiet stretch.
    assert len(_quirk_timers(floating_widget)) == 2


def test_idle_quirk_cancelled_by_state_change(monkeypatch):
    """Leaving idle invalidates the pending quirk; returning re-arms it."""
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    monkeypatch.setattr(floating_widget.random, "uniform", lambda a, b: 60.0)
    FakeTimer.created.clear()

    widget = _quirk_widget(floating_widget)
    with widget._lock:
        widget._restart_animation_for_state_locked()
    stale = _quirk_timers(floating_widget)[0]

    widget.set_recording()
    assert stale.cancelled is True
    # A stale fire (raced with the cancel) is ignored by the generation guard.
    stale.function(*stale.args)
    assert widget._idle_quirk_active is False
    assert len(_quirk_timers(floating_widget)) == 1  # none armed while recording

    widget.set_idle()
    assert len(_quirk_timers(floating_widget)) == 2  # re-armed on return to idle


def test_idle_quirk_not_armed_without_idle_rare_frames(monkeypatch):
    """Packs without an idle_rare sequence never schedule a quirk."""
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    widget = _quirk_widget(floating_widget, with_quirk=False)
    with widget._lock:
        widget._restart_animation_for_state_locked()

    assert _quirk_timers(floating_widget) == []


def test_animations_master_switch_freezes_everything(monkeypatch):
    """With the master switch off, no state schedules an animation timer."""
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    FakeTimer.created.clear()

    widget = floating_widget.FloatingWidget(lambda: None, lambda: None)
    widget._visible = True
    widget._view = MagicMock()
    widget._appearance_config = _frame_appearance({"recording": {"frames": ["a", "b"], "fps": 10}})
    widget._image_processor = _FakeFrameProcessor({"recording": ["f0", "f1"]})

    widget.set_animation_prefs(False, True)
    FakeTimer.created.clear()

    widget.set_recording()
    assert not any(t.started for t in FakeTimer.created)
    # The static frame is still pushed, so the state remains visible.
    widget._view.setFrames_.assert_called_with(["f0", "f1"])

    # Flipping the switch back on mid-state resumes the animation at once.
    widget.set_animation_prefs(True, True)
    assert any(t.started for t in FakeTimer.created)


def test_idle_animation_switch_stills_idle_only(monkeypatch):
    """Idle loop and quirks stop; recording animation is unaffected."""
    floating_widget = _load_floating_widget_module(monkeypatch)
    monkeypatch.setattr(floating_widget.threading, "Timer", FakeTimer)
    monkeypatch.setattr(floating_widget.random, "uniform", lambda a, b: 60.0)
    FakeTimer.created.clear()

    widget = _quirk_widget(floating_widget)
    widget.set_animation_prefs(True, False)
    FakeTimer.created.clear()

    with widget._lock:
        widget._restart_animation_for_state_locked()

    # No idle loop timer and no rare-quirk timer.
    assert FakeTimer.created == []

    # Recording still animates (procedural fallback in this pack).
    widget.set_recording()
    assert any(t.started for t in FakeTimer.created)
