"""Tests for the bundled **handheld-89** character pack (manifest v2).

Mirrors the mechanics of ``test_builtin_panda_pack_backward_compat`` in
``tests/test_character_packs.py``: it loads the REAL repo pack directory through
the public ``character_packs`` API and asserts the manifest v2 contract.

``whisper_hud.character_packs`` only depends on stdlib + the package's own
``logging_config``; it does NOT import rumps/AppKit/pynput/sounddevice, so these
tests import it directly the same way the existing pack tests do (no extra
mocking required — conftest already wires ``sys.path``).
"""

from pathlib import Path

from whisper_hud.character_packs import (
    load_pack_manifest,
    MIN_FRAME_FPS,
    MAX_FRAME_FPS,
    ALLOWED_SOUND_EXTENSIONS,
    MAX_SOUND_SIZE,
)

EXPECTED_STATES = {"idle", "idle_rare", "recording", "processing", "success", "error"}
SOUND_STATES = {"recording", "success", "error"}
SILENT_STATES = {"idle", "processing"}


def _pack_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "character-packs" / "handheld-89"


def _load():
    pack = load_pack_manifest(_pack_dir())
    assert pack is not None, "handheld-89 pack failed to load from the repo dir"
    return pack


def test_handheld_89_loads_with_expected_identity():
    """The pack loads from its real directory with the expected id/name."""
    pack = _load()
    assert pack.id == "handheld-89"
    assert pack.name == "Handheld '89"
    assert pack.builtin is True


def test_handheld_89_has_all_five_states():
    """All five widget states must be present for a quality pack."""
    pack = _load()
    assert set(pack.states) == EXPECTED_STATES


def test_handheld_89_frames_resolve_to_existing_files():
    """Every state animates (>1 frame) and all frame paths exist on disk."""
    pack = _load()
    for name, state in pack.states.items():
        assert len(state.frames) > 1, f"{name} should be multi-frame"
        assert len(state.frame_paths) == len(state.frames)
        for frame_path in state.frame_paths:
            p = Path(frame_path)
            assert p.is_file(), f"{name} frame missing: {frame_path}"
            assert p.suffix.lower() == ".png"
            # Frames stay inside the pack directory (no traversal).
            assert _pack_dir().resolve() in p.resolve().parents


def test_handheld_89_fps_within_supported_range():
    """Per-state fps values are within the engine's clamp window."""
    pack = _load()
    for name, state in pack.states.items():
        assert MIN_FRAME_FPS <= state.fps <= MAX_FRAME_FPS, f"{name} fps {state.fps} out of range"


def test_handheld_89_sounds_only_on_expected_states():
    """Only recording/success/error carry sounds; idle/processing are silent."""
    pack = _load()
    for name in SILENT_STATES:
        assert pack.states[name].sound == ""
        assert pack.states[name].sound_path == ""
    for name in SOUND_STATES:
        state = pack.states[name]
        assert state.sound, f"{name} should declare a sound"
        assert state.sound_path, f"{name} sound did not resolve"


def test_handheld_89_sounds_are_small_wav_files():
    """Declared sounds are .wav, exist, and stay under the 2MB cap."""
    pack = _load()
    for name in SOUND_STATES:
        state = pack.states[name]
        p = Path(state.sound_path)
        assert p.is_file(), f"{name} sound missing: {state.sound_path}"
        assert p.suffix.lower() in ALLOWED_SOUND_EXTENSIONS
        assert p.suffix.lower() == ".wav"
        assert p.stat().st_size <= MAX_SOUND_SIZE


def test_handheld_89_uses_nearest_interpolation():
    """Pixel-art pack requests crisp nearest-neighbour scaling."""
    pack = _load()
    assert pack.settings.get("interpolation") == "nearest"
    assert pack.get_interpolation() == "nearest"


def test_handheld_89_preview_image_resolves():
    """The declared preview image resolves to a real file in the pack."""
    pack = _load()
    assert pack.preview_image == "idle_0.png"
    assert pack.preview_path
    assert Path(pack.preview_path).is_file()


def test_handheld_89_appearance_config_emits_v2_payload():
    """``to_appearance_config`` exposes animations, sounds and interpolation."""
    pack = _load()
    appearance = pack.to_appearance_config()

    assert appearance["interpolation"] == "nearest"
    assert appearance["character_pack"] == "handheld-89"
    assert appearance["apply_state_tint"] is False

    # Animations: one entry per state, each with absolute frame paths + fps.
    animations = appearance["animations"]
    assert set(animations) == EXPECTED_STATES
    for name, anim in animations.items():
        assert anim["frames"], f"{name} animation has no frames"
        assert all(Path(f).is_file() for f in anim["frames"])
        assert MIN_FRAME_FPS <= anim["fps"] <= MAX_FRAME_FPS

    # Sounds: only the three transient/active states, all resolving to files.
    sounds = appearance["sounds"]
    assert set(sounds) == SOUND_STATES
    for name, sound_path in sounds.items():
        assert Path(sound_path).is_file()


def test_handheld_89_state_settings_are_sane():
    """Spot-check the per-state frame/fps/sound design contract."""
    pack = _load()
    # idle: a slow loop (low fps), silent, several frames for the blink.
    idle = pack.states["idle"]
    assert idle.fps <= 4
    assert len(idle.frames) >= 2
    assert idle.sound == ""
    # recording: brisk animation with a sound.
    rec = pack.states["recording"]
    assert rec.fps >= 6
    assert rec.sound.endswith(".wav")
    # success / error: one-shot-style flourishes with sounds; final frame held
    # by the engine (we only assert the data shape here).
    for name in ("success", "error"):
        st = pack.states[name]
        assert len(st.frames) >= 4
        assert st.sound.endswith(".wav")
