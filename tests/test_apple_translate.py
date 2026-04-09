"""Tests for Apple Translation helper resolution."""

import sys

from whisper_hud.providers.translation.apple_translate import AppleTranslateProvider


def test_helper_path_ignores_untrusted_override(monkeypatch):
    """Development overrides should stay inside the repo-controlled helper directory."""
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setenv("WHISPERHUD_APPLE_TRANSLATE_HELPER", "/tmp/evil-helper")

    assert AppleTranslateProvider._helper_path() == AppleTranslateProvider._source_helper_path()


def test_helper_path_accepts_repo_local_override(monkeypatch):
    """Repo-local helper overrides remain available for development workflows."""
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    allowed_dir = AppleTranslateProvider._source_helper_path().parent
    override = allowed_dir / "custom-helper"
    monkeypatch.setenv("WHISPERHUD_APPLE_TRANSLATE_HELPER", str(override))

    assert AppleTranslateProvider._helper_path() == override.resolve()
