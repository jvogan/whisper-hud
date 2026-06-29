"""Tests for the Apple Speech (Advanced) SpeechAnalyzer provider.

All tests mock the bundled Swift helper subprocess — the real
``whisperhud-speechanalyzer`` binary is never invoked. This mirrors the
subprocess-mocking style of ``test_apple_translate.py``.
"""

import json
import subprocess
import sys

import pytest

from whisper_hud.providers.apple_speechanalyzer import (
    AppleSpeechAnalyzerProvider,
    _parse_macos_major,
)

# --- fake subprocess plumbing -------------------------------------------------


class _FakeCompletedProc:
    """Stand-in for subprocess.Popen that records input and replays canned IO.

    ``communicate`` returns the configured ``(stdout, stderr)`` and records the
    request payload the provider wrote to stdin, so tests can assert on the JSON
    request (locale, vocabulary, audio_path) without touching a real process.
    """

    def __init__(self, *, stdout="", stderr="", returncode=0, timeout_first=False):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self._timeout_first = timeout_first
        self.sent_input = None
        self.killed = False
        self._communicate_calls = 0

    def communicate(self, input=None, timeout=None):  # noqa: A002 - match stdlib signature
        self._communicate_calls += 1
        if input is not None:
            self.sent_input = input
        if self._timeout_first and self._communicate_calls == 1:
            raise subprocess.TimeoutExpired(cmd="helper", timeout=timeout)
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True


@pytest.fixture
def patch_helper_subprocess(monkeypatch):
    """Patch Popen + temp-file helpers so transcribe() never spawns a real proc.

    Returns a callable ``install(fake_proc)`` that wires the given fake process
    in and yields a ``state`` dict capturing the temp file lifecycle and the
    Popen argv used.
    """
    state = {"created": [], "deleted": [], "argv": None, "proc": None}

    def install(fake_proc):
        state["proc"] = fake_proc

        def fake_popen(argv, **kwargs):
            state["argv"] = argv
            return fake_proc

        monkeypatch.setattr("whisper_hud.providers.apple_speechanalyzer.subprocess.Popen", fake_popen)

        def fake_create_temp(data, **kwargs):
            path = "/tmp/whisper_hud_speechanalyzer_test.wav"
            state["created"].append((path, data))
            return path

        def fake_secure_delete(path):
            state["deleted"].append(path)
            return True

        # The provider imports these lazily from ..encryption inside transcribe().
        monkeypatch.setattr("whisper_hud.encryption.create_private_temp_file", fake_create_temp)
        monkeypatch.setattr("whisper_hud.encryption.secure_delete", fake_secure_delete)
        return state

    return install


def _force_ready(monkeypatch):
    """Make the provider report macOS 26+ and a present, runnable helper."""
    monkeypatch.setattr(AppleSpeechAnalyzerProvider, "_is_supported_macos", staticmethod(lambda: True))
    monkeypatch.setattr(AppleSpeechAnalyzerProvider, "_helper_available", lambda self: True)


# --- macOS version parsing ----------------------------------------------------


@pytest.mark.parametrize(
    "version,expected",
    [
        ("26.5.1", 26),
        ("26.0", 26),
        ("26", 26),
        ("15.4", 15),
        ("", None),
        ("   ", None),
        ("not-a-version", None),
        (".5", None),
    ],
)
def test_parse_macos_major(version, expected):
    assert _parse_macos_major(version) == expected


# --- helper discovery (mirrors AppleTranslateProvider) ------------------------


def test_helper_path_ignores_untrusted_override(monkeypatch):
    """Overrides outside the repo-controlled bin directory are rejected."""
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setenv("WHISPERHUD_SPEECHANALYZER_HELPER", "/tmp/evil-helper")

    assert AppleSpeechAnalyzerProvider._helper_path() == AppleSpeechAnalyzerProvider._source_helper_path()


def test_helper_path_accepts_repo_local_override(monkeypatch):
    """Repo-local overrides remain available for development workflows."""
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    allowed_dir = AppleSpeechAnalyzerProvider._source_helper_path().parent
    override = allowed_dir / "custom-speechanalyzer"
    monkeypatch.setenv("WHISPERHUD_SPEECHANALYZER_HELPER", str(override))

    assert AppleSpeechAnalyzerProvider._helper_path() == override.resolve()


def test_source_helper_path_points_at_bin_dir():
    """The source helper lives at whisper-hud/bin/whisperhud-speechanalyzer."""
    path = AppleSpeechAnalyzerProvider._source_helper_path()
    assert path.parent.name == "bin"
    assert path.name == "whisperhud-speechanalyzer"


# --- public identifiers preserved from the stub -------------------------------


def test_public_identifiers_preserved():
    provider = AppleSpeechAnalyzerProvider()
    assert provider.name == "apple_analyzer"
    assert provider.display_name == "Apple Speech (Advanced)"
    assert "system" in provider.MODELS
    assert provider.DEFAULT_MODEL == "system"
    assert provider.get_current_model() == "system"


def test_get_models_shape():
    provider = AppleSpeechAnalyzerProvider()
    models = provider.get_models()
    assert len(models) == 1
    model = models[0]
    assert model["id"] == "system"
    assert model["cost_per_minute"] == 0.0
    assert model["recommended"] is True


