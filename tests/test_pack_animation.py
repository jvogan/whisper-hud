"""Tests for character-pack animation plumbing in the image processor.

Covers manifest v2 rendering support:
- interpolation hint normalization / NSImageInterpolation mapping,
- multi-frame ``get_frames_for_state`` (pipeline reuse + per-frame caching),
- cache-key isolation across interpolation and frame index.

These reuse the real (or mocked) AppKit available in the test environment and
stub the per-image rendering so no actual files are decoded.
"""

import importlib
from unittest.mock import patch


def _image_processor():
    """Import the image_processor module (package path set up by conftest)."""
    return importlib.import_module("whisper_hud.image_processor")


def test_normalize_interpolation():
    ip = _image_processor()
    assert ip._normalize_interpolation("nearest") == "nearest"
    assert ip._normalize_interpolation("smooth") == "smooth"
    assert ip._normalize_interpolation(None) == "smooth"
    assert ip._normalize_interpolation("garbage") == "smooth"


def test_interpolation_constant_maps_to_appkit(mock_appkit):
    """nearest -> None constant, anything else -> High constant."""
    ip = _image_processor()
    assert ip._interpolation_constant("nearest") == ip.NSImageInterpolationNone
    assert ip._interpolation_constant("smooth") == ip.NSImageInterpolationHigh


def test_cache_key_isolates_interpolation_and_frame_index():
    ip = _image_processor()
    base = dict(path="/p/idle.png", size=44, state="idle", tint_color="", tint_opacity=0.0, shape_mode="alpha")

    smooth = ip._get_cache_key(**base, interpolation="smooth", frame_index=-1)
    nearest = ip._get_cache_key(**base, interpolation="nearest", frame_index=-1)
    frame0 = ip._get_cache_key(**base, interpolation="smooth", frame_index=0)
    frame1 = ip._get_cache_key(**base, interpolation="smooth", frame_index=1)

    # Each axis must produce a distinct key so frames/modes never collide.
    assert len({smooth, nearest, frame0, frame1}) == 4


def test_get_frames_for_state_returns_empty_without_animations():
    ip = _image_processor()
    if not ip.HAS_APPKIT:
        return  # behaviour only meaningful when AppKit is present
    config = {"custom_icon": {"enabled": True, "per_state": True, "icons": {"idle": "/p/idle.png"}}}
    assert ip.get_frames_for_state(config, "idle", 44) == []


def test_get_frames_for_state_disabled_icon_returns_empty():
    ip = _image_processor()
    config = {"custom_icon": {"enabled": False, "animations": {"idle": {"frames": ["/p/a.png"], "fps": 10}}}}
    assert ip.get_frames_for_state(config, "idle", 44) == []


def test_get_frames_for_state_processes_each_frame():
    """Frames run through the single-icon pipeline once per frame."""
    ip = _image_processor()
    if not ip.HAS_APPKIT:
        return

    ip.clear_cache()
    sentinel_loaded = object()
    processed = {"/p/a.png": "IMG_A", "/p/b.png": "IMG_B", "/p/c.png": "IMG_C"}

    def fake_load(path):
        return sentinel_loaded

    def fake_process(image, path, size, shape_mode, interpolation="smooth"):
        return processed[path]

    config = {
        "custom_icon": {
            "enabled": True,
            "per_state": True,
            "shape_mode": "alpha",
            "interpolation": "nearest",
            "apply_state_tint": False,
            "animations": {"idle": {"frames": ["/p/a.png", "/p/b.png", "/p/c.png"], "fps": 12}},
        }
    }

    with patch.object(ip, "load_image", side_effect=fake_load):
        with patch.object(ip, "process_shape", side_effect=fake_process) as proc:
            frames = ip.get_frames_for_state(config, "idle", 44)

    assert frames == ["IMG_A", "IMG_B", "IMG_C"]
    # process_shape called once per frame with the nearest interpolation hint
    # (passed positionally as the 5th argument by _process_icon_path).
    assert proc.call_count == 3
    for call in proc.call_args_list:
        assert call.args[4] == "nearest"


def test_get_frames_for_state_caches_per_frame_index():
    """Re-requesting frames should hit the cache (no reprocessing)."""
    ip = _image_processor()
    if not ip.HAS_APPKIT:
        return

    ip.clear_cache()
    processed = {"/p/a.png": "IMG_A", "/p/b.png": "IMG_B"}

    def fake_process(image, path, size, shape_mode, interpolation="smooth"):
        return processed[path]

    config = {
        "custom_icon": {
            "enabled": True,
            "per_state": True,
            "shape_mode": "alpha",
            "apply_state_tint": False,
            "animations": {"idle": {"frames": ["/p/a.png", "/p/b.png"], "fps": 10}},
        }
    }

    with patch.object(ip, "load_image", side_effect=lambda p: object()):
        with patch.object(ip, "process_shape", side_effect=fake_process) as proc:
            first = ip.get_frames_for_state(config, "idle", 44)
            second = ip.get_frames_for_state(config, "idle", 44)

    assert first == ["IMG_A", "IMG_B"]
    assert second == ["IMG_A", "IMG_B"]
    # Only the first call processes; the second is served entirely from cache.
    assert proc.call_count == 2
    ip.clear_cache()
