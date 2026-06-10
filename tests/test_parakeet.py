"""Tests for the Parakeet transcription provider."""

import threading
from types import ModuleType, SimpleNamespace

import pytest

from whisper_hud.providers.parakeet import ParakeetLiveSession, ParakeetProvider


class _FakeBatchModel:
    """Stand-in for the parakeet-mlx 0.5.x model returned by from_pretrained.

    Exposes ``transcribe(audio_path)`` (the real 0.5.x batch entry point) and
    records each call. ``transcribe_fn`` lets individual tests customize the
    returned result/behavior while keeping the same model surface.
    """

    def __init__(self, repo_id, calls, transcribe_fn=None):
        self.repo_id = repo_id
        self._calls = calls
        self._transcribe_fn = transcribe_fn

    def transcribe(self, path, **kwargs):
        self._calls["transcribe"].append({"path": path, **kwargs})
        if self._transcribe_fn is not None:
            return self._transcribe_fn(path, **kwargs)
        return {"text": "  hello from parakeet  "}


@pytest.fixture
def fake_parakeet_module(monkeypatch):
    """Install a minimal parakeet_mlx module exposing the 0.5.x from_pretrained API.

    parakeet-mlx 0.5.x exports ``from_pretrained(repo_id)`` (returning a model
    object with ``.transcribe(path)``) and NOT module-level ``load_model`` /
    ``transcribe``. The fixture mirrors that: ``calls`` tracks the repo ids
    passed to ``from_pretrained`` and the per-call kwargs passed to the model's
    ``transcribe``. Tests can swap behavior via ``module._transcribe_fn``.
    """

    calls = {"from_pretrained": [], "transcribe": []}
    module = ModuleType("parakeet_mlx")
    state = {"transcribe_fn": None}

    def from_pretrained(repo_id):
        calls["from_pretrained"].append(repo_id)
        return _FakeBatchModel(repo_id, calls, transcribe_fn=state["transcribe_fn"])

    module.from_pretrained = from_pretrained
    # Expose a hook so tests can customize the model's transcribe behavior.
    module._set_transcribe_fn = lambda fn: state.__setitem__("transcribe_fn", fn)
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
    """Model loading should call from_pretrained once with the repo id and cache it."""
    calls, _module = fake_parakeet_module
    provider = ParakeetProvider()

    first = provider._load_model()
    second = provider._load_model()

    # from_pretrained is invoked with the resolved mlx-community repo id, once.
    assert first.repo_id == f"mlx-community/{provider.model}"
    assert second is first
    assert calls["from_pretrained"] == [f"mlx-community/{provider.model}"]


def test_model_loading_failure_raises_runtime_error(monkeypatch, fake_parakeet_module):
    """Loader failures should be wrapped in a provider-specific RuntimeError."""
    _calls, module = fake_parakeet_module

    def broken_from_pretrained(_repo_id):
        raise ValueError("weights missing")

    module.from_pretrained = broken_from_pretrained

    with pytest.raises(RuntimeError, match="Failed to load Parakeet model: weights missing"):
        ParakeetProvider()._load_model()


def test_successful_transcription_returns_correct_text(monkeypatch, sample_audio_bytes, fake_parakeet_module):
    """Successful transcriptions should normalize text and return metadata."""
    calls, _module = fake_parakeet_module
    deleted_paths = []
    temp_path = "/tmp/whisper_hud_parakeet.wav"

    monkeypatch.setattr(ParakeetProvider, "_is_apple_silicon", lambda self: True)
    monkeypatch.setattr(ParakeetProvider, "_check_availability", lambda self: True)
    monkeypatch.setattr("whisper_hud.encryption.create_private_temp_file", lambda _data: temp_path)
    monkeypatch.setattr("whisper_hud.encryption.secure_delete", lambda path: deleted_paths.append(path))

    provider = ParakeetProvider()
    result = provider.transcribe(sample_audio_bytes)

    assert result.text == "hello from parakeet"
    assert result.provider == "parakeet"
    assert result.model == provider.model
    assert result.cost_estimate == 0.0
    assert result.language is None
    assert result.duration_seconds >= 0
    # 0.5.x: model loaded via from_pretrained(repo_id), transcribed from a path.
    assert calls["from_pretrained"] == [f"mlx-community/{provider.model}"]
    assert len(calls["transcribe"]) == 1
    assert calls["transcribe"][0]["path"].endswith(".wav")
    assert deleted_paths == [calls["transcribe"][0]["path"]]


