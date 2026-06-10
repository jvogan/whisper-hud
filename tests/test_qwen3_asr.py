"""Tests for the Qwen3-ASR local transcription provider.

All native/SDK packages (``qwen3_asr_mlx``, ``huggingface_hub``) are mocked;
the real packages are never imported, mirroring the Parakeet test patterns.
"""

from types import ModuleType, SimpleNamespace

import pytest

from whisper_hud.providers.qwen3_asr import Qwen3ASRProvider


class _FakeQwenModel:
    """Stand-in for the qwen3-asr-mlx model returned by Qwen3ASR.from_pretrained.

    Exposes ``transcribe(audio, ...)`` (the real 0.1.x entry point) and records
    every call. ``transcribe_fn`` lets individual tests customise the returned
    result/behaviour while keeping the same model surface.
    """

    def __init__(self, repo_id, calls, transcribe_fn=None):
        self.repo_id = repo_id
        self._calls = calls
        self._transcribe_fn = transcribe_fn

    def transcribe(self, audio, **kwargs):
        self._calls["transcribe"].append({"audio": audio, **kwargs})
        if self._transcribe_fn is not None:
            return self._transcribe_fn(audio, **kwargs)
        # Real package returns a dataclass with text/language/duration.
        return SimpleNamespace(text="  hola mundo  ", language="Spanish", duration=1.0)


@pytest.fixture
def fake_qwen_module(monkeypatch):
    """Install a minimal qwen3_asr_mlx module exposing Qwen3ASR.from_pretrained.

    ``calls`` tracks the repo ids passed to ``from_pretrained`` and the per-call
    kwargs passed to the model's ``transcribe``. Tests can swap the model's
    transcribe behaviour via ``module._set_transcribe_fn``.
    """

    calls = {"from_pretrained": [], "transcribe": []}
    module = ModuleType("qwen3_asr_mlx")
    state = {"transcribe_fn": None}

    class _Qwen3ASR:
        @staticmethod
        def from_pretrained(repo_id):
            calls["from_pretrained"].append(repo_id)
            return _FakeQwenModel(repo_id, calls, transcribe_fn=state["transcribe_fn"])

    module.Qwen3ASR = _Qwen3ASR
    # Expose a hook so tests can customise the model's transcribe behaviour.
    module._set_transcribe_fn = lambda fn: state.__setitem__("transcribe_fn", fn)
    monkeypatch.setitem(__import__("sys").modules, "qwen3_asr_mlx", module)

    return calls, module


@pytest.fixture
def fake_hf_module(monkeypatch):
    """Install a minimal huggingface_hub module for cache/download tests."""

    calls = {"cache": [], "download": []}
    module = ModuleType("huggingface_hub")

    def try_to_load_from_cache(repo_id, filename):
        calls["cache"].append((repo_id, filename))
        return "/tmp/cached-config.json"

    def snapshot_download(repo_id, **kwargs):
        calls["download"].append((repo_id, kwargs))
        return "/tmp/model-cache"

    module.try_to_load_from_cache = try_to_load_from_cache
    module.snapshot_download = snapshot_download
    monkeypatch.setitem(__import__("sys").modules, "huggingface_hub", module)

    return calls, module


# ---------------------------------------------------------------------------
# Identity / registry contract
# ---------------------------------------------------------------------------


def test_public_identifiers_match_registry_expectations():
    """The registry depends on these public identifiers staying stable."""
    assert Qwen3ASRProvider.name == "qwen3_asr"
    assert Qwen3ASRProvider.display_name == "Qwen3 ASR"
    assert Qwen3ASRProvider.DEFAULT_MODEL == "qwen3-asr-0.6b"
    assert set(Qwen3ASRProvider.MODELS) == {"qwen3-asr-0.6b", "qwen3-asr-1.7b"}
    # No-arg construction must work (manager builds menu metadata generically).
    assert Qwen3ASRProvider().get_current_model() == "qwen3-asr-0.6b"


# ---------------------------------------------------------------------------
# Availability gating
# ---------------------------------------------------------------------------


def test_provider_reports_unavailable_on_non_apple_silicon(monkeypatch):
    """Availability is false off Apple Silicon, before any package probe."""
    provider = Qwen3ASRProvider()
    monkeypatch.setattr(provider, "_is_apple_silicon", lambda: False)

    assert provider._check_availability() is False
    assert provider._available is False


