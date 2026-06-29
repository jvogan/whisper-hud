"""Tests for character pack path-safety hardening."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def _write_manifest(pack_dir: Path, payload: dict) -> None:
    (pack_dir / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")


def test_load_pack_manifest_rejects_asset_path_traversal(tmp_path):
    """Manifest asset paths must stay inside the pack directory."""
    from whisper_hud.character_packs import load_pack_manifest

    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"not-an-icon")

    _write_manifest(
        pack_dir,
        {
            "id": "safe_pack",
            "name": "Safe Pack",
            "states": {"idle": "../secret.png"},
        },
    )

    assert load_pack_manifest(pack_dir) is None


def test_install_pack_from_directory_rejects_invalid_pack_id(tmp_path):
    """Pack installs must reject manifest IDs that would escape the user-pack root."""
    from whisper_hud.character_packs import install_pack_from_directory

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "idle.png").write_bytes(b"png")
    _write_manifest(
        source_dir,
        {
            "id": "../outside",
            "name": "Traversal Pack",
            "states": {"idle": "idle.png"},
        },
    )

    user_dir = tmp_path / "user-packs"
    escaped_dest = tmp_path / "outside"
    with patch("whisper_hud.character_packs._get_user_packs_dir", return_value=user_dir):
        assert install_pack_from_directory(str(source_dir)) is None

    assert not escaped_dest.exists()


def test_delete_user_pack_rejects_path_traversal_ids(tmp_path):
    """Deleting a user pack must not accept traversal-style pack IDs."""
    from whisper_hud.character_packs import delete_user_pack

    user_dir = tmp_path / "user-packs"
    user_dir.mkdir()
    victim_dir = tmp_path / "victim"
    victim_dir.mkdir()
    (victim_dir / "keep.txt").write_text("still here", encoding="utf-8")

    with patch("whisper_hud.character_packs._get_user_packs_dir", return_value=user_dir):
        ok, message = delete_user_pack("../victim")

    assert ok is False
    assert message == "Invalid pack ID"
    assert victim_dir.exists()
    assert (victim_dir / "keep.txt").read_text(encoding="utf-8") == "still here"


def test_builtin_transcription_controls_pack_loads_from_repo():
    """The bundled transcription controls pack should be discoverable from its manifest."""
    from whisper_hud.character_packs import load_pack_manifest

    pack_dir = Path(__file__).resolve().parents[1] / "assets" / "character-packs" / "transcription-controls"
    if not pack_dir.exists():
        pytest.skip("transcription-controls pack not present in this checkout")
    pack = load_pack_manifest(pack_dir)

    assert pack is not None
    assert pack.id == "transcription-controls"
    assert pack.name == "Transcription Controls"
    assert pack.settings["shape_mode"] == "alpha"
    assert pack.settings["apply_state_tint"] is False
    assert set(pack.states) == {"idle", "recording", "processing", "success", "error"}


# ---------------------------------------------------------------------------
# Manifest v2: frame sequences, per-state sounds, interpolation (additive)
# ---------------------------------------------------------------------------


def _touch(path: Path, data: bytes = b"stub") -> None:
    path.write_bytes(data)


def test_builtin_panda_pack_backward_compat():
    """The bundled panda pack (v1 manifest) must still load identically."""
    from whisper_hud.character_packs import load_pack_manifest

    pack_dir = Path(__file__).resolve().parents[1] / "assets" / "character-packs" / "panda"
    pack = load_pack_manifest(pack_dir)

    assert pack is not None
    assert pack.id == "panda"
    assert pack.name == "Panda"
    assert pack.settings["shape_mode"] == "alpha"
    assert set(pack.states) == {"idle", "recording", "processing", "success", "error"}
    # v1 states have no frames or sounds.
    for state in pack.states.values():
        assert state.frames == []
        assert state.frame_paths == []
        assert state.sound == ""
        assert state.sound_path == ""
    # Appearance config exposes empty animation/sound maps and default interp.
    appearance = pack.to_appearance_config()
    assert appearance["animations"] == {}
    assert appearance["sounds"] == {}
    assert appearance["interpolation"] == "smooth"


def test_load_pack_manifest_parses_frames_and_fps(tmp_path):
    """Manifest v2 frame lists and fps are resolved and clamped."""
    from whisper_hud.character_packs import load_pack_manifest

    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    for name in ("idle.png", "idle_0.png", "idle_1.png", "idle_2.png"):
        _touch(pack_dir / name)

    _write_manifest(
        pack_dir,
        {
            "id": "anim_pack",
            "name": "Anim Pack",
            "states": {
                "idle": {
                    "file": "idle.png",
                    "frames": ["idle_0.png", "idle_1.png", "idle_2.png"],
                    "fps": 8,
                }
            },
            "settings": {"interpolation": "nearest"},
        },
    )

    pack = load_pack_manifest(pack_dir)
    assert pack is not None
    idle = pack.states["idle"]
    assert idle.frames == ["idle_0.png", "idle_1.png", "idle_2.png"]
    assert len(idle.frame_paths) == 3
    assert all(Path(p).is_file() for p in idle.frame_paths)
    assert idle.fps == 8.0

    appearance = pack.to_appearance_config()
    assert appearance["interpolation"] == "nearest"
    assert appearance["animations"]["idle"]["fps"] == 8.0
    assert len(appearance["animations"]["idle"]["frames"]) == 3


def test_load_pack_manifest_clamps_fps_bounds(tmp_path):
    """fps outside the supported range is clamped; bad values fall back."""
    from whisper_hud.character_packs import (
        load_pack_manifest,
        MIN_FRAME_FPS,
        MAX_FRAME_FPS,
        DEFAULT_FRAME_FPS,
    )

    def build(fps_value):
        pack_dir = tmp_path / f"pack_{fps_value}"
        pack_dir.mkdir()
        _touch(pack_dir / "idle.png")
        _touch(pack_dir / "f0.png")
        _write_manifest(
            pack_dir,
            {
                "id": "fps_pack",
                "name": "FPS Pack",
                "states": {"idle": {"file": "idle.png", "frames": ["f0.png"], "fps": fps_value}},
            },
        )
        return load_pack_manifest(pack_dir)

    assert build(0.01).states["idle"].fps == MIN_FRAME_FPS
    assert build(999).states["idle"].fps == MAX_FRAME_FPS
    assert build("not-a-number").states["idle"].fps == DEFAULT_FRAME_FPS


def test_load_pack_manifest_rejects_frame_traversal(tmp_path):
    """Frames escaping the pack directory must be dropped, not resolved."""
    from whisper_hud.character_packs import load_pack_manifest

    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    _touch(pack_dir / "idle.png")
    _touch(pack_dir / "ok.png")
    secret = tmp_path / "secret.png"
    _touch(secret, b"not-a-frame")

    _write_manifest(
        pack_dir,
        {
            "id": "traversal_frames",
            "name": "Traversal Frames",
            "states": {
                "idle": {
                    "file": "idle.png",
                    "frames": ["ok.png", "../secret.png"],
                }
            },
        },
    )

    pack = load_pack_manifest(pack_dir)
    assert pack is not None
    idle = pack.states["idle"]
    # Only the safe frame survives; the traversal frame is dropped.
    assert idle.frames == ["ok.png"]
    assert len(idle.frame_paths) == 1
    assert "secret.png" not in idle.frame_paths[0]


def test_load_pack_manifest_parses_sound(tmp_path):
    """A valid per-state sound is resolved into sound_path."""
    from whisper_hud.character_packs import load_pack_manifest

    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    _touch(pack_dir / "idle.png")
    _touch(pack_dir / "recording.png")
    _touch(pack_dir / "blip.wav", b"RIFFstub")

    _write_manifest(
        pack_dir,
        {
            "id": "sound_pack",
            "name": "Sound Pack",
            "states": {
                "idle": {"file": "idle.png"},
                "recording": {"file": "recording.png", "sound": "blip.wav"},
            },
        },
    )

    pack = load_pack_manifest(pack_dir)
    assert pack is not None
    rec = pack.states["recording"]
    assert rec.sound == "blip.wav"
    assert rec.sound_path.endswith("blip.wav")
    assert pack.to_appearance_config()["sounds"]["recording"].endswith("blip.wav")


def test_load_pack_manifest_rejects_sound_traversal(tmp_path):
    """Sounds escaping the pack directory must not be resolved."""
    from whisper_hud.character_packs import load_pack_manifest

    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    _touch(pack_dir / "idle.png")
    outside = tmp_path / "evil.wav"
    _touch(outside, b"RIFFevil")

    _write_manifest(
        pack_dir,
        {
            "id": "sound_traversal",
            "name": "Sound Traversal",
            "states": {"idle": {"file": "idle.png", "sound": "../evil.wav"}},
        },
    )

    pack = load_pack_manifest(pack_dir)
    assert pack is not None
    assert pack.states["idle"].sound == ""
    assert pack.states["idle"].sound_path == ""


def test_load_pack_manifest_rejects_bad_sound_extension(tmp_path):
    """Only .wav/.aiff sounds are accepted; others are skipped."""
    from whisper_hud.character_packs import load_pack_manifest

    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    _touch(pack_dir / "idle.png")
    _touch(pack_dir / "evil.mp3", b"ID3stub")

    _write_manifest(
        pack_dir,
        {
            "id": "bad_ext",
            "name": "Bad Ext",
            "states": {"idle": {"file": "idle.png", "sound": "evil.mp3"}},
        },
    )

    pack = load_pack_manifest(pack_dir)
    assert pack is not None
    assert pack.states["idle"].sound_path == ""


def test_load_pack_manifest_rejects_oversized_sound(tmp_path):
    """Sounds above the size cap are skipped at load time."""
    from whisper_hud.character_packs import load_pack_manifest, MAX_SOUND_SIZE

    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    _touch(pack_dir / "idle.png")
    _touch(pack_dir / "big.wav", b"\x00" * (MAX_SOUND_SIZE + 1))

    _write_manifest(
        pack_dir,
        {
            "id": "big_sound",
            "name": "Big Sound",
            "states": {"idle": {"file": "idle.png", "sound": "big.wav"}},
        },
    )

    pack = load_pack_manifest(pack_dir)
    assert pack is not None
    assert pack.states["idle"].sound_path == ""


def test_install_pack_copies_frames_and_sounds(tmp_path):
    """Install allowlist must include frame images and per-state sounds."""
    from whisper_hud.character_packs import install_pack_from_directory

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for name in ("idle.png", "idle_0.png", "idle_1.png", "rec.png", "blip.wav"):
        _touch(source_dir / name)

    _write_manifest(
        source_dir,
        {
            "id": "installable",
            "name": "Installable",
            "states": {
                "idle": {"file": "idle.png", "frames": ["idle_0.png", "idle_1.png"]},
                "recording": {"file": "rec.png", "sound": "blip.wav"},
            },
        },
    )

    user_dir = tmp_path / "user-packs"
    with patch("whisper_hud.character_packs._get_user_packs_dir", return_value=user_dir):
        installed = install_pack_from_directory(str(source_dir))

    assert installed is not None
    dest = user_dir / "installable"
    # Frames and the sound must have been copied, not silently dropped.
    assert (dest / "idle_0.png").is_file()
    assert (dest / "idle_1.png").is_file()
    assert (dest / "blip.wav").is_file()
    # Reloaded pack still resolves the frame sequence and sound.
    assert installed.states["idle"].frames == ["idle_0.png", "idle_1.png"]
    assert installed.states["recording"].sound == "blip.wav"


def test_load_pack_manifest_parses_menubar_icon(tmp_path):
    """The optional menubar_icon resolves and lands in the appearance config."""
    from whisper_hud.character_packs import load_pack_manifest

    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    _touch(pack_dir / "idle.png")
    _touch(pack_dir / "menubar.png")

    _write_manifest(
        pack_dir,
        {
            "id": "glyph_pack",
            "name": "Glyph Pack",
            "menubar_icon": "menubar.png",
            "states": {"idle": "idle.png"},
        },
    )

    pack = load_pack_manifest(pack_dir)
    assert pack is not None
    assert pack.menubar_icon == "menubar.png"
    assert Path(pack.menubar_icon_path).is_file()
    assert pack.to_appearance_config()["menubar_icon"] == pack.menubar_icon_path


def test_load_pack_manifest_rejects_menubar_icon_traversal(tmp_path):
    """A menubar_icon escaping the pack directory is dropped, not resolved."""
    from whisper_hud.character_packs import load_pack_manifest

    outside = tmp_path / "outside.png"
    _touch(outside)
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    _touch(pack_dir / "idle.png")

    _write_manifest(
        pack_dir,
        {
            "id": "sneaky_pack",
            "name": "Sneaky Pack",
            "menubar_icon": "../outside.png",
            "states": {"idle": "idle.png"},
        },
    )

    pack = load_pack_manifest(pack_dir)
    assert pack is not None  # pack still loads, the bad member is dropped
    assert pack.menubar_icon == ""
    assert pack.menubar_icon_path == ""
    assert pack.to_appearance_config()["menubar_icon"] == ""


def test_install_pack_copies_menubar_icon(tmp_path):
    """Install must copy the menubar glyph alongside the other members."""
    from whisper_hud.character_packs import install_pack_from_directory

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for name in ("idle.png", "menubar.png"):
        _touch(source_dir / name)

    _write_manifest(
        source_dir,
        {
            "id": "glyphed",
            "name": "Glyphed",
            "menubar_icon": "menubar.png",
            "states": {"idle": "idle.png"},
        },
    )

    user_dir = tmp_path / "user-packs"
    with patch("whisper_hud.character_packs._get_user_packs_dir", return_value=user_dir):
        installed = install_pack_from_directory(str(source_dir))

    assert installed is not None
    assert (user_dir / "glyphed" / "menubar.png").is_file()
    assert installed.menubar_icon == "menubar.png"


def test_builtin_retro_packs_have_menubar_icon_and_idle_quirk():
    """The three retro packs ship a menu bar glyph and a rare-idle sequence."""
    from whisper_hud.character_packs import _get_builtin_packs_dir, load_pack_manifest

    for pack_name in ("pixel-adventurer", "handheld-89", "crt-terminal"):
        pack = load_pack_manifest(_get_builtin_packs_dir() / pack_name)
        assert pack is not None, pack_name
        assert pack.menubar_icon_path, pack_name
        quirk = pack.states.get("idle_rare")
        assert quirk is not None, pack_name
        assert len(quirk.frame_paths) >= 2, pack_name
        appearance = pack.to_appearance_config()
        assert appearance["menubar_icon"] == pack.menubar_icon_path
        assert len(appearance["animations"]["idle_rare"]["frames"]) >= 2


def test_save_user_pack_preserves_distinct_success(tmp_path, monkeypatch):
    """A distinct success image must not be overwritten by the recording alias."""
    from whisper_hud import character_packs

    user_dir = tmp_path / "user-packs"
    monkeypatch.setattr(character_packs, "_get_user_packs_dir", lambda: user_dir)

    class FakeProcessor:
        def save_image(self, image, filepath):
            Path(filepath).write_bytes(b"png")
            return True

    # Sentinel NSImage stand-ins; success differs from recording.
    images = {
        "idle": object(),
        "recording": object(),
        "processing": object(),
        "error": object(),
        "success": object(),
    }

    ok, result = character_packs.save_user_pack("distinct-success", "Distinct", "desc", images, FakeProcessor())
    assert ok is True

    manifest = json.loads((Path(result) / "manifest.json").read_text())
    # success must point at its own file, not recording.png.
    assert manifest["states"]["success"] == "success.png"
    assert manifest["states"]["recording"] == "recording.png"


def test_save_user_pack_aliases_success_to_recording_when_missing(tmp_path, monkeypatch):
    """The classic 4-image flow still aliases success to the recording image."""
    from whisper_hud import character_packs

    user_dir = tmp_path / "user-packs"
    monkeypatch.setattr(character_packs, "_get_user_packs_dir", lambda: user_dir)

    class FakeProcessor:
        def save_image(self, image, filepath):
            Path(filepath).write_bytes(b"png")
            return True

    images = {
        "idle": object(),
        "recording": object(),
        "processing": object(),
        "error": object(),
    }

    ok, result = character_packs.save_user_pack("classic-flow", "Classic", "desc", images, FakeProcessor())
    assert ok is True

    manifest = json.loads((Path(result) / "manifest.json").read_text())
    assert manifest["states"]["success"] == "recording.png"
