"""Tests for the bundled "crt-terminal" character pack (manifest v2).

These load the REAL pack directory from the repo through the public
``character_packs`` API (mirroring ``test_builtin_panda_pack_backward_compat``)
and assert the animation / sound / interpolation metadata the engine relies on.

Like the rest of the suite, this never imports real rumps/AppKit/pynput/
sounddevice -- only the pure ``character_packs`` module is touched.
"""

import wave
from pathlib import Path

from whisper_hud.character_packs import (
    load_pack_manifest,
    ALLOWED_SOUND_EXTENSIONS,
    MAX_SOUND_SIZE,
    MIN_FRAME_FPS,
    MAX_FRAME_FPS,
)

PACK_DIR = Path(__file__).resolve().parents[1] / "assets" / "character-packs" / "crt-terminal"
ALL_STATES = {"idle", "idle_rare", "recording", "processing", "success", "error"}
# Per the pack's sound design: only these states emit audio.
SOUND_STATES = {"recording", "success", "error"}
SILENT_STATES = {"idle", "processing"}


def _load():
    pack = load_pack_manifest(PACK_DIR)
    assert pack is not None, "crt-terminal pack failed to load from the repo"
    return pack


def test_crt_terminal_pack_loads_with_expected_identity():
    pack = _load()
    assert pack.id == "crt-terminal"
    assert pack.name == "CRT Terminal"
    assert pack.author == "WhisperHUD"
    assert pack.description  # non-empty


def test_crt_terminal_has_all_five_states():
    pack = _load()
    assert set(pack.states) == ALL_STATES


def test_crt_terminal_preview_resolves():
    pack = _load()
    assert pack.preview_image == "idle_0.png"
    assert pack.preview_path
    assert Path(pack.preview_path).is_file()


def test_crt_terminal_every_state_file_resolves():
    """The single-icon fallback (``file``) must exist for every state."""
    pack = _load()
    for name, state in pack.states.items():
        assert state.full_path, f"{name} has no resolved file path"
        assert Path(state.full_path).is_file(), f"{name} file is missing"


def test_crt_terminal_frames_resolve_to_existing_files():
    """Every state animates (>1 frame) and all frames resolve on disk."""
    pack = _load()
    for name, state in pack.states.items():
        assert len(state.frames) > 1, f"{name} should be animated (>1 frame)"
        assert len(state.frames) == len(state.frame_paths)
        for fp in state.frame_paths:
            assert Path(fp).is_file(), f"{name} frame missing: {fp}"
        # The static fallback is the first animation frame.
        assert state.file == state.frames[0]


def test_crt_terminal_fps_within_supported_range():
    pack = _load()
    for name, state in pack.states.items():
        assert MIN_FRAME_FPS <= state.fps <= MAX_FRAME_FPS, f"{name} fps out of range: {state.fps}"


def test_crt_terminal_idle_is_two_frame_slow_blink():
    """Idle is the blinking cursor: a short, slow 2-frame loop."""
    pack = _load()
    idle = pack.states["idle"]
    assert len(idle.frames) == 2
    assert idle.fps <= 4  # a blink, not a fast animation


def test_crt_terminal_sounds_only_on_expected_states():
    """Only recording/success/error carry a sound; idle/processing stay silent."""
    pack = _load()
    for name in SOUND_STATES:
        state = pack.states[name]
        assert state.sound, f"{name} should define a sound"
        assert state.sound_path, f"{name} sound did not resolve"
    for name in SILENT_STATES:
        state = pack.states[name]
        assert state.sound == "", f"{name} should be silent"
        assert state.sound_path == "", f"{name} should have no resolved sound"


def test_crt_terminal_sounds_are_small_valid_wavs():
    """Each sound is a real .wav, within the engine's extension/size limits."""
    pack = _load()
    for name in SOUND_STATES:
        state = pack.states[name]
        path = Path(state.sound_path)
        assert path.is_file()
        assert path.suffix.lower() == ".wav"
        assert path.suffix.lower() in ALLOWED_SOUND_EXTENSIONS
        assert path.stat().st_size <= MAX_SOUND_SIZE
        # Confirms it is actually a parseable PCM WAV, not a renamed blob.
        with wave.open(str(path), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2  # 16-bit
            assert wf.getframerate() == 22050
            assert wf.getnframes() > 0


def test_crt_terminal_uses_nearest_interpolation():
    pack = _load()
    assert pack.settings.get("interpolation") == "nearest"
    assert pack.get_interpolation() == "nearest"


def test_crt_terminal_settings_are_alpha_no_tint():
    pack = _load()
    assert pack.settings.get("shape_mode") == "alpha"
    assert pack.settings.get("apply_state_tint") is False


def test_crt_terminal_appearance_config_emits_v2_payload():
    """``to_appearance_config`` must surface animations, sounds and interpolation."""
    pack = _load()
    ac = pack.to_appearance_config()

    assert ac["interpolation"] == "nearest"
    assert ac["character_pack"] == "crt-terminal"

    # Every state contributes an animation entry with a frame list + fps.
    assert set(ac["animations"]) == ALL_STATES
    for name, anim in ac["animations"].items():
        assert len(anim["frames"]) > 1
        assert all(Path(p).is_file() for p in anim["frames"])
        assert MIN_FRAME_FPS <= anim["fps"] <= MAX_FRAME_FPS

    # Sounds map only contains the three sounding states, all on disk.
    assert set(ac["sounds"]) == SOUND_STATES
    for path in ac["sounds"].values():
        assert Path(path).is_file()


def test_crt_terminal_icons_map_covers_all_states():
    pack = _load()
    icons = pack.get_all_icon_paths()
    assert set(icons) == ALL_STATES
    for path in icons.values():
        assert Path(path).is_file()