def test_provider_reports_unavailable_when_package_not_installed(monkeypatch):
    """Availability is false when the package cannot be discovered."""
    provider = Qwen3ASRProvider()
    monkeypatch.setattr(provider, "_is_apple_silicon", lambda: True)
    monkeypatch.setattr("whisper_hud.providers.qwen3_asr.importlib.util.find_spec", lambda _: None)

    assert provider._check_availability() is False
    assert provider._available is False


def test_provider_reports_available_when_package_present(monkeypatch):
    """Availability is true on Apple Silicon with the package installed."""
    provider = Qwen3ASRProvider()
    monkeypatch.setattr(provider, "_is_apple_silicon", lambda: True)
    monkeypatch.setattr("whisper_hud.providers.qwen3_asr.importlib.util.find_spec", lambda _: object())

    assert provider._check_availability() is True
    assert provider._available is True


def test_is_configured_requires_platform_package_and_downloaded_model(monkeypatch):
    """Configured status depends on all three prerequisites."""
    provider = Qwen3ASRProvider()

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


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------


def test_load_model_caches_loaded_model(fake_qwen_module):
    """Model loading calls from_pretrained once with the repo id and caches it."""
    calls, _module = fake_qwen_module
    provider = Qwen3ASRProvider()

    first = provider._load_model()
    second = provider._load_model()

    assert first.repo_id == "mlx-community/Qwen3-ASR-0.6B-bf16"
    assert second is first
    assert calls["from_pretrained"] == ["mlx-community/Qwen3-ASR-0.6B-bf16"]


def test_model_loading_failure_raises_runtime_error(fake_qwen_module):
    """Loader failures are wrapped in a provider-specific RuntimeError."""
    _calls, module = fake_qwen_module

    class _Broken:
        @staticmethod
        def from_pretrained(_repo_id):
            raise ValueError("weights missing")

    module.Qwen3ASR = _Broken

    with pytest.raises(RuntimeError, match="Failed to load Qwen3-ASR model: weights missing"):
        Qwen3ASRProvider()._load_model()


def test_load_model_raises_when_package_missing(monkeypatch):
    """A missing qwen3_asr_mlx import raises a descriptive install error."""
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "qwen3_asr_mlx":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    with pytest.raises(RuntimeError, match=r"qwen3-asr-mlx not installed"):
        Qwen3ASRProvider()._load_model()


# ---------------------------------------------------------------------------
# Transcription happy path + temp-file cleanup
# ---------------------------------------------------------------------------


def test_successful_transcription_returns_text_and_language(monkeypatch, sample_audio_bytes, fake_qwen_module):
    """Successful transcriptions normalise text and report detected language."""
    calls, _module = fake_qwen_module
    deleted_paths = []
    temp_path = "/tmp/whisper_hud_qwen.wav"

    monkeypatch.setattr(Qwen3ASRProvider, "_is_apple_silicon", lambda self: True)
    monkeypatch.setattr(Qwen3ASRProvider, "_check_availability", lambda self: True)
    monkeypatch.setattr("whisper_hud.encryption.create_private_temp_file", lambda _data: temp_path)
    monkeypatch.setattr("whisper_hud.encryption.secure_delete", lambda path: deleted_paths.append(path))

    provider = Qwen3ASRProvider()
    result = provider.transcribe(sample_audio_bytes)

    assert result.text == "hola mundo"
    assert result.provider == "qwen3_asr"
    assert result.model == provider.model
    assert result.cost_estimate == 0.0
    assert result.language == "Spanish"
    assert result.duration_seconds >= 0
    # Model loaded via from_pretrained(repo_id), transcribed from a path.
    assert calls["from_pretrained"] == ["mlx-community/Qwen3-ASR-0.6B-bf16"]
    assert len(calls["transcribe"]) == 1
    assert calls["transcribe"][0]["audio"].endswith(".wav")
    # Temp file is securely deleted exactly once, after transcription.
    assert deleted_paths == [calls["transcribe"][0]["audio"]]


def test_unknown_language_is_normalised_to_none(monkeypatch, sample_audio_bytes, fake_qwen_module):
    """An 'Unknown' language from the package is surfaced as None."""
    _calls, module = fake_qwen_module
    module._set_transcribe_fn(lambda _audio, **_kw: SimpleNamespace(text="hi", language="Unknown", duration=0.5))

    monkeypatch.setattr(Qwen3ASRProvider, "_is_apple_silicon", lambda self: True)
    monkeypatch.setattr(Qwen3ASRProvider, "_check_availability", lambda self: True)
    monkeypatch.setattr("whisper_hud.encryption.create_private_temp_file", lambda _data: "/tmp/q.wav")
    monkeypatch.setattr("whisper_hud.encryption.secure_delete", lambda _path: None)

    result = Qwen3ASRProvider().transcribe(sample_audio_bytes)

    assert result.text == "hi"
    assert result.language is None


