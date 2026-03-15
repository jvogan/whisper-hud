"""Tests for local Whisper provider platform-specific compute selection."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from whisper_hud.providers.whisper_local import WhisperLocalProvider


def test_load_model_uses_coreml_on_apple_silicon(monkeypatch):
    """Apple Silicon Macs should select the Core ML backend."""
    whisper_model_cls = MagicMock(return_value=object())
    monkeypatch.setattr("whisper_hud.providers.whisper_local.platform.machine", lambda: "arm64")
    monkeypatch.setitem(__import__("sys").modules, "faster_whisper", SimpleNamespace(WhisperModel=whisper_model_cls))

    provider = WhisperLocalProvider()
    provider._load_model()

    whisper_model_cls.assert_called_once_with(
        provider.model,
        device="cpu",
        compute_type="coreml",
        download_root=str(provider._get_model_path().parent),
    )


def test_load_model_uses_float16_on_intel_mac(monkeypatch):
    """Intel Macs should fall back to float16."""
    whisper_model_cls = MagicMock(return_value=object())
    monkeypatch.setattr("whisper_hud.providers.whisper_local.platform.machine", lambda: "x86_64")
    monkeypatch.setitem(__import__("sys").modules, "faster_whisper", SimpleNamespace(WhisperModel=whisper_model_cls))

    provider = WhisperLocalProvider()
    provider._load_model()

    whisper_model_cls.assert_called_once_with(
        provider.model,
        device="cpu",
        compute_type="float16",
        download_root=str(provider._get_model_path().parent),
    )
