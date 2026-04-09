"""Tests for the Parakeet transcription provider."""

from types import ModuleType, SimpleNamespace

import pytest

from whisper_hud.providers.parakeet import ParakeetProvider


@pytest.fixture
def fake_parakeet_module(monkeypatch):
    """Install a minimal parakeet_mlx module for provider tests."""

    calls = {"load_model": [], "transcribe": []}
    module = ModuleType("parakeet_mlx")

    def load_model(model_name):
        calls["load_model"].append(model_name)
        return {"loaded_model": model_name}

    def transcribe(path, **kwargs):
        calls["transcribe"].append({"path": path, **kwargs})
        return {"text": "  hello from parakeet  "}

    module.load_model = load_model
    module.transcribe = transcribe
    monkeypatch.setitem(__import__("sys").modules, "parakeet_mlx", module)

    return calls, module


@pytest.fixture
def fake_hf_module(monkeypatch):
    """Install a minimal huggingface_hub module for cache/download tests."""

    calls = {"cache": [], "download": []}
    module = ModuleType("huggingface_hub")

    def try_to_load_from_cache(model_name, filename):
        calls["cache"].append((model_name, filename))
        return "/tmp/cached-config.json"

    def snapshot_download(model_name, **kwargs):
        calls["download"].append((model_name, kwargs))
        return "/tmp/model-cache"

    module.try_to_load_from_cache = try_to_load_from_cache
    module.snapshot_download = snapshot_download
    monkeypatch.setitem(__import__("sys").modules, "huggingface_hub", module)

    return calls, module


def test_provider_reports_unavailable_when_parakeet_package_not_installed(monkeypatch):
    """Availability should be false when the package cannot be discovered."""
    provider = ParakeetProvider()
    monkeypatch.setattr(provider, "_is_apple_silicon", lambda: True)
    monkeypatch.setattr("whisper_hud.providers.parakeet.importlib.util.find_spec", lambda _: None)

    assert provider._check_availability() is False
    assert provider._available is False


def test_provider_reports_available_when_parakeet_package_present(monkeypatch):
    """Availability should be true when Apple Silicon and the package is installed."""
    provider = ParakeetProvider()
    monkeypatch.setattr(provider, "_is_apple_silicon", lambda: True)
    monkeypatch.setattr("whisper_hud.providers.parakeet.importlib.util.find_spec", lambda _: object())

    assert provider._check_availability() is True
    assert provider._available is True


def test_load_model_caches_loaded_model(monkeypatch, fake_parakeet_module):
    """Model loading should call parakeet_mlx once and cache the result."""
    calls, _module = fake_parakeet_module
    provider = ParakeetProvider()

    first = provider._load_model()
    second = provider._load_model()

    assert first == {"loaded_model": provider.model}
    assert second is first
    assert calls["load_model"] == [provider.model]


def test_model_loading_failure_raises_runtime_error(monkeypatch, fake_parakeet_module):
    """Loader failures should be wrapped in a provider-specific RuntimeError."""
    _calls, module = fake_parakeet_module

    def broken_load_model(_model_name):
        raise ValueError("weights missing")

    module.load_model = broken_load_model

    with pytest.raises(RuntimeError, match="Failed to load Parakeet model: weights missing"):
        ParakeetProvider()._load_model()


def test_successful_transcription_returns_correct_text(monkeypatch, sample_audio_bytes, fake_parakeet_module):
    """Successful transcriptions should normalize text and return metadata."""
    calls, _module = fake_parakeet_module
    deleted_paths = []

    monkeypatch.setattr(ParakeetProvider, "_is_apple_silicon", lambda self: True)
    monkeypatch.setattr(ParakeetProvider, "_check_availability", lambda self: True)
    monkeypatch.setattr("whisper_hud.encryption.secure_delete", lambda path: deleted_paths.append(path))

    provider = ParakeetProvider()
    result = provider.transcribe(sample_audio_bytes)

    assert result.text == "hello from parakeet"
    assert result.provider == "parakeet"
    assert result.model == provider.model
    assert result.cost_estimate == 0.0
    assert result.language is None
    assert result.duration_seconds >= 0
    assert len(calls["transcribe"]) == 1
    assert calls["transcribe"][0]["model"] == provider.model
    assert calls["transcribe"][0]["path"].endswith(".wav")
    assert deleted_paths == [calls["transcribe"][0]["path"]]