def test_transcription_error_propagates_correctly(monkeypatch, sample_audio_bytes, fake_parakeet_module):
    """Transcription failures should keep the provider error prefix."""
    _calls, module = fake_parakeet_module
    deleted_paths = []
    temp_path = "/tmp/whisper_hud_parakeet_error.wav"

    def broken_transcribe(_path, **_kwargs):
        raise Exception("decoder exploded")

    module._set_transcribe_fn(broken_transcribe)
    monkeypatch.setattr(ParakeetProvider, "_is_apple_silicon", lambda self: True)
    monkeypatch.setattr(ParakeetProvider, "_check_availability", lambda self: True)
    monkeypatch.setattr("whisper_hud.encryption.create_private_temp_file", lambda _data: temp_path)
    monkeypatch.setattr("whisper_hud.encryption.secure_delete", lambda path: deleted_paths.append(path))

    with pytest.raises(RuntimeError, match="Parakeet transcription failed: decoder exploded"):
        ParakeetProvider().transcribe(sample_audio_bytes)

    assert len(deleted_paths) == 1
    assert deleted_paths[0].endswith(".wav")


def test_vocabulary_is_accepted_and_ignored(monkeypatch, sample_audio_bytes, fake_parakeet_module):
    """Parakeet has no biasing mechanism: vocabulary is accepted and silently ignored."""
    calls, _module = fake_parakeet_module
    monkeypatch.setattr(ParakeetProvider, "_is_apple_silicon", lambda self: True)
    monkeypatch.setattr(ParakeetProvider, "_check_availability", lambda self: True)
    monkeypatch.setattr("whisper_hud.encryption.create_private_temp_file", lambda _data: "/tmp/p.wav")
    monkeypatch.setattr("whisper_hud.encryption.secure_delete", lambda _path: None)

    result = ParakeetProvider().transcribe(sample_audio_bytes, vocabulary=["Kubernetes", "Anthropic"])

    # Transcription still succeeds and no vocabulary artifact is forwarded to the model.
    assert result.text == "hello from parakeet"
    assert len(calls["transcribe"]) == 1
    # model.transcribe was called with only the path (no prompt/vocabulary kwargs).
    assert set(calls["transcribe"][0]) == {"path"}


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
        (f"mlx-community/{provider.model}", "config.json"),
        ("mlx-community/parakeet-tdt-0.6b-v3", "config.json"),
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
    assert calls["download"][0][0] == "mlx-community/parakeet-tdt-0.6b-v3"
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
    temp_path = "/tmp/whisper_hud_parakeet_stream.wav"

    def streaming_transcribe(path, **kwargs):
        return {
            "text": "hello world",
            "words": [{"word": "hello"}, {"word": "world"}],
        }

    module._set_transcribe_fn(streaming_transcribe)
    monkeypatch.setattr(ParakeetProvider, "_is_apple_silicon", lambda self: True)
    monkeypatch.setattr("whisper_hud.encryption.create_private_temp_file", lambda _data: temp_path)
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
    temp_path = "/tmp/whisper_hud_parakeet_stream_error.wav"

    monkeypatch.setattr(ParakeetProvider, "_is_apple_silicon", lambda self: True)
    monkeypatch.setattr("whisper_hud.encryption.create_private_temp_file", lambda _data: temp_path)
    monkeypatch.setattr("whisper_hud.encryption.secure_delete", lambda _path: None)

    class RawResult:
        def __str__(self):
            return "raw transcript"

    seen_chunks = []
    module._set_transcribe_fn(lambda _path, **_kwargs: RawResult())
    result = ParakeetProvider().transcribe_streaming(sample_audio_bytes, seen_chunks.append)

    assert seen_chunks == ["raw transcript"]
    assert result.text == "raw transcript"

    module._set_transcribe_fn(lambda _path, **_kwargs: (_ for _ in ()).throw(Exception("stream blew up")))
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