def test_set_model_ignores_unknown():
    provider = AppleSpeechAnalyzerProvider()
    provider.set_model("does-not-exist")
    assert provider.get_current_model() == "system"


def test_init_falls_back_to_default_model_for_unknown():
    provider = AppleSpeechAnalyzerProvider(model="bogus")
    assert provider.model == "system"


# --- version / availability gating --------------------------------------------


def test_is_configured_false_on_non_macos(monkeypatch):
    monkeypatch.setattr("whisper_hud.providers.apple_speechanalyzer.platform.system", lambda: "Linux")
    assert AppleSpeechAnalyzerProvider().is_configured() is False


def test_is_configured_false_on_old_macos(monkeypatch):
    monkeypatch.setattr("whisper_hud.providers.apple_speechanalyzer.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "whisper_hud.providers.apple_speechanalyzer.platform.mac_ver",
        lambda: ("15.4", ("", "", ""), "arm64"),
    )
    assert AppleSpeechAnalyzerProvider().is_configured() is False


def test_is_configured_false_when_helper_missing(monkeypatch):
    monkeypatch.setattr(AppleSpeechAnalyzerProvider, "_is_supported_macos", staticmethod(lambda: True))
    monkeypatch.setattr(AppleSpeechAnalyzerProvider, "_helper_available", lambda self: False)
    assert AppleSpeechAnalyzerProvider().is_configured() is False


def test_is_configured_true_when_supported_and_helper_present(monkeypatch):
    _force_ready(monkeypatch)
    assert AppleSpeechAnalyzerProvider().is_configured() is True


# --- transcribe happy path ----------------------------------------------------


def test_transcribe_parses_final_event(monkeypatch, patch_helper_subprocess, sample_audio_bytes):
    _force_ready(monkeypatch)
    monkeypatch.setattr(AppleSpeechAnalyzerProvider, "_resolve_locale", lambda self: "en-US")

    stdout = "\n".join(
        [
            json.dumps({"type": "partial", "text": "Hello"}),
            json.dumps({"type": "partial", "text": "Hello world"}),
            json.dumps({"type": "final", "text": "Hello world, this is a test.", "locale": "en-US"}),
        ]
    )
    fake = _FakeCompletedProc(stdout=stdout, returncode=0)
    state = patch_helper_subprocess(fake)

    result = AppleSpeechAnalyzerProvider().transcribe(sample_audio_bytes)

    assert result.text == "Hello world, this is a test."
    assert result.provider == "apple_analyzer"
    assert result.model == "system"
    assert result.cost_estimate == 0.0
    assert result.language == "en"
    # The audio temp file is created and then securely deleted.
    assert state["created"], "expected a private temp file to be created"
    assert state["deleted"] == ["/tmp/whisper_hud_speechanalyzer_test.wav"]


def test_transcribe_sends_locale_and_audio_path_in_request(monkeypatch, patch_helper_subprocess, sample_audio_bytes):
    _force_ready(monkeypatch)
    monkeypatch.setattr(AppleSpeechAnalyzerProvider, "_resolve_locale", lambda self: "fr-FR")

    fake = _FakeCompletedProc(
        stdout=json.dumps({"type": "final", "text": "bonjour", "locale": "fr-FR"}),
        returncode=0,
    )
    patch_helper_subprocess(fake)

    AppleSpeechAnalyzerProvider().transcribe(sample_audio_bytes)

    request = json.loads(fake.sent_input)
    assert request["locale"] == "fr-FR"
    assert request["audio_path"] == "/tmp/whisper_hud_speechanalyzer_test.wav"
    # No vocabulary key when none supplied.
    assert "vocabulary" not in request


def test_transcribe_passes_vocabulary_through_request(monkeypatch, patch_helper_subprocess, sample_audio_bytes):
    _force_ready(monkeypatch)
    monkeypatch.setattr(AppleSpeechAnalyzerProvider, "_resolve_locale", lambda self: "en-US")

    fake = _FakeCompletedProc(
        stdout=json.dumps({"type": "final", "text": "ok", "locale": "en-US"}),
        returncode=0,
    )
    patch_helper_subprocess(fake)

    # Includes blanks/dupes to confirm normalization is applied before sending.
    AppleSpeechAnalyzerProvider().transcribe(
        sample_audio_bytes, vocabulary=["Kubernetes", "  ", "Kubernetes", "WhisperHUD"]
    )

    request = json.loads(fake.sent_input)
    assert request["vocabulary"] == ["Kubernetes", "WhisperHUD"]


# --- transcribe error handling ------------------------------------------------


def test_transcribe_raises_on_error_event(monkeypatch, patch_helper_subprocess, sample_audio_bytes):
    _force_ready(monkeypatch)
    monkeypatch.setattr(AppleSpeechAnalyzerProvider, "_resolve_locale", lambda self: "en-US")

    fake = _FakeCompletedProc(
        stdout=json.dumps({"type": "error", "message": "Locale 'xx-ZZ' is not supported"}),
        returncode=1,
    )
    state = patch_helper_subprocess(fake)

    with pytest.raises(RuntimeError, match="not supported"):
        AppleSpeechAnalyzerProvider().transcribe(sample_audio_bytes)

    # Temp file is still cleaned up on the error path.
    assert state["deleted"] == ["/tmp/whisper_hud_speechanalyzer_test.wav"]