def test_transcription_error_propagates_correctly(monkeypatch, sample_audio_bytes, fake_parakeet_module):
    """Transcription failures should keep the provider error prefix."""
    _calls, module = fake_parakeet_module
    deleted_paths = []

    def broken_transcribe(_path, **_kwargs):
        raise Exception("decoder exploded")

    module.transcribe = broken_transcribe
    monkeypatch.setattr(ParakeetProvider, "_is_apple_silicon", lambda self: True)
    monkeypatch.setattr(ParakeetProvider, "_check_availability", lambda self: True)
    monkeypatch.setattr("whisper_hud.encryption.secure_delete", lambda path: deleted_paths.append(path))

    with pytest.raises(RuntimeError, match="Parakeet transcription failed: decoder exploded"):
        ParakeetProvider().transcribe(sample_audio_bytes)

    assert len(deleted_paths) == 1
    assert deleted_paths[0].endswith(".wav")


def test_transcribe_requires_apple_silicon(sample_audio_bytes, monkeypatch):
    """Non-Apple systems should fail before any package work happens."""
    monkeypatch.setattr(ParakeetProvider, "_is_apple_silicon", lambda self: False)

    with pytest.raises(RuntimeError, match="Parakeet requires Apple Silicon"):
        ParakeetProvider().transcribe(sample_audio_bytes)


def test_transcribe_requires_installed_package(sample_audio_bytes, monkeypatch):
    """Missing parakeet_mlx should raise a descriptive install error."""
    monkeypatch.setattr(ParakeetProvider, "_is_apple_silicon", lambda self: True)
    monkeypatch.setattr(ParakeetProvider, "_check_availability", lambda self: False)

    with pytest.raises(RuntimeError, match="parakeet-mlx is not installed"):
        ParakeetProvider().transcribe(sample_audio_bytes)


def test_is_configured_requires_platform_package_and_downloaded_model(monkeypatch):
    """Configured status should depend on all three prerequisites."""
    provider = ParakeetProvider()

    monkeypatch.setattr(provider, "_is_apple_silicon", lambda: True)
    monkeypatch.setattr(provider, "_check_availability", lambda: True)
    monkeypatch.setattr(provider, "is_model_downloaded", lambda: True)
    assert provider.is_configured() is True

    monkeypatch.setattr(provider, "is_model_downloaded", lambda: False)
    assert provider.is_configured() is False

    monkeypatch.setattr(provider, "_check_availability", lambda: False)
    assert provider.is_configured() is False

    monkeypatch.setattr(provider, "_is_apple_silicon", lambda: False)
    assert provider.is_configured() is False


def test_model_download_helpers_use_huggingface_cache(monkeypatch, fake_hf_module):
    """Download checks should probe the expected Hugging Face cache key."""
    calls, _module = fake_hf_module
    provider = ParakeetProvider()

    assert provider.is_model_downloaded() is True
    assert provider._is_specific_model_downloaded("parakeet-tdt-0.6b-v3") is True
    assert calls["cache"] == [
        (f"nvidia/{provider.model}", "config.json"),
        ("nvidia/parakeet-tdt-0.6b-v3", "config.json"),
    ]


def test_model_download_helpers_return_false_when_cache_lookup_fails(monkeypatch, fake_hf_module):
    """Cache helper failures should be treated as not-downloaded."""
    _calls, module = fake_hf_module

    def broken_cache(*_args, **_kwargs):
        raise RuntimeError("cache unavailable")

    module.try_to_load_from_cache = broken_cache
    provider = ParakeetProvider()

    assert provider.is_model_downloaded() is False
    assert provider._is_specific_model_downloaded(provider.model) is False


