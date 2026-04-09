"""Tests for character pack path-safety hardening."""

import json
from pathlib import Path
from unittest.mock import patch


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