# ---------------------------------------------------------------------------
# v2 model + repo-id resolution
# ---------------------------------------------------------------------------


def test_v2_model_is_listed_and_selectable():
    """The English-only v2 model should be available and switchable."""
    provider = ParakeetProvider()

    # v3 stays the default (multilingual-safe) and recommended.
    assert provider.get_current_model() == "parakeet-tdt-0.6b-v3"
    assert provider.DEFAULT_MODEL == "parakeet-tdt-0.6b-v3"

    model_ids = [m["id"] for m in provider.get_models()]
    assert "parakeet-tdt-0.6b-v2" in model_ids
    assert "parakeet-tdt-0.6b-v3" in model_ids

    v2 = next(m for m in provider.get_models() if m["id"] == "parakeet-tdt-0.6b-v2")
    assert v2["languages"] == "en"
    assert v2["recommended"] is False
    assert "English" in v2["description"]

    # v2 can be constructed directly and selected at runtime.
    assert ParakeetProvider(model="parakeet-tdt-0.6b-v2").get_current_model() == "parakeet-tdt-0.6b-v2"

    provider.set_model("parakeet-tdt-0.6b-v2")
    assert provider.get_current_model() == "parakeet-tdt-0.6b-v2"


def test_repo_id_resolution_for_v2_and_v3():
    """Repo ids must point at the mlx-community weights from_pretrained loads."""
    assert ParakeetProvider._hf_repo_id("parakeet-tdt-0.6b-v3") == "mlx-community/parakeet-tdt-0.6b-v3"
    assert ParakeetProvider._hf_repo_id("parakeet-tdt-0.6b-v2") == "mlx-community/parakeet-tdt-0.6b-v2"


def test_cache_and_download_use_mlx_community_repo_for_v2(monkeypatch, fake_hf_module):
    """v2 cache checks and downloads should target the mlx-community repo id."""
    calls, _module = fake_hf_module
    provider = ParakeetProvider(model="parakeet-tdt-0.6b-v2")

    monkeypatch.setattr(provider, "_is_apple_silicon", lambda: True)

    assert provider.is_model_downloaded() is True
    assert provider._is_specific_model_downloaded("parakeet-tdt-0.6b-v2") is True
    assert provider.download_model() is True

    assert calls["cache"] == [
        ("mlx-community/parakeet-tdt-0.6b-v2", "config.json"),
        ("mlx-community/parakeet-tdt-0.6b-v2", "config.json"),
    ]
    assert calls["download"][0][0] == "mlx-community/parakeet-tdt-0.6b-v2"


# ---------------------------------------------------------------------------
# Live streaming session
# ---------------------------------------------------------------------------


class _FakeStreamingParakeet:
    """Stand-in for parakeet_mlx.StreamingParakeet used by the live session."""

    def __init__(self):
        self.added = []
        self.entered = False
        self.exited = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.exited = True
        return False

    def add_audio(self, audio):
        self.added.append(audio)

    @property
    def result(self):
        # Transcript grows with the number of audio chunks consumed so that
        # partials and the final transcript differ deterministically.
        return SimpleNamespace(text=f"  chunk-{len(self.added)}  ")


class _FakeStreamingModel:
    def __init__(self):
        self.stream = _FakeStreamingParakeet()
        self.stream_kwargs = None

    def transcribe_stream(self, **kwargs):
        self.stream_kwargs = kwargs
        return self.stream


