"""Tests for the local Whisper provider."""

from types import ModuleType, SimpleNamespace
import sys

import pytest

import whisper_hud.providers.whisper_local as whisper_local_module
from whisper_hud.providers.base import TranscriptionResult
from whisper_hud.providers.whisper_local import CACHE_DIR, WhisperLocalProvider


class FakeWhisperModel:
    """Capture model initialization args for assertions."""

    instances = []

    def __init__(self, model, device, compute_type, download_root):
        self.model = model
        self.device = device
        self.compute_type = compute_type
        self.download_root = download_root
        self.transcribe_calls = []
        FakeWhisperModel.instances.append(self)

    def transcribe(self, *args, **kwargs):
        self.transcribe_calls.append((args, kwargs))
        return (
            [SimpleNamespace(text="hello"), SimpleNamespace(text="world")],
            SimpleNamespace(language="en"),
        )


def install_fake_module(monkeypatch, name, **attrs):
    """Install a lightweight module into sys.modules for import-based code paths."""
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def record_progress(events):
    """Build a progress callback that stores both callback arguments."""
    return lambda message, progress: events.append((message, progress))


@pytest.fixture(autouse=True)
def clear_fake_modules():
    """Reset global test state between cases."""
    FakeWhisperModel.instances.clear()
    yield
    FakeWhisperModel.instances.clear()


def test_invalid_model_defaults_to_large_v3_turbo():
    provider = WhisperLocalProvider(model="not-a-real-model")

    assert provider.get_current_model() == "large-v3-turbo"


@pytest.mark.parametrize(
    ("machine", "expected_compute_type"),
    [("arm64", "coreml"), ("x86_64", "float16")],
)
def test_load_model_selects_compute_type_by_architecture(monkeypatch, machine, expected_compute_type):
    monkeypatch.setattr(whisper_local_module.platform, "machine", lambda: machine)
    install_fake_module(monkeypatch, "faster_whisper", WhisperModel=FakeWhisperModel)

    provider = WhisperLocalProvider()
    model = provider._load_model()

    assert model is provider._whisper_model
    assert len(FakeWhisperModel.instances) == 1
    instance = FakeWhisperModel.instances[0]
    assert instance.model == provider.model
    assert instance.device == "cpu"
    assert instance.compute_type == expected_compute_type
    assert instance.download_root == str(CACHE_DIR)


def test_load_model_returns_cached_instance_without_reloading(monkeypatch):
    monkeypatch.setattr(whisper_local_module.platform, "machine", lambda: "arm64")
    install_fake_module(monkeypatch, "faster_whisper", WhisperModel=FakeWhisperModel)

    provider = WhisperLocalProvider()
    first = provider._load_model()
    second = provider._load_model()

    assert first is second
    assert len(FakeWhisperModel.instances) == 1


def test_load_model_raises_runtime_error_when_package_missing(monkeypatch):
    monkeypatch.delitem(sys.modules, "faster_whisper", raising=False)

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "faster_whisper":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    provider = WhisperLocalProvider()

    with pytest.raises(RuntimeError, match="faster-whisper not installed"):
        provider._load_model()


def test_load_model_raises_runtime_error_when_initialization_fails(monkeypatch):
    class BrokenWhisperModel:
        def __init__(self, *args, **kwargs):
            raise ValueError("broken model")

    install_fake_module(monkeypatch, "faster_whisper", WhisperModel=BrokenWhisperModel)

    provider = WhisperLocalProvider()

    with pytest.raises(RuntimeError, match="Failed to load Whisper model: broken model"):
        provider._load_model()


def test_is_model_downloaded_returns_true_when_cache_hit(monkeypatch):
    install_fake_module(
        monkeypatch,
        "huggingface_hub",
        try_to_load_from_cache=lambda repo_id, filename: "/tmp/model.bin",
    )

    provider = WhisperLocalProvider(model="small")

    assert provider.is_model_downloaded() is True