def test_transcribe_raises_on_nonzero_exit_without_event(monkeypatch, patch_helper_subprocess, sample_audio_bytes):
    _force_ready(monkeypatch)
    monkeypatch.setattr(AppleSpeechAnalyzerProvider, "_resolve_locale", lambda self: "en-US")

    fake = _FakeCompletedProc(stdout="", stderr="boom", returncode=2)
    patch_helper_subprocess(fake)

    with pytest.raises(RuntimeError, match="boom"):
        AppleSpeechAnalyzerProvider().transcribe(sample_audio_bytes)


def test_transcribe_raises_when_no_final_event(monkeypatch, patch_helper_subprocess, sample_audio_bytes):
    _force_ready(monkeypatch)
    monkeypatch.setattr(AppleSpeechAnalyzerProvider, "_resolve_locale", lambda self: "en-US")

    # Only partials, no final and exit 0 -> treated as failure.
    fake = _FakeCompletedProc(stdout=json.dumps({"type": "partial", "text": "Hello"}), returncode=0)
    patch_helper_subprocess(fake)

    with pytest.raises(RuntimeError, match="no transcript"):
        AppleSpeechAnalyzerProvider().transcribe(sample_audio_bytes)


def test_transcribe_raises_when_macos_unsupported(monkeypatch, sample_audio_bytes):
    monkeypatch.setattr(AppleSpeechAnalyzerProvider, "_is_supported_macos", staticmethod(lambda: False))
    with pytest.raises(RuntimeError, match="macOS 26"):
        AppleSpeechAnalyzerProvider().transcribe(sample_audio_bytes)


def test_transcribe_raises_when_helper_missing(monkeypatch, sample_audio_bytes):
    monkeypatch.setattr(AppleSpeechAnalyzerProvider, "_is_supported_macos", staticmethod(lambda: True))
    monkeypatch.setattr(AppleSpeechAnalyzerProvider, "_helper_available", lambda self: False)
    with pytest.raises(RuntimeError, match="build-speechanalyzer.sh"):
        AppleSpeechAnalyzerProvider().transcribe(sample_audio_bytes)


# --- timeout handling ---------------------------------------------------------


def test_transcribe_kills_helper_on_timeout(monkeypatch, patch_helper_subprocess, sample_audio_bytes):
    _force_ready(monkeypatch)
    monkeypatch.setattr(AppleSpeechAnalyzerProvider, "_resolve_locale", lambda self: "en-US")

    # First communicate() raises TimeoutExpired; the provider must kill + reap.
    fake = _FakeCompletedProc(stdout="", returncode=0, timeout_first=True)
    state = patch_helper_subprocess(fake)

    with pytest.raises(TimeoutError, match="timed out"):
        AppleSpeechAnalyzerProvider().transcribe(sample_audio_bytes)

    assert fake.killed is True
    # Even on timeout the staged audio file is securely deleted.
    assert state["deleted"] == ["/tmp/whisper_hud_speechanalyzer_test.wav"]


# --- availability messaging ---------------------------------------------------


def test_availability_message_non_macos(monkeypatch):
    monkeypatch.setattr("whisper_hud.providers.apple_speechanalyzer.platform.system", lambda: "Linux")
    assert "requires macOS" in AppleSpeechAnalyzerProvider.get_availability_message()


def test_availability_message_old_macos(monkeypatch):
    monkeypatch.setattr("whisper_hud.providers.apple_speechanalyzer.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "whisper_hud.providers.apple_speechanalyzer.platform.mac_ver",
        lambda: ("15.4", ("", "", ""), "arm64"),
    )
    msg = AppleSpeechAnalyzerProvider.get_availability_message()
    assert "macOS 26" in msg
    assert "15.4" in msg


def test_availability_message_helper_missing(monkeypatch):
    monkeypatch.setattr(AppleSpeechAnalyzerProvider, "_is_supported_macos", staticmethod(lambda: True))
    monkeypatch.setattr(
        AppleSpeechAnalyzerProvider,
        "_helper_path",
        classmethod(lambda cls: __import__("pathlib").Path("/nonexistent/whisperhud-speechanalyzer")),
    )
    assert "build-speechanalyzer.sh" in AppleSpeechAnalyzerProvider.get_availability_message()


def test_availability_message_ready(monkeypatch, tmp_path):
    monkeypatch.setattr(AppleSpeechAnalyzerProvider, "_is_supported_macos", staticmethod(lambda: True))
    helper = tmp_path / "whisperhud-speechanalyzer"
    helper.write_text("#!/bin/sh\n")
    helper.chmod(0o755)
    monkeypatch.setattr(AppleSpeechAnalyzerProvider, "_helper_path", classmethod(lambda cls: helper))
    assert AppleSpeechAnalyzerProvider.get_availability_message() == "Apple Speech (Advanced) is available"