@pytest.fixture
def fake_mlx_module(monkeypatch):
    """Install a minimal mlx.core module exposing array()."""
    mlx_pkg = ModuleType("mlx")
    mlx_core = ModuleType("mlx.core")

    def array(value):
        # Pass the numpy chunk straight through; the fake stream just counts it.
        return value

    mlx_core.array = array
    mlx_pkg.core = mlx_core
    sys_modules = __import__("sys").modules
    monkeypatch.setitem(sys_modules, "mlx", mlx_pkg)
    monkeypatch.setitem(sys_modules, "mlx.core", mlx_core)
    return mlx_core


def _make_live_session(model, **overrides):
    """Build a ParakeetLiveSession wired to the given fake model."""
    events = {
        "ready": threading.Event(),
        "final": threading.Event(),
        "error": threading.Event(),
    }
    captured = {"partials": [], "final": None, "error": None}

    def on_partial(text):
        captured["partials"].append(text)

    def on_final(result):
        captured["final"] = result
        events["final"].set()

    def on_error(exc):
        captured["error"] = exc
        events["error"].set()

    def on_ready():
        events["ready"].set()

    kwargs = dict(
        model_loader=lambda: model,
        provider_name="parakeet",
        model_id="parakeet-tdt-0.6b-v3",
        on_partial=on_partial,
        on_final=on_final,
        on_error=on_error,
        on_ready=on_ready,
        language=None,
    )
    kwargs.update(overrides)
    session = ParakeetLiveSession(**kwargs)
    return session, events, captured


def test_live_session_lifecycle_start_push_partial_stop_final(fake_mlx_module):
    """A full live turn should emit partials then a final transcript."""
    import numpy as np

    model = _FakeStreamingModel()
    session, events, captured = _make_live_session(model)

    session.start()
    assert events["ready"].wait(timeout=2.0), "session never became ready"
    assert session.is_ready() is True
    # The streaming context must have been entered with the configured window.
    assert model.stream.entered is True
    assert model.stream_kwargs == {"context_size": (256, 256), "depth": 1}

    # Feed two chunks of 16 kHz float32 mono audio.
    chunk = np.zeros(1600, dtype=np.float32)
    session.push_audio(chunk, 16000)
    session.push_audio(chunk, 16000)

    session.request_stop()
    assert events["final"].wait(timeout=2.0), "final transcript never arrived"

    # Audio was forwarded to the stream and a final result was produced.
    assert len(model.stream.added) == 2
    assert captured["partials"], "expected at least one partial"
    assert all(p.startswith("chunk-") for p in captured["partials"])

    result = captured["final"]
    assert result is not None
    assert result.text == "chunk-2"  # stripped, reflects both chunks
    assert result.provider == "parakeet"
    assert result.model == "parakeet-tdt-0.6b-v3"
    assert result.cost_estimate == 0.0
    assert result.language is None
    # duration tracks fed audio: 2 * 1600 / 16000 = 0.2s
    assert result.duration_seconds == pytest.approx(0.2)
    assert captured["error"] is None

    session.close()
    assert model.stream.exited is True


def test_live_session_resamples_non_16k_audio(fake_mlx_module):
    """Audio at a non-native rate should be resampled before reaching the model."""
    import numpy as np

    model = _FakeStreamingModel()
    session, events, captured = _make_live_session(model)

    session.start()
    assert events["ready"].wait(timeout=2.0)

    # 48 kHz, two channels -> mono 16 kHz. 4800 frames at 48k == 0.1s.
    chunk = np.zeros((4800, 2), dtype=np.float32)
    session.push_audio(chunk, 48000)
    session.request_stop()
    assert events["final"].wait(timeout=2.0)

    forwarded = model.stream.added[0]
    # Down to ~1600 samples (0.1s at 16 kHz), 1D mono float32.
    assert forwarded.ndim == 1
    assert forwarded.dtype == np.float32
    assert abs(len(forwarded) - 1600) <= 4
    assert captured["final"].duration_seconds == pytest.approx(0.1, abs=0.01)


