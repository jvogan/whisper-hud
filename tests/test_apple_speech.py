"""Tests for the Apple Speech transcription provider."""

import builtins
import threading
from types import SimpleNamespace

import pytest

from whisper_hud.providers.apple_speech import AppleSpeechProvider


class _FakeLocale:
    @staticmethod
    def localeWithLocaleIdentifier_(locale_id):
        return f"locale:{locale_id}"


class _FakeURL:
    @staticmethod
    def fileURLWithPath_(path):
        return f"url:{path}"


class _FakeSpeechError:
    def __init__(self, message):
        self._message = message

    def localizedDescription(self):
        return self._message


class _FakeBestTranscription:
    def __init__(self, text):
        self._text = text

    def formattedString(self):
        return self._text


class _FakeRecognitionResult:
    def __init__(self, text="", is_final=True):
        self._text = text
        self._is_final = is_final

    def isFinal(self):
        return self._is_final

    def bestTranscription(self):
        return _FakeBestTranscription(self._text)


class _FakeTask:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class _FakeRequest:
    def __init__(self, file_url):
        self.file_url = file_url
        self.partial_results = None
        self.requires_on_device = None

    def setShouldReportPartialResults_(self, value):
        self.partial_results = value

    def setRequiresOnDeviceRecognition_(self, value):
        self.requires_on_device = value


class _FakeRequestFactory:
    def __init__(self):
        self.requests = []

    def alloc(self):
        return self

    def initWithURL_(self, file_url):
        request = _FakeRequest(file_url)
        self.requests.append(request)
        return request


class _FakeRecognizer:
    def __init__(self, available=True, completion=None):
        self.available = available
        self.completion = completion
        self.locales = []
        self.requests = []
        self.task = _FakeTask()

    def initWithLocale_(self, locale):
        self.locales.append(locale)
        return self

    def isAvailable(self):
        return self.available

    def recognitionTaskWithRequest_resultHandler_(self, request, handler):
        self.requests.append(request)
        if self.completion is not None:
            self.completion(handler)
        return self.task


class _FakeRecognizerFactory:
    def __init__(self, recognizer):
        self.recognizer = recognizer

    def alloc(self):
        return self.recognizer


def _install_speech_modules(monkeypatch, recognizer=None, request_factory=None):
    if recognizer is None:
        recognizer = _FakeRecognizer()
    if request_factory is None:
        request_factory = _FakeRequestFactory()

    monkeypatch.setitem(
        __import__("sys").modules,
        "Foundation",
        SimpleNamespace(NSLocale=_FakeLocale, NSURL=_FakeURL),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "Speech",
        SimpleNamespace(
            SFSpeechRecognizer=_FakeRecognizerFactory(recognizer),
            SFSpeechURLRecognitionRequest=request_factory,
        ),
    )
    return recognizer, request_factory


def _set_macos(monkeypatch, version="12.3.1"):
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("platform.mac_ver", lambda: (version, ("", "", ""), ""))


def _block_import(monkeypatch, module_name):
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == module_name:
            raise ImportError(f"{module_name} unavailable")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    return original_import


@pytest.fixture(autouse=True)
def clear_provider_modules(monkeypatch):
    monkeypatch.delitem(__import__("sys").modules, "Speech", raising=False)
    monkeypatch.delitem(__import__("sys").modules, "Foundation", raising=False)