def test_is_model_downloaded_returns_false_when_cache_lookup_fails(monkeypatch):
    install_fake_module(
        monkeypatch,
        "huggingface_hub",
        try_to_load_from_cache=lambda repo_id, filename: (_ for _ in ()).throw(RuntimeError("cache error")),
    )

    provider = WhisperLocalProvider()

    assert provider.is_model_downloaded() is False


def test_is_configured_reports_unavailable_when_faster_whisper_missing(monkeypatch):
    monkeypatch.setattr(whisper_local_module.importlib.util, "find_spec", lambda name: None)

    provider = WhisperLocalProvider()

    assert provider.is_configured() is False
    assert provider.is_faster_whisper_installed() is False
    assert provider.get_availability_message() == "Install faster-whisper: pip install faster-whisper"


def test_is_configured_reports_available_when_faster_whisper_installed(monkeypatch):
    monkeypatch.setattr(whisper_local_module.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(WhisperLocalProvider, "is_model_downloaded", lambda self: True)

    provider = WhisperLocalProvider()

    assert provider.is_configured() is True
    assert provider.is_faster_whisper_installed() is True
    assert provider.get_availability_message() == "Whisper Local is available"


def test_get_models_includes_download_state(monkeypatch):
    downloaded_models = {"tiny", "large-v3-turbo"}
    monkeypatch.setattr(
        WhisperLocalProvider,
        "_is_specific_model_downloaded",
        lambda self, model_id: model_id in downloaded_models,
    )

    provider = WhisperLocalProvider()
    models = provider.get_models()

    assert len(models) == len(provider.MODELS)
    assert next(model for model in models if model["id"] == "tiny")["downloaded"] is True
    assert next(model for model in models if model["id"] == "base")["downloaded"] is False
    assert next(model for model in models if model["id"] == "large-v3-turbo")["recommended"] is True


def test_set_model_changes_provider_and_resets_cached_model():
    provider = WhisperLocalProvider(model="tiny")
    provider._whisper_model = object()

    provider.set_model("base")

    assert provider.get_current_model() == "base"
    assert provider._whisper_model is None


def test_set_model_ignores_unknown_model():
    provider = WhisperLocalProvider(model="tiny")

    provider.set_model("unknown")

    assert provider.get_current_model() == "tiny"


def test_transcribe_returns_text_and_metadata(monkeypatch, sample_audio_bytes):
    provider = WhisperLocalProvider(model="small")
    fake_model = FakeWhisperModel("small", "cpu", "float16", str(CACHE_DIR))
    deleted_paths = []

    monkeypatch.setattr(provider, "_load_model", lambda: fake_model)
    monkeypatch.setattr("whisper_hud.encryption.secure_delete", deleted_paths.append)
    monkeypatch.setattr(whisper_local_module.time, "time", lambda: 100.0 if not deleted_paths else 101.5)

    result = provider.transcribe(sample_audio_bytes)

    assert isinstance(result, TranscriptionResult)
    assert result.text == "hello world"
    assert result.provider == provider.name
    assert result.model == "small"
    assert result.language == "en"
    assert result.cost_estimate == 0.0
    assert result.duration_seconds == pytest.approx(1.5)
    assert len(fake_model.transcribe_calls) == 1
    call_args, call_kwargs = fake_model.transcribe_calls[0]
    assert call_args and call_args[0].endswith(".wav")
    assert call_kwargs == {"beam_size": 5, "language": None, "vad_filter": True}
    assert len(deleted_paths) == 1
    assert deleted_paths[0].endswith(".wav")


def test_transcribe_wraps_transcription_errors(monkeypatch, sample_audio_bytes):
    provider = WhisperLocalProvider()
    deleted_paths = []

    class BrokenModel:
        def transcribe(self, *args, **kwargs):
            raise ValueError("decode failed")

    monkeypatch.setattr(provider, "_load_model", lambda: BrokenModel())
    monkeypatch.setattr("whisper_hud.encryption.secure_delete", deleted_paths.append)

    with pytest.raises(RuntimeError, match="Whisper transcription failed: decode failed"):
        provider.transcribe(sample_audio_bytes)

    assert len(deleted_paths) == 1


def test_download_model_reports_success(monkeypatch):
    callbacks = []
    snapshot_calls = []

    def fake_snapshot_download(model_name, cache_dir, local_files_only):
        snapshot_calls.append((model_name, cache_dir, local_files_only))
        return "/tmp/model"

    install_fake_module(monkeypatch, "huggingface_hub", snapshot_download=fake_snapshot_download)

    provider = WhisperLocalProvider(model="tiny")

    assert provider.download_model(record_progress(callbacks)) is True
    assert snapshot_calls == [("Systran/faster-whisper-tiny", str(CACHE_DIR), False)]
    assert callbacks[0] == ("Downloading Tiny (75MB) (75MB)...", 0.0)
    assert callbacks[-1] == ("Download complete!", 100.0)


def test_download_model_reports_missing_dependency(monkeypatch):
    callbacks = []

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "huggingface_hub":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    provider = WhisperLocalProvider()

    assert provider.download_model(record_progress(callbacks)) is False
    assert callbacks == [("Error: faster-whisper not installed", 0.0)]


def test_download_model_reports_runtime_failure(monkeypatch):
    callbacks = []

    def fake_snapshot_download(*args, **kwargs):
        raise RuntimeError("network disabled")

    install_fake_module(monkeypatch, "huggingface_hub", snapshot_download=fake_snapshot_download)

    provider = WhisperLocalProvider()

    assert provider.download_model(record_progress(callbacks)) is False
    assert callbacks[-1] == ("Error: network disabled", 0.0)


def test_transcribe_streaming_emits_chunks_and_returns_final_result(monkeypatch, sample_audio_bytes):
    provider = WhisperLocalProvider(model="base")
    chunks = []
    deleted_paths = []
    fake_model = FakeWhisperModel("base", "cpu", "float16", str(CACHE_DIR))

    monkeypatch.setattr(provider, "_load_model", lambda: fake_model)
    monkeypatch.setattr("whisper_hud.encryption.secure_delete", deleted_paths.append)
    monkeypatch.setattr(whisper_local_module.time, "time", lambda: 200.0 if not chunks else 201.0)

    result = provider.transcribe_streaming(sample_audio_bytes, chunks.append)

    assert chunks == ["hello", "hello world"]
    assert result.text == "hello world"
    assert result.language == "en"
    assert result.duration_seconds == pytest.approx(1.0)
    assert len(deleted_paths) == 1


def test_transcribe_streaming_wraps_errors(monkeypatch, sample_audio_bytes):
    provider = WhisperLocalProvider()

    class BrokenModel:
        def transcribe(self, *args, **kwargs):
            raise ValueError("stream failed")

    monkeypatch.setattr(provider, "_load_model", lambda: BrokenModel())
    monkeypatch.setattr("whisper_hud.encryption.secure_delete", lambda path: None)

    with pytest.raises(RuntimeError, match="Whisper streaming transcription failed: stream failed"):
        provider.transcribe_streaming(sample_audio_bytes, lambda chunk: None)


def test_check_disk_space_uses_home_volume_stats(monkeypatch):
    stat = SimpleNamespace(f_frsize=1024 * 1024, f_bavail=300)
    monkeypatch.setattr(whisper_local_module.os, "statvfs", lambda path: stat)

    has_space, available_mb = WhisperLocalProvider.check_disk_space(100)

    assert has_space is True
    assert available_mb == pytest.approx(300.0)


def test_check_disk_space_returns_false_on_failure(monkeypatch):
    monkeypatch.setattr(
        whisper_local_module.os,
        "statvfs",
        lambda path: (_ for _ in ()).throw(OSError("unavailable")),
    )

    assert WhisperLocalProvider.check_disk_space(100) == (False, 0.0)


def test_provider_helper_methods_expose_static_metadata():
    provider = WhisperLocalProvider(model="medium")

    assert provider.get_download_size() == 1500
    assert provider.supports_streaming() is True
    assert provider.get_supported_languages()["en"] == "English"