def test_dict_result_shape_is_supported(monkeypatch, sample_audio_bytes, fake_qwen_module):
    """A dict-style result (defensive) is parsed for text and language."""
    _calls, module = fake_qwen_module
    module._set_transcribe_fn(lambda _audio, **_kw: {"text": "  bonjour  ", "language": "French"})

    monkeypatch.setattr(Qwen3ASRProvider, "_is_apple_silicon", lambda self: True)
    monkeypatch.setattr(Qwen3ASRProvider, "_check_availability", lambda self: True)
    monkeypatch.setattr("whisper_hud.encryption.create_private_temp_file", lambda _data: "/tmp/q.wav")
    monkeypatch.setattr("whisper_hud.encryption.secure_delete", lambda _path: None)

    result = Qwen3ASRProvider().transcribe(sample_audio_bytes)

    assert result.text == "bonjour"
    assert result.language == "French"


def test_transcription_error_is_sanitised_and_cleans_up(monkeypatch, sample_audio_bytes, fake_qwen_module):
    """Transcription failures keep the provider prefix and still delete temp files."""
    _calls, module = fake_qwen_module
    deleted_paths = []
    temp_path = "/tmp/whisper_hud_qwen_error.wav"

    module._set_transcribe_fn(lambda _audio, **_kw: (_ for _ in ()).throw(Exception("decoder exploded")))
    monkeypatch.setattr(Qwen3ASRProvider, "_is_apple_silicon", lambda self: True)
    monkeypatch.setattr(Qwen3ASRProvider, "_check_availability", lambda self: True)
    monkeypatch.setattr("whisper_hud.encryption.create_private_temp_file", lambda _data: temp_path)
    monkeypatch.setattr("whisper_hud.encryption.secure_delete", lambda path: deleted_paths.append(path))

    with pytest.raises(RuntimeError, match="Qwen3 ASR transcription failed: decoder exploded"):
        Qwen3ASRProvider().transcribe(sample_audio_bytes)

    assert deleted_paths == [temp_path]


def test_transcribe_requires_apple_silicon(sample_audio_bytes, monkeypatch):
    """Non-Apple systems fail before any package work happens."""
    monkeypatch.setattr(Qwen3ASRProvider, "_is_apple_silicon", lambda self: False)

    with pytest.raises(RuntimeError, match="Qwen3 ASR requires Apple Silicon"):
        Qwen3ASRProvider().transcribe(sample_audio_bytes)


def test_transcribe_requires_installed_package(sample_audio_bytes, monkeypatch):
    """Missing qwen3_asr_mlx raises a descriptive install error."""
    monkeypatch.setattr(Qwen3ASRProvider, "_is_apple_silicon", lambda self: True)
    monkeypatch.setattr(Qwen3ASRProvider, "_check_availability", lambda self: False)

    with pytest.raises(RuntimeError, match="qwen3-asr-mlx is not installed"):
        Qwen3ASRProvider().transcribe(sample_audio_bytes)


# ---------------------------------------------------------------------------
# Vocabulary handling
# ---------------------------------------------------------------------------


def test_vocabulary_is_accepted_and_ignored(monkeypatch, sample_audio_bytes, fake_qwen_module):
    """qwen3-asr-mlx has no biasing mechanism: vocabulary is accepted and ignored."""
    calls, _module = fake_qwen_module
    monkeypatch.setattr(Qwen3ASRProvider, "_is_apple_silicon", lambda self: True)
    monkeypatch.setattr(Qwen3ASRProvider, "_check_availability", lambda self: True)
    monkeypatch.setattr("whisper_hud.encryption.create_private_temp_file", lambda _data: "/tmp/q.wav")
    monkeypatch.setattr("whisper_hud.encryption.secure_delete", lambda _path: None)

    result = Qwen3ASRProvider().transcribe(sample_audio_bytes, vocabulary=["Kubernetes", "Anthropic"])

    # Transcription still succeeds and no vocabulary artifact is forwarded.
    assert result.text == "hola mundo"
    assert len(calls["transcribe"]) == 1
    # model.transcribe was called with only the audio path (no biasing kwargs).
    assert set(calls["transcribe"][0]) == {"audio"}


# ---------------------------------------------------------------------------
# Download routing per model
# ---------------------------------------------------------------------------


