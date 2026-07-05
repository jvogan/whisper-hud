"""Tests for py2app bundle asset declarations."""

import runpy
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_setup_app_bundles_character_pack_wav_assets(monkeypatch):
    """Built-in character-pack sounds must be copied by py2app data_files."""
    captured = {}

    def fake_setup(**kwargs):
        captured.update(kwargs)

    class DummyPy2App:
        def finalize_options(self):
            return None

    py2app_module = types.ModuleType("py2app")
    build_app_module = types.ModuleType("py2app.build_app")
    setuptools_module = types.ModuleType("setuptools")
    setuptools_module.setup = fake_setup
    build_app_module.py2app = DummyPy2App
    py2app_module.build_app = build_app_module

    monkeypatch.setitem(sys.modules, "setuptools", setuptools_module)
    monkeypatch.setitem(sys.modules, "py2app", py2app_module)
    monkeypatch.setitem(sys.modules, "py2app.build_app", build_app_module)

    runpy.run_path(str(REPO_ROOT / "setup_app.py"))

    data_files = captured["data_files"]
    bundled_files = {file_name for _destination, file_names in data_files for file_name in file_names}
    expected_wavs = {
        str(path.relative_to(REPO_ROOT)) for path in (REPO_ROOT / "assets" / "character-packs").rglob("*.wav")
    }

    assert expected_wavs, "expected at least one built-in character-pack .wav fixture"
    assert expected_wavs <= bundled_files
