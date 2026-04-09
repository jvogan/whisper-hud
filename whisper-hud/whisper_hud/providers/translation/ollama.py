"""
Ollama TranslateGemma provider for local translation.

Uses Google's TranslateGemma models via Ollama for privacy-focused,
on-device translation. No data is sent to cloud APIs.

Models (January 2026):
- translategemma (4B): 3.3 GB, ~8GB RAM, fast
- translategemma:12b: 8.1 GB, ~16GB RAM, better quality
- translategemma:27b: 17 GB, ~32GB RAM, best quality
"""

import os
import subprocess
import requests
from typing import Optional, Callable
from .base import TranslationProvider, TranslationResult
from ..error_utils import build_provider_error_message


class OllamaTranslateProvider(TranslationProvider):
    """Translation provider using TranslateGemma via Ollama."""

    name = "ollama"
    display_name = "Ollama (Local)"

    OLLAMA_API = "http://127.0.0.1:11434"
    REQUEST_TIMEOUT_SECONDS = 60
    HEALTH_TIMEOUT_SECONDS = 2

    # Available TranslateGemma models
    MODELS = {
        "translategemma-4b": {
            "ollama_name": "translategemma",
            "size_gb": 3.3,
            "ram_required": "8GB",
            "description": "Fast, works on most Macs",
        },
        "translategemma-12b": {
            "ollama_name": "translategemma:12b",
            "size_gb": 8.1,
            "ram_required": "16GB",
            "description": "Better quality, needs more RAM",
        },
        "translategemma-27b": {
            "ollama_name": "translategemma:27b",
            "size_gb": 17.0,
            "ram_required": "32GB",
            "description": "Best quality, high-end Macs only",
        },
    }

    # Whitelisted model names for subprocess calls (security)
    # Pattern: alphanumeric, hyphens, underscores, dots, colons (for tags)
    import re

    _VALID_MODEL_PATTERN = re.compile(r"^[a-zA-Z0-9._:-]+$")

    @classmethod
    def _validate_model_name(cls, model_name: str) -> bool:
        """
        Validate model name is safe for subprocess execution.

        Only allows alphanumeric characters, hyphens, underscores,
        dots, and colons (for version tags like model:12b).
        """
        if not model_name or len(model_name) > 100:
            return False
        return bool(cls._VALID_MODEL_PATTERN.match(model_name))

    # 55 Supported Languages (ISO 639-1 codes)
    SUPPORTED_LANGUAGES = {
        "ar": "Arabic",
        "bn": "Bengali",
        "bg": "Bulgarian",
        "ca": "Catalan",
        "zh": "Chinese (Simplified)",
        "zh-TW": "Chinese (Traditional)",
        "hr": "Croatian",
        "cs": "Czech",
        "da": "Danish",
        "nl": "Dutch",
        "en": "English",
        "et": "Estonian",
        "fi": "Finnish",
        "fr": "French",
        "de": "German",
        "el": "Greek",
        "gu": "Gujarati",
        "he": "Hebrew",
        "hi": "Hindi",
        "hu": "Hungarian",
        "is": "Icelandic",
        "id": "Indonesian",
        "ga": "Irish",
        "it": "Italian",
        "ja": "Japanese",
        "kn": "Kannada",
        "ko": "Korean",
        "lv": "Latvian",
        "lt": "Lithuanian",
        "mk": "Macedonian",
        "ms": "Malay",
        "ml": "Malayalam",
        "mr": "Marathi",
        "no": "Norwegian",
        "fa": "Persian",
        "pl": "Polish",
        "pt": "Portuguese",
        "pa": "Punjabi",
        "ro": "Romanian",
        "ru": "Russian",
        "sr": "Serbian",
        "sk": "Slovak",
        "sl": "Slovenian",
        "es": "Spanish",
        "sw": "Swahili",
        "sv": "Swedish",
        "ta": "Tamil",
        "te": "Telugu",
        "th": "Thai",
        "tr": "Turkish",
        "uk": "Ukrainian",
        "ur": "Urdu",
        "vi": "Vietnamese",
        "cy": "Welsh",
        "zu": "Zulu",
    }

    def __init__(self, model: str = "translategemma-4b"):
        if model not in self.MODELS:
            model = "translategemma-4b"
        self.model = model
        self.model_config = self.MODELS[model]
        self._ollama_process: Optional[subprocess.Popen] = None
        self._http_session: Optional[requests.Session] = None

    def _get_http_session(self) -> requests.Session:
        """Use a local-only session that ignores proxy environment variables."""
        if self._http_session is None:
            session = requests.Session()
            session.trust_env = False
            self._http_session = session
        return self._http_session

    def _get_tags_response(self, timeout: float) -> requests.Response:
        """Fetch the local Ollama tags endpoint without following redirects."""
        return self._get_http_session().get(
            f"{self.OLLAMA_API}/api/tags",
            timeout=timeout,
            allow_redirects=False,
        )

    def _generate(self, prompt: str, *, stream: bool) -> requests.Response:
        """Post a translation request to the local Ollama daemon."""
        return self._get_http_session().post(
            f"{self.OLLAMA_API}/api/generate",
            json={
                "model": self.model_config["ollama_name"],
                "prompt": prompt,
                "stream": stream,
                "options": {
                    "temperature": 0.1,
                },
            },
            stream=stream,
            timeout=self.REQUEST_TIMEOUT_SECONDS,
            allow_redirects=False,
        )

    def translate(self, text: str, source_lang: str, target_lang: str) -> TranslationResult:
        """
        Translate text using TranslateGemma via Ollama.

        Args:
            text: Text to translate
            source_lang: Source language code (e.g., 'en')
            target_lang: Target language code (e.g., 'es')

        Returns:
            TranslationResult with translated text
        """
        if not text.strip():
            return TranslationResult(
                text="", source_lang=source_lang, target_lang=target_lang, provider=self.name, model=self.model
            )

        # Build the prompt for TranslateGemma
        prompt = self._build_prompt(text, source_lang, target_lang)

        try:
            response = self._generate(prompt, stream=False)
            response.raise_for_status()

            result_text = response.json().get("response", "").strip()

            # Clean up any artifacts from the model response
            result_text = self._clean_response(result_text)

            return TranslationResult(
                text=result_text, source_lang=source_lang, target_lang=target_lang, provider=self.name, model=self.model
            )

        except requests.exceptions.ConnectionError:
            raise ConnectionError("Ollama is not running. Start it with: ollama serve")
        except requests.exceptions.Timeout:
            raise TimeoutError("Translation timed out")
        except Exception as e:
            raise RuntimeError(build_provider_error_message("Ollama", "translation", e)) from e

    def _build_prompt(self, text: str, source_lang: str, target_lang: str) -> str:
        """Build the translation prompt for TranslateGemma."""
        target_name = self.SUPPORTED_LANGUAGES.get(target_lang, target_lang)

        if not source_lang or source_lang == "auto":
            instruction = f"Detect the source language and translate to {target_name}."
        else:
            source_name = self.SUPPORTED_LANGUAGES.get(source_lang, source_lang)
            instruction = f"Translate the following text from {source_name} to {target_name}."

        # TranslateGemma prompt format (Gemma instruct format)
        return f"""<start_of_turn>user
{instruction} Output ONLY the translation, nothing else.

{text}<end_of_turn>
<start_of_turn>model
"""

    def _clean_response(self, text: str) -> str:
        """Clean up model response artifacts."""
        # Remove any trailing model tags
        if "<end_of_turn>" in text:
            text = text.split("<end_of_turn>")[0]

        # Remove any leading/trailing whitespace
        text = text.strip()

        # Remove quotes if the model wrapped the translation in them
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
        if text.startswith("'") and text.endswith("'"):
            text = text[1:-1]

        return text

    def is_available(self) -> bool:
        """Check if Ollama is running and model is downloaded."""
        try:
            # Check if Ollama server is running
            response = self._get_tags_response(self.HEALTH_TIMEOUT_SECONDS)
            if response.status_code != 200:
                return False

            # Check if model is downloaded
            return self._is_model_downloaded()
        except Exception:
            return False

    def _is_model_downloaded(self) -> bool:
        """Check if the current model is downloaded in Ollama."""
        try:
            response = self._get_tags_response(5)
            if response.status_code != 200:
                return False

            models = response.json().get("models", [])
            ollama_name = self.model_config["ollama_name"]

            # Check for exact match or prefix match
            base_name = ollama_name.split(":")[0]
            for m in models:
                model_name = m.get("name", "")
                # Match "translategemma:latest" or "translategemma:12b" etc.
                if model_name == ollama_name or model_name.startswith(f"{base_name}:"):
                    return True
                # Also match if just the base name with :latest
                if ollama_name == base_name and model_name == f"{base_name}:latest":
                    return True

            return False
        except Exception:
            return False

    def get_model_status(self) -> dict:
        """Return model download status and info."""
        ollama_installed = self.is_ollama_installed()
        ollama_running = self._is_ollama_running()
        model_downloaded = self._is_model_downloaded() if ollama_running else False

        return {
            "model": self.model,
            "ollama_installed": ollama_installed,
            "ollama_running": ollama_running,
            "downloaded": model_downloaded,
            "size_gb": self.model_config["size_gb"],
            "ram_required": self.model_config["ram_required"],
            "description": self.model_config["description"],
        }

    def _is_ollama_running(self) -> bool:
        """Check if Ollama server is running."""
        try:
            response = self._get_tags_response(self.HEALTH_TIMEOUT_SECONDS)
            return response.status_code == 200
        except Exception:
            return False

    def download_model(self, progress_callback: Optional[Callable[[str], None]] = None) -> bool:
        """
        Download the model via ollama pull.

        Args:
            progress_callback: Called with progress lines from ollama

        Returns:
            True if download succeeded
        """
        if not self.is_ollama_installed():
            if progress_callback:
                progress_callback("Error: Ollama is not installed")
            return False

        # Validate model name before passing to subprocess (security)
        ollama_name = self.model_config["ollama_name"]
        if not self._validate_model_name(ollama_name):
            if progress_callback:
                progress_callback("Error: Invalid model name")
            return False

        try:
            process = subprocess.Popen(
                ["ollama", "pull", ollama_name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
            )

            for line in iter(process.stdout.readline, ""):
                if line and progress_callback:
                    progress_callback(line.strip())

            process.wait()
            return process.returncode == 0

        except FileNotFoundError:
            if progress_callback:
                progress_callback("Error: Ollama command not found")
            return False
        except Exception as e:
            if progress_callback:
                progress_callback(f"Error: {e}")
            return False

    @staticmethod
    def is_ollama_installed() -> bool:
        """Check if Ollama CLI is installed."""
        try:
            result = subprocess.run(["ollama", "--version"], capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def set_model(self, model_id: str) -> None:
        """Change the active model."""
        # Only allow whitelisted model IDs from MODELS dict
        if model_id in self.MODELS:
            ollama_name = self.MODELS[model_id]["ollama_name"]
            # Double-check the ollama name is safe (defense in depth)
            if self._validate_model_name(ollama_name):
                self.model = model_id
                self.model_config = self.MODELS[model_id]

    def get_current_model(self) -> str:
        """Get the current model ID."""
        return self.model

    def get_models(self) -> list[dict]:
        """Return available models with their info."""
        return [
            {
                "id": model_id,
                "name": f"{model_id.replace('translategemma-', '').upper()} ({config['size_gb']}GB)",
                "description": config["description"],
                "size_gb": config["size_gb"],
                "ram_required": config["ram_required"],
                "ollama_name": config["ollama_name"],
            }
            for model_id, config in self.MODELS.items()
        ]

    @classmethod
    def get_supported_languages(cls) -> dict[str, str]:
        """Return dict of supported language codes to names."""
        return cls.SUPPORTED_LANGUAGES.copy()

    def supports_streaming(self) -> bool:
        """Ollama supports streaming translation."""
        return True

    def translate_streaming(self, text: str, source_lang: str, target_lang: str, on_chunk: Callable[[str], None]):
        """
        Translate text with streaming output.

        Args:
            text: Text to translate
            source_lang: Source language code
            target_lang: Target language code
            on_chunk: Callback called with cumulative text as it streams

        Returns:
            TranslationResult with translated text
        """
        from .base import TranslationResult

        if not text.strip():
            return TranslationResult(
                text="", source_lang=source_lang, target_lang=target_lang, provider=self.name, model=self.model
            )

        prompt = self._build_prompt(text, source_lang, target_lang)
        cumulative_text = ""

        try:
            response = self._generate(prompt, stream=True)
            response.raise_for_status()

            for line in response.iter_lines():
                if line:
                    try:
                        import json

                        data = json.loads(line.decode("utf-8"))
                        if "response" in data:
                            cumulative_text += data["response"]
                            # Clean and send update
                            clean_text = self._clean_response(cumulative_text)
                            on_chunk(clean_text)
                        if data.get("done", False):
                            break
                    except json.JSONDecodeError:
                        continue

            final_text = self._clean_response(cumulative_text)

            return TranslationResult(
                text=final_text, source_lang=source_lang, target_lang=target_lang, provider=self.name, model=self.model
            )

        except requests.exceptions.ConnectionError:
            raise ConnectionError("Ollama is not running. Start it with: ollama serve")
        except requests.exceptions.Timeout:
            raise TimeoutError("Translation timed out")
        except Exception as e:
            raise RuntimeError(build_provider_error_message("Ollama", "translation", e)) from e

    @staticmethod
    def is_homebrew_installed() -> bool:
        """Check if Homebrew is installed."""
        try:
            result = subprocess.run(["brew", "--version"], capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def install_ollama(progress_callback: Optional[Callable[[str], None]] = None) -> bool:
        """
        Install Ollama via Homebrew.

        Args:
            progress_callback: Called with progress messages

        Returns:
            True if installation succeeded
        """
        if not OllamaTranslateProvider.is_homebrew_installed():
            if progress_callback:
                progress_callback("Error: Homebrew is not installed. Please install Homebrew first.")
            return False

        try:
            if progress_callback:
                progress_callback("Installing Ollama via Homebrew...")

            process = subprocess.Popen(
                ["brew", "install", "ollama"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
            )

            for line in iter(process.stdout.readline, ""):
                if line and progress_callback:
                    progress_callback(line.strip())

            process.wait()
            success = process.returncode == 0

            if success and progress_callback:
                progress_callback("Ollama installed successfully!")

            return success

        except FileNotFoundError:
            if progress_callback:
                progress_callback("Error: Homebrew command not found")
            return False
        except Exception as e:
            if progress_callback:
                progress_callback(f"Error: {e}")
            return False

    def start_ollama_server(self) -> tuple[bool, Optional[int]]:
        """
        Start the Ollama server in the background.

        Returns:
            Tuple of (success, process_id or None)
        """
        # Check if already running
        try:
            response = self._get_tags_response(self.HEALTH_TIMEOUT_SECONDS)
            if response.status_code == 200:
                return True, None  # Already running
        except Exception:
            pass

        try:
            # Start ollama serve in background
            process = subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,  # Detach from parent process
            )

            # Store the process so we can terminate it precisely later
            self._ollama_process = process

            # Wait a moment for server to start
            import time

            for _ in range(10):  # Wait up to 5 seconds
                time.sleep(0.5)
                try:
                    response = self._get_tags_response(self.HEALTH_TIMEOUT_SECONDS)
                    if response.status_code == 200:
                        return True, process.pid
                except Exception:
                    continue

            return False, None

        except FileNotFoundError:
            return False, None
        except Exception:
            return False, None

    def stop_ollama_server(self) -> bool:
        """
        Stop the Ollama server process that was started by this instance.

        Only terminates the process if it was started by this application
        (i.e., self._ollama_process is set). Does not use broad pattern-matching
        process killing (e.g., pkill -f) that could affect unrelated processes.

        Returns:
            True if successfully stopped (or no managed process was running)
        """
        if self._ollama_process is None:
            # No process was started by this instance; nothing to stop
            return True

        process = self._ollama_process
        self._ollama_process = None

        try:
            # Check if the process is still running
            if process.poll() is not None:
                # Process has already exited
                return True

            # Send SIGTERM and wait up to 5 seconds for a clean shutdown
            process.terminate()
            try:
                process.wait(timeout=5)
                return True
            except subprocess.TimeoutExpired:
                # Process did not exit cleanly; escalate to SIGKILL
                process.kill()
                process.wait()
                return True
        except Exception:
            return False

    @staticmethod
    def check_disk_space(required_gb: float) -> tuple[bool, float]:
        """
        Check if there's enough disk space for download.

        Args:
            required_gb: Required space in GB

        Returns:
            Tuple of (has_space, available_gb)
        """
        try:
            statvfs = os.statvfs(os.path.expanduser("~"))
            available_gb = (statvfs.f_frsize * statvfs.f_bavail) / (1024**3)
            # Require 50% buffer
            has_space = available_gb >= (required_gb * 1.5)
            return has_space, available_gb
        except Exception:
            return False, 0.0