def test_repo_id_resolution_for_both_models():
    """Repo ids must point at the mlx-community bf16 weights from_pretrained loads."""
    assert Qwen3ASRProvider._hf_repo_id("qwen3-asr-0.6b") == "mlx-community/Qwen3-ASR-0.6B-bf16"
    assert Qwen3ASRProvider._hf_repo_id("qwen3-asr-1.7b") == "mlx-community/Qwen3-ASR-1.7B-bf16"


def test_model_download_helpers_use_huggingface_cache(fake_hf_module):
    """Download checks probe the expected Hugging Face cache key per model."""
    calls, _module = fake_hf_module
    provider = Qwen3ASRProvider()

    assert provider.is_model_downloaded() is True
    assert provider._is_specific_model_downloaded("qwen3-asr-1.7b") is True
    assert calls["cache"] == [
        ("mlx-community/Qwen3-ASR-0.6B-bf16", "config.json"),
        ("mlx-community/Qwen3-ASR-1.7B-bf16", "config.json"),
    ]


def test_model_download_helpers_return_false_when_cache_lookup_fails(fake_hf_module):
    """Cache helper failures are treated as not-downloaded."""
    _calls, module = fake_hf_module

    def broken_cache(*_args, **_kwargs):
        raise RuntimeError("cache unavailable")

    module.try_to_load_from_cache = broken_cache
    provider = Qwen3ASRProvider()

    assert provider.is_model_downloaded() is False
    assert provider._is_specific_model_downloaded(provider.model) is False


def test_download_model_routes_default_model_to_bf16_repo(monkeypatch, fake_hf_module):
    """The default 0.6B download targets the 0.6B bf16 repo with progress updates."""
    calls, _module = fake_hf_module
    progress = []

    monkeypatch.setattr(Qwen3ASRProvider, "_is_apple_silicon", lambda self: True)

    assert Qwen3ASRProvider().download_model(lambda m, p: progress.append((m, p))) is True
    assert calls["download"][0][0] == "mlx-community/Qwen3-ASR-0.6B-bf16"
    assert progress == [
        ("Downloading Qwen3 ASR 0.6B (700MB)...", 0.0),
        ("Download complete!", 100.0),
    ]


def test_download_model_routes_large_model_to_bf16_repo(monkeypatch, fake_hf_module):
    """Selecting 1.7B downloads from the 1.7B bf16 repo with the right size note."""
    calls, _module = fake_hf_module
    progress = []

    provider = Qwen3ASRProvider(model="qwen3-asr-1.7b")
    monkeypatch.setattr(provider, "_is_apple_silicon", lambda: True)

    assert provider.download_model(lambda m, p: progress.append((m, p))) is True
    assert calls["download"][0][0] == "mlx-community/Qwen3-ASR-1.7B-bf16"
    assert progress[0] == ("Downloading Qwen3 ASR 1.7B (1800MB)...", 0.0)