def test_model_helpers_and_metadata():
    """Model setters/getters and metadata helpers should stay consistent."""
    provider = ParakeetProvider(model="not-a-real-model")

    assert provider.get_current_model() == "parakeet-tdt-0.6b-v3"
    assert provider.get_download_size() == 600
    assert provider.supports_streaming() is True

    models = provider.get_models()
    assert models[0]["id"] == "parakeet-tdt-0.6b-v3"
    assert models[0]["recommended"] is True

    sentinel_same_model = object()
    provider._parakeet_model = sentinel_same_model
    provider.set_model("parakeet-tdt-0.6b-v3")
    assert provider._parakeet_model is sentinel_same_model

    sentinel = object()
    provider._parakeet_model = sentinel
    provider.set_model("not-a-real-model")
    assert provider.get_current_model() == "parakeet-tdt-0.6b-v3"
    assert provider._parakeet_model is sentinel


def test_set_model_resets_loaded_model_when_switching(monkeypatch):
    """Changing to a valid different model ID should clear the cached model."""
    provider = ParakeetProvider()
    provider.MODELS = {
        **provider.MODELS,
        "parakeet-alt": {
            "name": "Alt",
            "size_mb": 700,
            "description": "alt",
            "languages": "multilingual",
        },
    }
    provider._parakeet_model = object()

    provider.set_model("parakeet-alt")

    assert provider.get_current_model() == "parakeet-alt"
    assert provider._parakeet_model is None


def test_download_model_reports_success(monkeypatch, fake_hf_module):
    """Downloads should call snapshot_download and notify progress."""
    calls, _module = fake_hf_module
    progress = []

    monkeypatch.setattr(ParakeetProvider, "_is_apple_silicon", lambda self: True)

    def callback(message, percent):
        progress.append((message, percent))

    assert ParakeetProvider().download_model(callback) is True
    assert calls["download"][0][0] == "nvidia/parakeet-tdt-0.6b-v3"
    assert progress == [
        ("Downloading Parakeet 0.6B v3 (600MB)...", 0.0),
        ("Download complete!", 100.0),
    ]