def test_provider_reports_unavailable_on_non_macos(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")

    provider = AppleSpeechProvider()

    assert provider.is_configured() is False
    assert provider._available is False


def test_provider_reports_available_on_macos_with_speech_framework(monkeypatch):
    _set_macos(monkeypatch)
    recognizer, _ = _install_speech_modules(monkeypatch, recognizer=_FakeRecognizer(available=True))

    provider = AppleSpeechProvider(model="en-US")

    assert provider.is_configured() is True
    assert recognizer.locales == ["locale:en-US"]


def test_transcribe_returns_text_on_success(monkeypatch, sample_audio_bytes):
    _set_macos(monkeypatch)

    def complete(handler):
        handler(_FakeRecognitionResult("Hello from Apple Speech"), None)

    recognizer, request_factory = _install_speech_modules(
        monkeypatch,
        recognizer=_FakeRecognizer(available=True, completion=complete),
    )
    secure_delete_calls = []
    monkeypatch.setattr(
        "whisper_hud.providers.apple_speech.AppleSpeechProvider._check_availability",
        lambda self: True,
    )
    monkeypatch.setattr(
        "whisper_hud.encryption.secure_delete",
        lambda path: secure_delete_calls.append(path),
    )

    provider = AppleSpeechProvider(model="en-US")
    result = provider.transcribe(sample_audio_bytes)

    assert result.text == "Hello from Apple Speech"
    assert result.provider == "apple"
    assert result.model == "en-US"
    assert result.language == "en"
    assert result.duration_seconds >= 0
    assert result.cost_estimate == 0.0
    assert recognizer.requests == request_factory.requests
    assert request_factory.requests[0].partial_results is False
    assert request_factory.requests[0].requires_on_device is True
    assert secure_delete_calls and secure_delete_calls[0].endswith(".wav")


def test_transcribe_wraps_recognition_errors(monkeypatch, sample_audio_bytes):
    _set_macos(monkeypatch)

    def complete(handler):
        handler(None, _FakeSpeechError("No speech detected"))

    _install_speech_modules(
        monkeypatch,
        recognizer=_FakeRecognizer(available=True, completion=complete),
    )
    monkeypatch.setattr(
        "whisper_hud.providers.apple_speech.AppleSpeechProvider._check_availability",
        lambda self: True,
    )
    monkeypatch.setattr("whisper_hud.encryption.secure_delete", lambda path: None)

    with pytest.raises(
        RuntimeError,
        match="Apple Speech transcription failed: Speech recognition error: No speech detected",
    ):
        AppleSpeechProvider().transcribe(sample_audio_bytes)


def test_transcribe_returns_empty_string_for_empty_audio(monkeypatch):
    _set_macos(monkeypatch)

    def complete(handler):
        handler(_FakeRecognitionResult(""), None)

    _install_speech_modules(
        monkeypatch,
        recognizer=_FakeRecognizer(available=True, completion=complete),
    )
    monkeypatch.setattr(
        "whisper_hud.providers.apple_speech.AppleSpeechProvider._check_availability",
        lambda self: True,
    )
    monkeypatch.setattr("whisper_hud.encryption.secure_delete", lambda path: None)

    result = AppleSpeechProvider().transcribe(b"")

    assert result.text == ""
    assert result.provider == "apple"
    assert result.model == "en-US"


def test_transcribe_times_out_and_cancels_task(monkeypatch, sample_audio_bytes):
    _set_macos(monkeypatch)
    recognizer = _FakeRecognizer(available=True, completion=None)
    _install_speech_modules(monkeypatch, recognizer=recognizer)
    monkeypatch.setattr(
        "whisper_hud.providers.apple_speech.AppleSpeechProvider._check_availability",
        lambda self: True,
    )
    monkeypatch.setattr("whisper_hud.encryption.secure_delete", lambda path: None)

    original_acquire = threading.Semaphore.acquire

    def fake_acquire(self, timeout=None):
        if timeout == 60:
            return False
        return original_acquire(self, timeout=timeout)

    monkeypatch.setattr(threading.Semaphore, "acquire", fake_acquire)

    with pytest.raises(RuntimeError, match="Apple Speech transcription failed: Speech recognition timed out"):
        AppleSpeechProvider().transcribe(sample_audio_bytes)

    assert recognizer.task.cancelled is True


def test_model_helpers_and_caching(monkeypatch):
    _set_macos(monkeypatch)
    recognizer, _ = _install_speech_modules(monkeypatch, recognizer=_FakeRecognizer(available=True))

    provider = AppleSpeechProvider(model="not-a-real-locale")

    assert provider.get_current_model() == "en-US"
    assert provider.supports_streaming() is False
    assert provider.get_models()[0]["description"] == "On-device recognition"

    first = provider._get_recognizer()
    second = provider._get_recognizer()

    assert first is second
    provider.set_model("fr-FR")
    assert provider.get_current_model() == "fr-FR"
    assert provider._recognizer is None
    assert recognizer.locales == ["locale:en-US"]


def test_macos_version_helpers(monkeypatch):
    _set_macos(monkeypatch, version="14.4.0")

    assert AppleSpeechProvider.get_macos_version() == (14, 4, 0)
    assert AppleSpeechProvider.is_macos_12_or_later() is True

    monkeypatch.setattr("platform.mac_ver", lambda: ("not-a-version", ("", "", ""), ""))
    assert AppleSpeechProvider.get_macos_version() == (0, 0, 0)
    assert AppleSpeechProvider.is_macos_12_or_later() is False


def test_availability_message_covers_platform_version_and_package_states(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    assert AppleSpeechProvider.get_availability_message() == "Apple Speech requires macOS"

    _set_macos(monkeypatch, version="11.7.2")
    assert AppleSpeechProvider.get_availability_message() == "Apple Speech requires macOS 12+. You have 11.7.2"

    _set_macos(monkeypatch, version="12.3.1")
    original_import = _block_import(monkeypatch, "Speech")
    assert AppleSpeechProvider.get_availability_message() == (
        "Install pyobjc-framework-Speech: pip install pyobjc-framework-Speech"
    )

    monkeypatch.setattr(builtins, "__import__", original_import)
    _install_speech_modules(monkeypatch)
    assert AppleSpeechProvider.get_availability_message() == "Apple Speech is available"


def test_setup_instructions_cover_non_macos_missing_package_and_ready_states(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    assert AppleSpeechProvider.get_setup_instructions() == ("Not Available", "Apple Speech requires macOS.")

    _set_macos(monkeypatch, version="11.6.8")
    title, message = AppleSpeechProvider.get_setup_instructions()
    assert title == "macOS Update Required"
    assert "macOS 11.6.8" in message

    _set_macos(monkeypatch, version="12.3.1")
    original_import = _block_import(monkeypatch, "Speech")
    title, message = AppleSpeechProvider.get_setup_instructions()
    assert title == "Package Required"
    assert "pip install pyobjc-framework-Speech" in message

    monkeypatch.setattr(builtins, "__import__", original_import)
    _install_speech_modules(monkeypatch, recognizer=_FakeRecognizer(available=True))
    assert AppleSpeechProvider.get_setup_instructions() == ("Ready", "Apple Speech is ready to use.")


def test_setup_instructions_cover_permission_and_setup_errors(monkeypatch):
    _set_macos(monkeypatch)

    _install_speech_modules(monkeypatch, recognizer=_FakeRecognizer(available=False))
    title, message = AppleSpeechProvider.get_setup_instructions()
    assert title == "Permissions Required"
    assert "Speech Recognition" in message

    class _ExplodingLocale:
        @staticmethod
        def localeWithLocaleIdentifier_(_locale_id):
            raise RuntimeError("locale unavailable")

    monkeypatch.setitem(
        __import__("sys").modules,
        "Foundation",
        SimpleNamespace(NSLocale=_ExplodingLocale, NSURL=_FakeURL),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "Speech",
        SimpleNamespace(
            SFSpeechRecognizer=_FakeRecognizerFactory(_FakeRecognizer(available=True)),
            SFSpeechURLRecognitionRequest=_FakeRequestFactory(),
        ),
    )
    title, message = AppleSpeechProvider.get_setup_instructions()
    assert title == "Setup Error"
    assert "locale unavailable" in message


def test_open_speech_settings_uses_expected_system_path(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.run", lambda args, capture_output: calls.append((args, capture_output)))

    monkeypatch.setattr(AppleSpeechProvider, "get_macos_version", staticmethod(lambda: (13, 0)))
    AppleSpeechProvider.open_speech_settings()

    monkeypatch.setattr(AppleSpeechProvider, "get_macos_version", staticmethod(lambda: (12, 6)))
    AppleSpeechProvider.open_speech_settings()

    assert calls == [
        (
            [
                "open",
                "x-apple.systempreferences:com.apple.preference.security?Privacy_SpeechRecognition",
            ],
            True,
        ),
        (
            ["open", "/System/Library/PreferencePanes/Security.prefPane"],
            True,
        ),
    ]