def test_live_session_close_without_stop_emits_no_final(fake_mlx_module):
    """Aborting via close() should not deliver a final transcript."""
    import numpy as np

    model = _FakeStreamingModel()
    session, events, captured = _make_live_session(model)

    session.start()
    assert events["ready"].wait(timeout=2.0)

    session.push_audio(np.zeros(1600, dtype=np.float32), 16000)
    session.close()

    # No graceful stop was requested, so no final result is delivered.
    assert events["final"].wait(timeout=0.5) is False
    assert captured["final"] is None
    assert model.stream.exited is True


def test_live_session_reports_loader_failure(fake_mlx_module):
    """A model-load failure should surface through the error callback."""

    def broken_loader():
        raise RuntimeError("weights missing")

    session, events, captured = _make_live_session(model=None, model_loader=broken_loader)

    session.start()
    assert events["error"].wait(timeout=2.0), "error was never reported"
    assert isinstance(captured["error"], RuntimeError)
    assert "Parakeet live transcription failed" in str(captured["error"])
    assert "weights missing" in str(captured["error"])
    assert captured["final"] is None


def test_push_audio_is_ignored_after_stop(fake_mlx_module):
    """Audio pushed after a stop request must not be forwarded."""
    import numpy as np

    model = _FakeStreamingModel()
    session, events, captured = _make_live_session(model)

    session.start()
    assert events["ready"].wait(timeout=2.0)

    session.request_stop()
    assert events["final"].wait(timeout=2.0)

    pushed_before = len(model.stream.added)
    session.push_audio(np.ones(1600, dtype=np.float32), 16000)
    assert len(model.stream.added) == pushed_before


# ---------------------------------------------------------------------------
# Live session availability / configuration gating
# ---------------------------------------------------------------------------


def _noop_callbacks():
    return dict(
        on_partial=lambda _t: None,
        on_final=lambda _r: None,
        on_error=lambda _e: None,
    )


def test_supports_live_input_tracks_configuration(monkeypatch):
    """Live input is offered only when the provider is fully configured."""
    provider = ParakeetProvider()

    monkeypatch.setattr(provider, "_is_apple_silicon", lambda: True)
    monkeypatch.setattr(provider, "_check_availability", lambda: True)
    monkeypatch.setattr(provider, "is_model_downloaded", lambda: True)
    assert provider.supports_live_input() is True

    monkeypatch.setattr(provider, "is_model_downloaded", lambda: False)
    assert provider.supports_live_input() is False


def test_create_live_session_raises_when_not_configured(monkeypatch):
    """create_live_session must refuse when prerequisites are missing."""
    provider = ParakeetProvider()
    monkeypatch.setattr(provider, "is_configured", lambda: False)

    with pytest.raises(RuntimeError, match="Parakeet live transcription is unavailable"):
        provider.create_live_session(**_noop_callbacks())


def test_create_live_session_returns_session_when_configured(monkeypatch):
    """A configured provider should hand back a startable live session."""
    provider = ParakeetProvider()
    monkeypatch.setattr(provider, "is_configured", lambda: True)
    # Avoid touching the real loader; we only check the object is constructed.
    monkeypatch.setattr(provider, "_load_streaming_model", lambda: _FakeStreamingModel())

    session = provider.create_live_session(**_noop_callbacks())
    assert isinstance(session, ParakeetLiveSession)


def test_load_streaming_model_prefers_from_pretrained(monkeypatch):
    """Streaming should load weights via from_pretrained with the resolved id."""
    module = ModuleType("parakeet_mlx")
    seen = {}

    def from_pretrained(repo_id):
        seen["repo_id"] = repo_id
        return "streaming-model"

    module.from_pretrained = from_pretrained
    monkeypatch.setitem(__import__("sys").modules, "parakeet_mlx", module)

    provider = ParakeetProvider(model="parakeet-tdt-0.6b-v2")
    assert provider._load_streaming_model() == "streaming-model"
    assert seen["repo_id"] == "mlx-community/parakeet-tdt-0.6b-v2"
