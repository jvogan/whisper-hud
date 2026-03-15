"""
Apple Translation provider (local, system-managed).

Uses a small helper binary built with Apple's Translation framework.
This keeps the Python app lightweight while enabling on-device translation
when available on the host OS.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .base import TranslationProvider, TranslationResult


class AppleTranslateProvider(TranslationProvider):
    """Translation provider using Apple's Translation framework via helper."""

    name = "apple"
    display_name = "Apple (Local)"

    # Conservative set of commonly supported languages (ISO 639-1 codes)
    SUPPORTED_LANGUAGES = {
        "en": "English",
        "zh": "Chinese (Simplified)",
        "zh-TW": "Chinese (Traditional)",
        "es": "Spanish",
        "fr": "French",
        "de": "German",
        "it": "Italian",
        "ja": "Japanese",
        "ko": "Korean",
        "pt": "Portuguese",
        "ru": "Russian",
        "ar": "Arabic",
        "nl": "Dutch",
        "tr": "Turkish",
        "th": "Thai",
        "vi": "Vietnamese",
        "id": "Indonesian",
        "hi": "Hindi",
    }

    MODELS = {
        "system": {
            "name": "Apple System",
            "description": "On-device when available; system-managed",
            "category": "balanced",
            "recommended": True,
        }
    }

    def __init__(self, model: str = "system"):
        self.model = model if model in self.MODELS else "system"

    @staticmethod
    def _helper_path() -> Path:
        override = os.environ.get("WHISPERHUD_APPLE_TRANSLATE_HELPER")
        if override:
            return Path(override).expanduser()

        if getattr(sys, "frozen", False):
            try:
                from Foundation import NSBundle

                bundle = NSBundle.mainBundle()
                resources_path = bundle.resourcePath()
                if resources_path:
                    candidate = Path(resources_path) / "bin" / "whisperhud-apple-translate"
                    return candidate
            except Exception:
                pass

        # Project root (repo/whisper-hud) when running from source
        pkg_root = Path(__file__).resolve().parents[3]
        return pkg_root / "bin" / "whisperhud-apple-translate"

    @staticmethod
    def _is_supported_macos() -> bool:
        if platform.system() != "Darwin":
            return False
        try:
            version = tuple(int(p) for p in platform.mac_ver()[0].split(".")[:2])
        except Exception:
            return False
        # Translation framework requires macOS 26+
        return version >= (26, 0)

    def is_available(self) -> bool:
        """Check if helper binary is present and OS is supported."""
        if not self._is_supported_macos():
            return False
        helper = self._helper_path()
        return helper.exists() and os.access(helper, os.X_OK)

    def translate(self, text: str, source_lang: str, target_lang: str) -> TranslationResult:
        if not text.strip():
            return TranslationResult(
                text="", source_lang=source_lang, target_lang=target_lang, provider=self.name, model=self.model
            )

        if not self.is_available():
            raise RuntimeError(
                "Apple Translation helper not available. " "Build it with scripts/build-apple-translate.sh"
            )

        payload = {
            "text": text,
            "source": source_lang,
            "target": target_lang,
        }

        helper = self._helper_path()
        try:
            result = subprocess.run(
                [str(helper)], input=json.dumps(payload), text=True, capture_output=True, timeout=30
            )
        except subprocess.TimeoutExpired:
            raise TimeoutError("Apple translation timed out")
        except Exception as e:
            raise RuntimeError(f"Apple translation failed: {e}")

        if result.returncode != 0:
            stderr = result.stderr.strip() or "Unknown error"
            raise RuntimeError(f"Apple translation failed: {stderr}")

        try:
            response = json.loads(result.stdout)
        except Exception as e:
            raise RuntimeError(f"Apple translation failed: invalid response ({e})")

        translated = response.get("text", "").strip()

        return TranslationResult(
            text=translated, source_lang=source_lang, target_lang=target_lang, provider=self.name, model=self.model
        )

    def get_model_status(self) -> dict:
        return {
            "model": self.model,
            "downloaded": True,
            "size_gb": 0,
            "ram_required": "N/A (system)",
            "requires_download": False,
        }

    def download_model(self, progress_callback: Optional[callable] = None) -> bool:
        if progress_callback:
            progress_callback("Apple Translation uses system-managed language packs")
        return True

    def set_model(self, model_id: str) -> None:
        if model_id in self.MODELS:
            self.model = model_id

    def get_current_model(self) -> str:
        return self.model

    def get_models(self) -> list[dict]:
        return [
            {
                "id": model_id,
                "name": config["name"],
                "description": config["description"],
                "size_gb": 0,
                "ram_required": "N/A",
                "category": config.get("category", "balanced"),
                "recommended": config.get("recommended", False),
            }
            for model_id, config in self.MODELS.items()
        ]

    @classmethod
    def get_supported_languages(cls) -> dict[str, str]:
        return cls.SUPPORTED_LANGUAGES.copy()