def test_download_model_handles_platform_and_dependency_failures(monkeypatch, fake_hf_module):
    """Download helper should fail cleanly for unsupported hosts and hub errors."""
    progress = []
    provider = ParakeetProvider()

    def callback(message, percent):
        progress.append((message, percent))

    monkeypatch.setattr(provider, "_is_apple_silicon", lambda: False)
    assert provider.download_model(callback) is False
    assert progress == [("Error: Parakeet requires Apple Silicon", 0.0)]

    progress.clear()
    monkeypatch.setattr(provider, "_is_apple_silicon", lambda: True)
    real_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "huggingface_hub":
            raise ImportError("missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)
    assert provider.download_model(callback) is False
    assert progress == [("Error: huggingface_hub not installed", 0.0)]


def test_download_model_reports_runtime_failure(monkeypatch, fake_hf_module):
    """Unexpected hub failures should be surfaced through the progress callback."""
    _calls, module = fake_hf_module
    progress = []

    def broken_download(*_args, **_kwargs):
        raise RuntimeError("no space left")

    module.snapshot_download = broken_download
    monkeypatch.setattr(ParakeetProvider, "_is_apple_silicon", lambda self: True)

    def callback(message, percent):
        progress.append((message, percent))

    assert ParakeetProvider().download_model(callback) is False
    assert progress == [
        ("Downloading Parakeet 0.6B v3 (600MB)...", 0.0),
        ("Error: no space left", 0.0),
    ]


def test_transcribe_streaming_emits_word_chunks_and_final_text(
    monkeypatch,
    sample_audio_bytes,
    fake_parakeet_module,
):
    """Streaming mode should emit cumulative chunks when word timestamps exist."""
    _calls, module = fake_parakeet_module
    seen_chunks = []
    deleted_paths = []

    def streaming_transcribe(path, **kwargs):
        assert kwargs["word_timestamps"] is True
        return {
            "text": "hello world",
            "words": [{"word": "hello"}, {"word": "world"}],
        }

    module.transcribe = streaming_transcribe
    monkeypatch.setattr(ParakeetProvider, "_is_apple_silicon", lambda self: True)
    monkeypatch.setattr("whisper_hud.encryption.secure_delete", lambda path: deleted_paths.append(path))

    result = ParakeetProvider().transcribe_streaming(sample_audio_bytes, seen_chunks.append)

    assert seen_chunks == ["hello", "hello world"]
    assert result.text == "hello world"
    assert result.provider == "parakeet"
    assert len(deleted_paths) == 1


def test_transcribe_streaming_handles_plain_text_and_errors(
    monkeypatch,
    sample_audio_bytes,
    fake_parakeet_module,
):
    """Streaming mode should support non-dict results and wrap provider errors."""
    _calls, module = fake_parakeet_module

    monkeypatch.setattr(ParakeetProvider, "_is_apple_silicon", lambda self: True)
    monkeypatch.setattr("whisper_hud.encryption.secure_delete", lambda _path: None)

    class RawResult:
        def __str__(self):
            return "raw transcript"

    seen_chunks = []
    module.transcribe = lambda _path, **_kwargs: RawResult()
    result = ParakeetProvider().transcribe_streaming(sample_audio_bytes, seen_chunks.append)

    assert seen_chunks == ["raw transcript"]
    assert result.text == "raw transcript"

    module.transcribe = lambda _path, **_kwargs: (_ for _ in ()).throw(Exception("stream blew up"))
    with pytest.raises(RuntimeError, match="Parakeet streaming transcription failed: stream blew up"):
        ParakeetProvider().transcribe_streaming(sample_audio_bytes, lambda _chunk: None)


def test_transcribe_streaming_requires_apple_silicon(sample_audio_bytes, monkeypatch):
    """Streaming mode should reject unsupported platforms immediately."""
    monkeypatch.setattr(ParakeetProvider, "_is_apple_silicon", lambda self: False)

    with pytest.raises(RuntimeError, match="Parakeet requires Apple Silicon"):
        ParakeetProvider().transcribe_streaming(sample_audio_bytes, lambda _chunk: None)


def test_platform_helpers_and_availability_messages(monkeypatch):
    """Static helper messaging should match platform and install state."""
    monkeypatch.setattr("whisper_hud.providers.parakeet.platform.system", lambda: "Linux")
    assert ParakeetProvider.is_apple_silicon() is False
    assert ParakeetProvider.get_availability_message() == "Parakeet requires macOS"

    monkeypatch.setattr("whisper_hud.providers.parakeet.platform.system", lambda: "Darwin")
    monkeypatch.setattr("whisper_hud.providers.parakeet.platform.machine", lambda: "x86_64")
    assert ParakeetProvider.is_apple_silicon() is False
    assert ParakeetProvider.get_availability_message() == "Parakeet requires Apple Silicon (M1/M2/M3/M4)"

    monkeypatch.setattr("whisper_hud.providers.parakeet.platform.machine", lambda: "arm64")
    monkeypatch.setattr("whisper_hud.providers.parakeet.importlib.util.find_spec", lambda _: None)
    assert ParakeetProvider.is_parakeet_installed() is False
    assert ParakeetProvider.get_availability_message() == "Install parakeet-mlx: pip install parakeet-mlx"

    monkeypatch.setattr("whisper_hud.providers.parakeet.importlib.util.find_spec", lambda _: object())
    assert ParakeetProvider.is_parakeet_installed() is True
    assert ParakeetProvider.get_availability_message() == "Parakeet is available"


def test_supported_languages_and_disk_space(monkeypatch):
    """Language metadata should be copied and disk checks should use a safety margin."""
    languages = ParakeetProvider.get_supported_languages()
    assert languages["en"] == "English"
    languages["en"] = "Mutated"
    assert ParakeetProvider.SUPPORTED_LANGUAGES["en"] == "English"

    monkeypatch.setattr(
        "whisper_hud.providers.parakeet.os.statvfs",
        lambda _path: SimpleNamespace(f_frsize=1024 * 1024, f_bavail=200),
    )
    assert ParakeetProvider.check_disk_space(100) == (True, 200.0)
    assert ParakeetProvider.check_disk_space(150) == (False, 200.0)

    def broken_statvfs(_path):
        raise OSError("unavailable")

    monkeypatch.setattr("whisper_hud.providers.parakeet.os.statvfs", broken_statvfs)
    assert ParakeetProvider.check_disk_space(100) == (False, 0.0)
