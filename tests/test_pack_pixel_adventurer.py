"""Tests for the bundled "Pixel Adventurer" character pack (manifest v2).

These load the REAL pack directory from the repo through the public
``character_packs`` API (mirroring ``test_builtin_panda_pack_backward_compat``
in ``tests/test_character_packs.py``) and assert the v2 contract: all five
states present, frame sequences resolve to real files, fps stays in range,
sounds exist only for recording/success/error (small ``.wav`` files), the pack
requests nearest-neighbour interpolation, and ``to_appearance_config()`` emits
animations / sounds / interpolation.

Following the existing test files, no real ``rumps`` / ``AppKit`` / ``pynput`` /
``sounddevice`` is imported here; only the pure ``character_packs`` module is
exercised (its package path is set up by ``tests/conftest.py``).
"""

from pathlib import Path


PACK_ID = "pixel-adventurer"
EXPECTED_STATES = {"idle", "recording", "processing", "success", "error"}
# Per the art/sound spec: only these three states carry a sound.
SOUND_STATES = {"recording", "success", "error"}
SILENT_STATES = {"idle", "processing"}


def _pack_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "character-packs" / PACK_ID


def _load():
    from whisper_hud.character_packs import load_pack_manifest

    return load_pack_manifest(_pack_dir())


def test_pixel_adventurer_pack_loads_with_all_states():
    """The real pack loads and exposes all five widget states."""
    pack = _load()

    assert pack is not None
    assert pack.id == PACK_ID
    assert pack.name == "Pixel Adventurer"
    assert set(pack.states) == EXPECTED_STATES


def test_pixel_adventurer_frames_resolve_to_existing_files():
    """Every state animates (>1 frame) and all frame paths exist on disk."""
    pack = _load()
    assert pack is not None

    for state in EXPECTED_STATES:
        info = pack.states[state]
        # The static fallback icon must resolve.
        assert info.full_path, f"{state} missing static icon path"
        assert Path(info.full_path).is_file()

        # A quality pack animates each state.
        assert len(info.frames) > 1, f"{state} should have a frame sequence"
        assert len(info.frame_paths) == len(info.frames)
        for fp in info.frame_paths:
            assert Path(fp).is_file(), f"{state} frame missing: {fp}"
        # The first frame is the single-icon fallback file.
        assert info.frames[0] == info.file


def test_pixel_adventurer_fps_within_supported_range():
    """All declared fps values sit inside the engine's clamp window."""
    from whisper_hud.character_packs import MIN_FRAME_FPS, MAX_FRAME_FPS

    pack = _load()
    assert pack is not None

    for state in EXPECTED_STATES:
        fps = pack.states[state].fps
        assert MIN_FRAME_FPS <= fps <= MAX_FRAME_FPS, f"{state} fps {fps} out of range"


def test_pixel_adventurer_sounds_only_for_transient_states():
    """Sounds exist only for recording/success/error; idle/processing are silent."""
    pack = _load()
    assert pack is not None

    for state in SOUND_STATES:
        info = pack.states[state]
        assert info.sound, f"{state} should declare a sound"
        assert info.sound_path, f"{state} sound did not resolve"
        assert Path(info.sound_path).is_file()

    for state in SILENT_STATES:
        info = pack.states[state]
        assert info.sound == "", f"{state} must stay silent"
        assert info.sound_path == ""


def test_pixel_adventurer_sounds_are_small_wav_files():
    """Every declared sound is a .wav under the engine's 2 MB size cap."""
    from whisper_hud.character_packs import MAX_SOUND_SIZE

    pack = _load()
    assert pack is not None

    for state in SOUND_STATES:
        path = Path(pack.states[state].sound_path)
        assert path.suffix.lower() == ".wav", f"{state} sound must be .wav"
        size = path.stat().st_size
        assert 0 < size <= MAX_SOUND_SIZE, f"{state} sound size {size} invalid"


def test_pixel_adventurer_requests_nearest_interpolation():
    """The pack opts into crisp pixel-art scaling via interpolation=nearest."""
    pack = _load()
    assert pack is not None

    assert pack.settings.get("interpolation") == "nearest"
    assert pack.get_interpolation() == "nearest"
    # Recommended pixel-art rendering settings.
    assert pack.settings.get("shape_mode") == "alpha"
    assert pack.settings.get("apply_state_tint") is False


def test_pixel_adventurer_appearance_config_exposes_v2_payload():
    """``to_appearance_config`` surfaces animations, sounds and interpolation."""
    pack = _load()
    assert pack is not None

    appearance = pack.to_appearance_config()

    # Interpolation hint flows through for the rendering pipeline.
    assert appearance["interpolation"] == "nearest"

    # Animations: one entry per state, each with absolute frame paths + fps.
    animations = appearance["animations"]
    assert set(animations) == EXPECTED_STATES
    for state, anim in animations.items():
        assert anim["frames"], f"{state} animation has no frames"
        assert all(Path(p).is_file() for p in anim["frames"])
        assert anim["fps"] == pack.states[state].fps

    # Sounds: only the three transient states, each an existing absolute path.
    sounds = appearance["sounds"]
    assert set(sounds) == SOUND_STATES
    for state, sound_path in sounds.items():
        assert Path(sound_path).is_file()

    # Icons map stays a flat state -> path map (single-icon backward compat).
    assert set(appearance["icons"]) == EXPECTED_STATES
    assert appearance["character_pack"] == PACK_ID
