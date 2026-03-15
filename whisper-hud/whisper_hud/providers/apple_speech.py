"""
Apple Speech Framework provider for local transcription.

Uses macOS native SFSpeechRecognizer via PyObjC for on-device recognition.
No API key required, audio never leaves the device.

Requirements:
- macOS 12.0+ (Monterey or later)
- pyobjc-framework-Speech package

Features:
- Zero setup (built into macOS)
- No model download required
- Complete privacy (on-device processing)
- Supports ~20 languages on-device
"""

import platform
from .base import TranscriptionProvider, TranscriptionResult


class AppleSpeechProvider(TranscriptionProvider):
    """Transcription provider using macOS native Speech Framework."""

    name = "apple"
    display_name = "Apple (Built-in)"

    # Supported languages for on-device recognition
    # These are available on-device starting from macOS 12+
    SUPPORTED_LANGUAGES = {
        "en-US": "English (US)",
        "en-GB": "English (UK)",
        "en-AU": "English (Australia)",
        "es-ES": "Spanish (Spain)",
        "es-MX": "Spanish (Mexico)",
        "fr-FR": "French",
        "de-DE": "German",
        "it-IT": "Italian",
        "pt-BR": "Portuguese (Brazil)",
        "pt-PT": "Portuguese (Portugal)",
        "zh-CN": "Chinese (Mandarin)",
        "zh-TW": "Chinese (Taiwan)",
        "ja-JP": "Japanese",
        "ko-KR": "Korean",
        "ru-RU": "Russian",
        "ar-SA": "Arabic",
        "nl-NL": "Dutch",
        "sv-SE": "Swedish",
        "da-DK": "Danish",
        "fi-FI": "Finnish",
        "nb-NO": "Norwegian",
        "pl-PL": "Polish",
        "tr-TR": "Turkish",
        "th-TH": "Thai",
        "vi-VN": "Vietnamese",
    }

    def __init__(self, model: str = "default"):
        """
        Initialize Apple Speech provider.

        Args:
            model: Language locale (e.g., 'en-US'). Defaults to system default.
        """
        self.model = model if model in self.SUPPORTED_LANGUAGES else "en-US"
        self._recognizer = None
        self._available = None

    def _check_availability(self) -> bool:
        """Check if Apple Speech is available on this system."""
        if self._available is not None:
            return self._available

        # Check macOS version
        if platform.system() != "Darwin":
            self._available = False
            return False

        try:
            mac_version = tuple(map(int, platform.mac_ver()[0].split(".")))
            if mac_version < (12, 0):
                self._available = False
                return False
        except Exception:
            self._available = False
            return False

        # Check if Speech framework is available
        try:
            from Speech import SFSpeechRecognizer

            recognizer = SFSpeechRecognizer.alloc().initWithLocale_(self._get_locale(self.model))
            self._available = recognizer is not None and recognizer.isAvailable()
            return self._available
        except ImportError:
            self._available = False
            return False
        except Exception:
            self._available = False
            return False

    def _get_locale(self, locale_id: str):
        """Get NSLocale for the given locale identifier."""
        from Foundation import NSLocale

        return NSLocale.localeWithLocaleIdentifier_(locale_id)

    def _get_recognizer(self):
        """Get or create the speech recognizer."""
        if self._recognizer is None:
            from Speech import SFSpeechRecognizer

            self._recognizer = SFSpeechRecognizer.alloc().initWithLocale_(self._get_locale(self.model))
        return self._recognizer

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        """
        Transcribe audio using Apple Speech Framework.

        Args:
            audio_bytes: WAV file contents

        Returns:
            TranscriptionResult with transcribed text
        """
        import os
        import tempfile
        import time

        start_time = time.time()
        temp_file = None

        if not self._check_availability():
            raise RuntimeError(
                "Apple Speech Recognition is not available. " "Requires macOS 12+ and pyobjc-framework-Speech."
            )

        try:
            from Foundation import NSURL

            # Write audio to a unique temp file (Speech framework needs a file URL)
            # Use restrictive permissions (owner-only) and consistent prefix for cleanup
            with tempfile.NamedTemporaryFile(prefix="whisper_hud_", suffix=".wav", delete=False) as temp_fp:
                os.chmod(temp_fp.name, 0o600)
                temp_fp.write(audio_bytes)
                temp_file = temp_fp.name

            # Create file URL
            file_url = NSURL.fileURLWithPath_(temp_file)

            # Create recognition request from URL
            from Speech import SFSpeechURLRecognitionRequest

            request = SFSpeechURLRecognitionRequest.alloc().initWithURL_(file_url)
            request.setShouldReportPartialResults_(False)

            # Use on-device recognition if available
            if hasattr(request, "setRequiresOnDeviceRecognition_"):
                request.setRequiresOnDeviceRecognition_(True)

            recognizer = self._get_recognizer()
            if not recognizer or not recognizer.isAvailable():
                raise RuntimeError("Speech recognizer is not available")

            # Perform synchronous recognition using semaphore
            import threading

            result_text = ""
            recognition_error = None
            semaphore = threading.Semaphore(0)

            def completion_handler(result, error):
                nonlocal result_text, recognition_error

                if error:
                    recognition_error = str(error.localizedDescription())
                elif result and result.isFinal():
                    result_text = result.bestTranscription().formattedString()

                semaphore.release()

            # Start recognition
            task = recognizer.recognitionTaskWithRequest_resultHandler_(request, completion_handler)

            # Wait for completion (timeout after 60 seconds)
            if not semaphore.acquire(timeout=60):
                task.cancel()
                raise TimeoutError("Speech recognition timed out")

            if recognition_error:
                raise RuntimeError(f"Speech recognition error: {recognition_error}")

            duration = time.time() - start_time

            return TranscriptionResult(
                text=result_text,
                duration_seconds=duration,
                cost_estimate=0.0,  # Free - on device
                provider=self.name,
                model=self.model,
                language=self.model.split("-")[0] if "-" in self.model else None,
            )

        except ImportError as e:
            raise RuntimeError(
                f"Required framework not available: {e}. " "Install with: pip install pyobjc-framework-Speech"
            )
        except Exception as e:
            raise RuntimeError(f"Apple Speech transcription failed: {e}")
        finally:
            # Always clean up temp audio files, even on early failures.
            if temp_file and os.path.exists(temp_file):
                try:
                    from ..encryption import secure_delete

                    secure_delete(temp_file)
                except Exception:
                    try:
                        os.unlink(temp_file)
                    except Exception:
                        pass

    def is_configured(self) -> bool:
        """
        Check if Apple Speech is available.

        Always returns True on macOS 12+ since no API key is needed.
        """
        return self._check_availability()

    def get_models(self) -> list[dict]:
        """
        Return available language models.

        Returns:
            List of supported languages as "models"
        """
        return [
            {"id": locale_id, "name": name, "description": "On-device recognition", "cost_per_minute": 0.0}
            for locale_id, name in self.SUPPORTED_LANGUAGES.items()
        ]

    def set_model(self, model_id: str) -> None:
        """Set the language/locale."""
        if model_id in self.SUPPORTED_LANGUAGES:
            self.model = model_id
            self._recognizer = None  # Reset recognizer to use new locale

    def get_current_model(self) -> str:
        """Get the current language/locale."""
        return self.model

    def supports_streaming(self) -> bool:
        """Apple Speech supports streaming, but we use sync for simplicity."""
        return False

    @staticmethod
    def get_macos_version() -> tuple:
        """Get the current macOS version as a tuple."""
        try:
            return tuple(map(int, platform.mac_ver()[0].split(".")))
        except Exception:
            return (0, 0, 0)

    @staticmethod
    def is_macos_12_or_later() -> bool:
        """Check if running macOS 12 or later."""
        version = AppleSpeechProvider.get_macos_version()
        return version >= (12, 0)

    @classmethod
    def get_availability_message(cls) -> str:
        """Get a human-readable availability message."""
        if platform.system() != "Darwin":
            return "Apple Speech requires macOS"

        version = cls.get_macos_version()
        if version < (12, 0):
            return f"Apple Speech requires macOS 12+. You have {platform.mac_ver()[0]}"

        try:
            import Speech

            _ = Speech.SFSpeechRecognizer
            return "Apple Speech is available"
        except ImportError:
            return "Install pyobjc-framework-Speech: pip install pyobjc-framework-Speech"

    @classmethod
    def get_setup_instructions(cls) -> tuple[str, str]:
        """
        Get detailed setup instructions.

        Returns:
            Tuple of (title, message) for the setup dialog
        """
        if platform.system() != "Darwin":
            return ("Not Available", "Apple Speech requires macOS.")

        version = cls.get_macos_version()
        if version < (12, 0):
            return (
                "macOS Update Required",
                f"Apple Speech requires macOS 12 (Monterey) or later.\n\n"
                f"Your version: macOS {platform.mac_ver()[0]}\n\n"
                "Please update macOS to use Apple Speech Recognition.",
            )

        try:
            from Speech import SFSpeechRecognizer
        except ImportError:
            return (
                "Package Required",
                "The Speech framework binding is not installed.\n\n"
                "Install it by running:\n"
                "pip install pyobjc-framework-Speech\n\n"
                "Then restart WhisperHUD.",
            )

        # Check if recognizer works
        try:
            from Foundation import NSLocale

            locale = NSLocale.localeWithLocaleIdentifier_("en-US")
            recognizer = SFSpeechRecognizer.alloc().initWithLocale_(locale)

            if recognizer is None:
                return (
                    "Speech Recognition Unavailable",
                    "The Speech Recognizer could not be initialized.\n\n" "Try restarting your Mac.",
                )

            if not recognizer.isAvailable():
                return (
                    "Permissions Required",
                    "Apple Speech Recognition needs permissions.\n\n"
                    "1. Open System Settings\n"
                    "2. Go to Privacy & Security → Speech Recognition\n"
                    "3. Enable WhisperHUD\n\n"
                    "You may also need to enable Dictation:\n"
                    "System Settings → Keyboard → Dictation",
                )
        except Exception as e:
            return (
                "Setup Error",
                f"Could not initialize Speech Recognition:\n{str(e)[:100]}\n\n"
                "Try restarting WhisperHUD or your Mac.",
            )

        return ("Ready", "Apple Speech is ready to use.")

    @staticmethod
    def open_speech_settings():
        """Open System Settings to Speech Recognition permissions."""
        import subprocess

        # macOS 13+ uses System Settings, earlier uses System Preferences
        version = AppleSpeechProvider.get_macos_version()
        if version >= (13, 0):
            subprocess.run(
                ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_SpeechRecognition"],
                capture_output=True,
            )
        else:
            subprocess.run(["open", "/System/Library/PreferencePanes/Security.prefPane"], capture_output=True)