def test_download_model_handles_platform_and_dependency_failures(monkeypatch, fake_hf_module):
    """Download helper fails cleanly for unsupported hosts and missing hub."""
    progress = []
    provider = Qwen3ASRProvider()

    monkeypatch.setattr(provider, "_is_apple_silicon", lambda: False)
    assert provider.download_model(lambda m, p: progress.append((m, p))) is False
    assert progress == [("Error: Qwen3 ASR requires Apple Silicon", 0.0)]

    progress.clear()
    monkeypatch.setattr(provider, "_is_apple_silicon", lambda: True)
    real_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "huggingface_hub":
            raise ImportError("missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)
    assert provider.download_model(lambda m, p: progress.append((m, p))) is False
    assert progress == [("Error: huggingface_hub not installed", 0.0)]


def test_download_model_reports_runtime_failure(monkeypatch, fake_hf_module):
    """Unexpected hub failures are surfaced through the progress callback."""
    _calls, module = fake_hf_module
    progress = []

    def broken_download(*_args, **_kwargs):
        raise RuntimeError("no space left")

    module.snapshot_download = broken_download
    monkeypatch.setattr(Qwen3ASRProvider, "_is_apple_silicon", lambda self: True)

    assert Qwen3ASRProvider().download_model(lambda m, p: progress.append((m, p))) is False
    assert progress == [
        ("Downloading Qwen3 ASR 0.6B (700MB)...", 0.0),
        ("Error: no space left", 0.0),
    ]


# ---------------------------------------------------------------------------
# Model getters / setters / metadata
# ---------------------------------------------------------------------------


def test_get_models_lists_both_models_with_metadata(monkeypatch):
    """get_models returns both models with download state and recommendation."""
    monkeypatch.setattr(Qwen3ASRProvider, "_is_specific_model_downloaded", lambda self, _m: False)
    provider = Qwen3ASRProvider()

    models = provider.get_models()
    by_id = {m["id"]: m for m in models}

    assert set(by_id) == {"qwen3-asr-0.6b", "qwen3-asr-1.7b"}
    assert by_id["qwen3-asr-0.6b"]["recommended"] is True
    assert by_id["qwen3-asr-0.6b"]["cost_per_minute"] == 0.0
    assert by_id["qwen3-asr-0.6b"]["downloaded"] is False
    assert by_id["qwen3-asr-1.7b"]["recommended"] is False
    assert "52" in by_id["qwen3-asr-1.7b"]["languages"]


def test_set_model_and_get_current_model(fake_qwen_module):
    """set_model switches valid ids, resets the cached handle, ignores junk."""
    provider = Qwen3ASRProvider()
    assert provider.get_current_model() == "qwen3-asr-0.6b"
    assert provider.get_download_size() == 700.0

    # Selecting the same model keeps the cached handle.
    sentinel = object()
    provider._qwen_model = sentinel
    provider.set_model("qwen3-asr-0.6b")
    assert provider._qwen_model is sentinel

    # Switching to a different valid model resets the cached handle.
    provider.set_model("qwen3-asr-1.7b")
    assert provider.get_current_model() == "qwen3-asr-1.7b"
    assert provider._qwen_model is None
    assert provider.get_download_size() == 1800.0

    # Unknown ids are ignored.
    provider._qwen_model = sentinel
    provider.set_model("not-a-real-model")
    assert provider.get_current_model() == "qwen3-asr-1.7b"
    assert provider._qwen_model is sentinel


def test_constructor_falls_back_to_default_for_unknown_model():
    """Unknown / missing constructor models fall back to the default."""
    assert Qwen3ASRProvider(model="bogus").get_current_model() == "qwen3-asr-0.6b"
    assert Qwen3ASRProvider().get_current_model() == "qwen3-asr-0.6b"
    assert Qwen3ASRProvider(model="qwen3-asr-1.7b").get_current_model() == "qwen3-asr-1.7b"


# ---------------------------------------------------------------------------
# Static platform helpers / availability messaging / disk space
# ---------------------------------------------------------------------------


def test_platform_helpers_and_availability_messages(monkeypatch):
    """Static helper messaging matches platform and install state."""
    monkeypatch.setattr("whisper_hud.providers.qwen3_asr.platform.system", lambda: "Linux")
    assert Qwen3ASRProvider.is_apple_silicon() is False
    assert Qwen3ASRProvider.get_availability_message() == "Qwen3 ASR requires macOS"

    monkeypatch.setattr("whisper_hud.providers.qwen3_asr.platform.system", lambda: "Darwin")
    monkeypatch.setattr("whisper_hud.providers.qwen3_asr.platform.machine", lambda: "x86_64")
    assert Qwen3ASRProvider.is_apple_silicon() is False
    assert Qwen3ASRProvider.get_availability_message() == "Qwen3 ASR requires Apple Silicon (M1/M2/M3/M4)"

    monkeypatch.setattr("whisper_hud.providers.qwen3_asr.platform.machine", lambda: "arm64")
    monkeypatch.setattr("whisper_hud.providers.qwen3_asr.importlib.util.find_spec", lambda _: None)
    assert Qwen3ASRProvider.is_qwen3_asr_installed() is False
    msg = Qwen3ASRProvider.get_availability_message()
    assert "pip install 'whisper-hud[qwen3-asr]'" in msg

    monkeypatch.setattr("whisper_hud.providers.qwen3_asr.importlib.util.find_spec", lambda _: object())
    assert Qwen3ASRProvider.is_qwen3_asr_installed() is True
    assert Qwen3ASRProvider.get_availability_message() == "Qwen3 ASR is available"


def test_check_disk_space_uses_safety_margin(monkeypatch):
    """Disk checks apply a 1.5x safety margin and fail closed on errors."""
    monkeypatch.setattr(
        "whisper_hud.providers.qwen3_asr.os.statvfs",
        lambda _path: SimpleNamespace(f_frsize=1024 * 1024, f_bavail=2000),
    )
    assert Qwen3ASRProvider.check_disk_space(1000) == (True, 2000.0)
    assert Qwen3ASRProvider.check_disk_space(1500) == (False, 2000.0)

    def broken_statvfs(_path):
        raise OSError("unavailable")

    monkeypatch.setattr("whisper_hud.providers.qwen3_asr.os.statvfs", broken_statvfs)
    assert Qwen3ASRProvider.check_disk_space(100) == (False, 0.0)
