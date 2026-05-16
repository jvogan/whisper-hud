"""
Configuration management.

Stores user preferences in a JSON file.
API keys are stored separately via the configured credential storage mode (see keychain.py).
"""

import json
import os
import tempfile
from pathlib import Path
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import List, Optional

from .logging_config import get_logger

logger = get_logger("config")

CONFIG_DIR = Path.home() / ".config" / "whisper-hud"
CONFIG_FILE = CONFIG_DIR / "config.json"


def _backup_corrupted_config() -> Optional[Path]:
    """Back up a corrupted config file without overwriting existing backups."""
    if not CONFIG_FILE.exists():
        return None

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_file = CONFIG_DIR / f"{CONFIG_FILE.name}.bak.{timestamp}"
    suffix = 1
    while backup_file.exists():
        backup_file = CONFIG_DIR / f"{CONFIG_FILE.name}.bak.{timestamp}.{suffix}"
        suffix += 1

    try:
        CONFIG_FILE.replace(backup_file)
        return backup_file
    except Exception as e:
        logger.warning(f"Failed to back up corrupted config: {e}")
        return None


def _ensure_config_permissions() -> None:
    """Tighten config directory/file permissions to user-only access."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        return

    try:
        os.chmod(CONFIG_DIR, 0o700)
    except Exception as e:
        logger.warning(f"Could not set config directory permissions: {e}")

    if CONFIG_FILE.exists():
        try:
            os.chmod(CONFIG_FILE, 0o600)
        except Exception as e:
            logger.warning(f"Could not set config file permissions: {e}")


def _normalize_model_config_values(data: dict) -> None:
    """Migrate stale/removed provider model IDs to the nearest supported values."""
    try:
        from .providers.gemini import GeminiProvider
        from .providers.openai_realtime import OpenAIRealtimeProvider
        from .providers.openai_whisper import OpenAITranscribeProvider
        from .providers.translation.anthropic_translate import AnthropicTranslateProvider
        from .providers.translation.gemini_translate import GeminiTranslateProvider
        from .providers.translation.openai_translate import OpenAITranslateProvider
    except Exception:
        return

    normalizers = {
        "openai_model": OpenAITranscribeProvider.normalize_model_id,
        "openai_realtime_model": OpenAIRealtimeProvider._normalize_model,
        "gemini_model": GeminiProvider.normalize_model_id,
        "openai_translate_model": OpenAITranslateProvider.normalize_model_id,
        "gemini_translate_model": GeminiTranslateProvider.normalize_model_id,
        "anthropic_translate_model": AnthropicTranslateProvider.normalize_model_id,
    }

    for field_name, normalize in normalizers.items():
        current_value = data.get(field_name)
        if not isinstance(current_value, str) or not current_value:
            continue
        normalized_value = normalize(current_value)
        if normalized_value != current_value:
            logger.info("Migrating %s from %s to %s", field_name, current_value, normalized_value)
            data[field_name] = normalized_value


@dataclass
class Config:
    """Application configuration."""

    # Default transcription provider
    # Options: openai, openai_realtime, gemini, apple, whisper_local, parakeet
    default_provider: str = "apple"

    # Default model for each transcription provider
    openai_model: str = "gpt-4o-mini-transcribe"
    openai_realtime_model: str = "gpt-realtime-whisper"
    gemini_model: str = "gemini-3.1-flash-lite"
    apple_model: str = "en-US"
    whisper_local_model: str = "large-v3-turbo"
    parakeet_model: str = "parakeet-tdt-0.6b-v3"

    # Hotkey (stored as key names)
    hotkey: List[str] = field(default_factory=lambda: ["cmd", "shift", "space"])
    hotkey_mode: str = "push_to_talk"  # "push_to_talk" (hold) or "toggle" (press to start/stop)

    # Behavior
    auto_paste: bool = True  # Automatically paste after transcription
    show_hud: bool = True  # Show floating HUD
    show_widget: bool = False  # Show floating widget button
    widget_size: str = "medium"  # Widget size: small, medium, large, xlarge
    widget_position: Optional[dict] = None  # {"x": float, "y": float} for persisted position
    auto_stop: bool = True  # Auto-stop recording after silence
    silence_duration: float = 1.5  # Seconds of silence before auto-stop
    silence_threshold: float = 0.002  # Audio level threshold for silence (below ambient noise)
    max_recording_duration: int = 600  # Max recording duration in seconds (10 min default)
    play_sound: bool = False  # Play sound on completion
    restore_clipboard: bool = True  # Restore clipboard after paste
    show_notifications: bool = True  # Show system notifications
    audio_input_device: Optional[int] = None  # Audio input device ID (None = system default)
    launch_at_login: bool = False  # Launch app at login

    # API key credential storage
    # passphrase: encrypted local file unlocked for current app session
    # keychain: macOS keychain via keyring
    # none: in-memory only (lost on quit)
    credential_storage_mode: str = "passphrase"

    # Translation settings
    translation_enabled: bool = False
    translation_provider: str = "apple"  # apple, ollama, gemini, openai
    translation_model: str = "translategemma-4b"  # Ollama model: 4b, 12b, 27b
    gemini_translate_model: str = "gemini-3.1-flash-lite"  # Gemini translation model
    openai_translate_model: str = "gpt-5.4-mini"  # OpenAI translation model
    anthropic_translate_model: str = "claude-sonnet-4-6"  # Anthropic translation model
    target_language: str = "en"  # Default: English (neutral first-run choice)
    source_language: str = "auto"  # "auto" or specific ISO 639-1 code

    # Stats
    total_transcriptions: int = 0
    total_cost: float = 0.0

    # Setup wizard
    setup_completed: bool = False

    # Ollama automation
    ollama_auto_start: bool = True  # Auto-start ollama serve on app launch

    # Streaming display
    streaming_enabled: bool = False  # Show live streaming display panel

    # Paste target lock
    paste_target_enabled: bool = False  # Lock transcription to specific target
    paste_target_type: str = "focused"  # focused, app, tmux, iterm2, terminal
    paste_target_identifier: str = ""  # App name, tmux session, etc.
    paste_target_return_focus: bool = True  # Return to original app after paste
    paste_target_recent: List[str] = field(default_factory=list)  # Recent targets ["type:id", ...]

    # Recent language selections (for quick access in menus)
    recent_source_languages: List[str] = field(default_factory=list)  # Recent source language codes
    recent_target_languages: List[str] = field(default_factory=list)  # Recent target language codes
    max_recent_languages: int = 5  # Maximum recent languages to remember

    # Transcription history
    history_enabled: bool = False  # Store transcription history
    history_max_items: int = 20  # Maximum number of history items to keep
    history: List[dict] = field(default_factory=list)  # [{text, timestamp, provider, translated}]

    # Privacy settings
    private_mode: bool = False  # No transcription storage at all (overrides history_enabled)
    history_encrypted: bool = False  # Encrypt history at rest using Fernet (AES-256)

    # Widget appearance customization
    widget_appearance: dict = field(
        default_factory=lambda: {
            "theme": "default",
            "colors": {
                "idle": {"background": "#232329", "icon": "#66A5FF", "background_hover": "#383840"},
                "recording": {"background": "#D92626", "icon": "#FFFFFF"},
                "processing": {"background": "#BF8C19", "icon": "#FFFFFF"},
                "success": {"background": "#3FB950", "icon": "#FFFFFF"},
                "error": {"background": "#F85149", "icon": "#FFFFFF"},
            },
            "custom_icon": {
                "enabled": False,
                "path": "",
                "per_state": False,
                "icons": {"idle": "", "recording": "", "processing": "", "success": "", "error": ""},
                "apply_state_tint": True,
                "tint_opacity": 0.3,
                "shape_mode": "auto",  # "auto", "circle", "alpha", "subject"
                "character_pack": None,  # ID of active character pack, if any
            },
        }
    )

    @classmethod
    def load(cls) -> "Config":
        """Load config from disk or return defaults."""
        _ensure_config_permissions()
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    data = json.load(f)

                # Migration: Old silence_threshold default (0.05) was too high for typical mics
                # Real MacBook mic RMS during speech is 0.005-0.03, so old default never detected speech
                if "silence_threshold" in data and data["silence_threshold"] >= 0.03:
                    old_val = data["silence_threshold"]
                    data["silence_threshold"] = 0.005
                    logger.info(
                        f"Migrating silence_threshold from {old_val} to 0.005 "
                        "(old default was too high for typical microphones)"
                    )

                # Migration: preserve existing installs on keychain mode.
                # Fresh installs use passphrase mode by default.
                if "credential_storage_mode" not in data:
                    data["credential_storage_mode"] = "keychain"

                _normalize_model_config_values(data)

                # Handle missing fields gracefully
                return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            except json.JSONDecodeError as e:
                backup_file = _backup_corrupted_config()
                if backup_file is not None:
                    logger.warning(
                        f"Config file contained invalid JSON and was reset to defaults. "
                        f"Backed up corrupted file to {backup_file}: {e}"
                    )
                else:
                    logger.warning(
                        f"Config file contained invalid JSON and was reset to defaults, " f"but backup failed: {e}"
                    )
            except Exception as e:
                logger.warning(f"Failed to load config: {e}")
        return cls()

    def update_from(self, other: "Config") -> None:
        """Update this config instance with values from another Config."""
        for field_name in self.__dataclass_fields__:
            setattr(self, field_name, getattr(other, field_name))

    def save(self) -> bool:
        """Save config to disk."""
        try:
            _ensure_config_permissions()
            fd, tmp_path = tempfile.mkstemp(dir=str(CONFIG_FILE.parent), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(asdict(self), f, indent=2)
                os.replace(tmp_path, str(CONFIG_FILE))
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            _ensure_config_permissions()
            return True
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            return False

    def get_provider_model(self, provider: str) -> str:
        """Get the configured model for a provider."""
        model_map = {
            "openai": self.openai_model,
            "openai_realtime": self.openai_realtime_model,
            "gemini": self.gemini_model,
            "apple": self.apple_model,
            "whisper_local": self.whisper_local_model,
            "parakeet": self.parakeet_model,
        }
        return model_map.get(provider, "")

    def set_provider_model(self, provider: str, model: str) -> None:
        """Set the model for a provider."""
        if provider == "openai":
            self.openai_model = model
        elif provider == "openai_realtime":
            self.openai_realtime_model = model
        elif provider == "gemini":
            self.gemini_model = model
        elif provider == "apple":
            self.apple_model = model
        elif provider == "whisper_local":
            self.whisper_local_model = model
        elif provider == "parakeet":
            self.parakeet_model = model
        self.save()

    def add_transcription_stats(self, cost: float) -> bool:
        """Update transcription statistics unless private mode is active."""
        if self.private_mode:
            return False

        original_total_transcriptions = self.total_transcriptions
        original_total_cost = self.total_cost

        self.total_transcriptions += 1
        self.total_cost += cost
        if self.save():
            return True

        self.total_transcriptions = original_total_transcriptions
        self.total_cost = original_total_cost
        return False

    def reset_stats(self) -> bool:
        """Reset transcription statistics."""
        original_total_transcriptions = self.total_transcriptions
        original_total_cost = self.total_cost
        self.total_transcriptions = 0
        self.total_cost = 0.0
        if self.save():
            return True

        self.total_transcriptions = original_total_transcriptions
        self.total_cost = original_total_cost
        return False

    def add_to_history(self, text: str, provider: str = "", translated: bool = False, original_text: str = "") -> bool:
        """
        Add a transcription to history.

        Args:
            text: The transcribed (and optionally translated) text
            provider: The provider used for transcription
            translated: Whether the text was translated
            original_text: Original text before translation (if translated)
        """
        # Private mode: never store any transcription data
        if self.private_mode:
            return False

        if not self.history_enabled or not text:
            return False

        import time

        # Encrypt text fields if encryption is enabled
        store_text = text
        store_original = original_text
        encrypted_ok = False

        if self.history_encrypted:
            from .encryption import encrypt_text

            encrypted = encrypt_text(text)
            if not encrypted:
                logger.warning("History encryption enabled but failed; skipping history entry")
                return False
            store_text = encrypted
            encrypted_ok = True
            if translated and original_text:
                encrypted_original = encrypt_text(original_text)
                if not encrypted_original:
                    logger.warning("History encryption enabled but failed on original text; skipping history entry")
                    return False
                store_original = encrypted_original

        entry = {
            "text": store_text,
            "timestamp": time.time(),
            "provider": provider,
            "translated": translated,
            "encrypted": encrypted_ok,  # Mark if entry is encrypted
        }
        if translated and store_original:
            entry["original_text"] = store_original

        original_history = [item.copy() if isinstance(item, dict) else item for item in self.history]
        new_history = [entry] + original_history
        if len(new_history) > self.history_max_items:
            new_history = new_history[: self.history_max_items]

        self.history = new_history
        if self.save():
            return True

        self.history = original_history
        return False

    def get_history(self, limit: int = 10) -> List[dict]:
        """
        Get recent history items.

        Automatically decrypts encrypted entries.
        """
        items = self.history[:limit]

        # Decrypt any encrypted entries
        result = []
        for item in items:
            if item.get("encrypted", False):
                from .encryption import decrypt_text

                decrypted_item = item.copy()
                decrypted_text = decrypt_text(item.get("text", ""))
                if decrypted_text:
                    decrypted_item["text"] = decrypted_text
                else:
                    # Decryption failed - key may be missing or changed
                    decrypted_item["text"] = "🔐 Unable to decrypt"
                    decrypted_item["_decryption_failed"] = True

                if item.get("original_text"):
                    decrypted_original = decrypt_text(item["original_text"])
                    if decrypted_original:
                        decrypted_item["original_text"] = decrypted_original
                    else:
                        decrypted_item["original_text"] = "🔐 Unable to decrypt"

                result.append(decrypted_item)
            else:
                result.append(item)

        return result

    def clear_history(self) -> bool:
        """Clear all history."""
        original_history = [item.copy() if isinstance(item, dict) else item for item in self.history]
        self.history = []
        if self.save():
            return True

        self.history = original_history
        return False

    def enable_private_mode(self) -> bool:
        """
        Enable private mode (no transcription storage).

        When enabled:
        - History is cleared and disabled
        - Stored statistics are reset
        - New transcriptions are never saved to disk
        """
        original_private_mode = self.private_mode
        original_history_enabled = self.history_enabled
        original_history = [item.copy() if isinstance(item, dict) else item for item in self.history]
        original_total_transcriptions = self.total_transcriptions
        original_total_cost = self.total_cost

        self.private_mode = True
        self.history_enabled = False
        self.history = []
        self.total_transcriptions = 0
        self.total_cost = 0.0
        if self.save():
            return True

        self.private_mode = original_private_mode
        self.history_enabled = original_history_enabled
        self.history = original_history
        self.total_transcriptions = original_total_transcriptions
        self.total_cost = original_total_cost
        return False

    def disable_private_mode(self) -> bool:
        """Disable private mode."""
        original_private_mode = self.private_mode
        self.private_mode = False
        if self.save():
            return True

        self.private_mode = original_private_mode
        return False

    def enable_history(self, encrypted: bool = True) -> None:
        """Enable history with encryption on by default."""
        self.history_enabled = True
        if encrypted:
            self.history_encrypted = True
        self.save()

    def enable_history_encryption(self) -> bool:
        """
        Enable history encryption.

        Creates a local history-encryption key wrapped by the active passphrase
        session if needed.

        Returns:
            True if encryption was enabled successfully
        """
        from .encryption import is_cryptography_installed, get_or_create_key

        if not is_cryptography_installed():
            logger.warning("Cannot enable encryption: cryptography not installed")
            return False

        original_history = [item.copy() if isinstance(item, dict) else item for item in self.history]
        original_history_encrypted = self.history_encrypted

        # This will create the key if it doesn't exist
        try:
            get_or_create_key()
            migrated_history = self._encrypt_history_entries(self.history)
            if migrated_history is None:
                logger.error("Failed to migrate existing history during encryption enable")
                return False
            self.history = migrated_history
            self.history_encrypted = True
            if not self.save():
                self.history = original_history
                self.history_encrypted = original_history_encrypted
                logger.error("Failed to persist encrypted history configuration")
                return False
            return True
        except Exception as e:
            self.history = original_history
            self.history_encrypted = original_history_encrypted
            logger.error(f"Failed to enable encryption: {e}")
            return False

    def _encrypt_history_entries(self, entries: List[dict]) -> Optional[List[dict]]:
        """Encrypt plaintext history entries without mutating the original list on failure."""
        from .encryption import encrypt_text

        migrated: List[dict] = []
        for item in entries:
            updated = item.copy()
            if updated.get("encrypted", False):
                migrated.append(updated)
                continue

            text = updated.get("text")
            if isinstance(text, str) and text:
                encrypted_text = encrypt_text(text)
                if not encrypted_text:
                    return None
                updated["text"] = encrypted_text

            original_text = updated.get("original_text")
            if isinstance(original_text, str) and original_text:
                encrypted_original = encrypt_text(original_text)
                if not encrypted_original:
                    return None
                updated["original_text"] = encrypted_original

            updated["encrypted"] = True
            updated.pop("_decryption_failed", None)
            migrated.append(updated)

        return migrated

    def merge_imported_config(self, imported: "Config") -> "Config":
        """
        Merge imported settings with runtime-only state preserved from the current config.

        API keys are not part of Config and are handled separately by credential storage.
        """
        imported.total_transcriptions = self.total_transcriptions
        imported.total_cost = self.total_cost

        if imported.private_mode:
            imported.history = []
            imported.history_enabled = False
        else:
            imported.history = list(self.history)

        return imported

    def disable_history_encryption(self) -> None:
        """
        Disable history encryption.

        Note: Existing encrypted entries will remain encrypted but
        can still be read while the matching history passphrase context is unlocked.
        """
        self.history_encrypted = False
        self.save()

    def get_custom_icons_dir(self) -> Path:
        """Get the custom icons directory, creating it if needed."""
        icons_dir = CONFIG_DIR / "custom" / "icons"
        icons_dir.mkdir(parents=True, exist_ok=True)
        return icons_dir

    def add_recent_source_language(self, lang_code: str) -> None:
        """Add a source language to the recent list."""
        if lang_code == "auto":
            return  # Don't track auto-detect
        # Remove if already in list
        if lang_code in self.recent_source_languages:
            self.recent_source_languages.remove(lang_code)
        # Add to front
        self.recent_source_languages.insert(0, lang_code)
        # Trim to max
        self.recent_source_languages = self.recent_source_languages[: self.max_recent_languages]
        self.save()

    def add_recent_target_language(self, lang_code: str) -> None:
        """Add a target language to the recent list."""
        # Remove if already in list
        if lang_code in self.recent_target_languages:
            self.recent_target_languages.remove(lang_code)
        # Add to front
        self.recent_target_languages.insert(0, lang_code)
        # Trim to max
        self.recent_target_languages = self.recent_target_languages[: self.max_recent_languages]
        self.save()

    def get_appearance_colors(self, state: str) -> dict:
        """Get colors for a specific widget state."""
        default_colors = {
            "idle": {"background": "#232329", "icon": "#66A5FF", "background_hover": "#383840"},
            "recording": {"background": "#D92626", "icon": "#FFFFFF"},
            "processing": {"background": "#BF8C19", "icon": "#FFFFFF"},
            "success": {"background": "#3FB950", "icon": "#FFFFFF"},
            "error": {"background": "#F85149", "icon": "#FFFFFF"},
        }
        colors = self.widget_appearance.get("colors", default_colors)
        return colors.get(state, default_colors.get(state, {}))

    def set_appearance_theme(self, theme_id: str, theme_colors: dict) -> None:
        """Apply a theme to the widget appearance."""
        self.widget_appearance["theme"] = theme_id
        self.widget_appearance["colors"] = theme_colors
        self.save()

    def set_appearance_colors(self, state: str, colors: dict) -> None:
        """Set colors for a specific state."""
        if "colors" not in self.widget_appearance:
            self.widget_appearance["colors"] = {}
        self.widget_appearance["colors"][state] = colors
        self.widget_appearance["theme"] = "custom"
        self.save()

    def set_custom_icon(
        self, path: str, apply_tint: bool = True, tint_opacity: float = 0.3, shape_mode: str = "auto"
    ) -> None:
        """Set a custom icon for the widget."""
        self.widget_appearance["custom_icon"] = {
            "enabled": bool(path),
            "path": path,
            "per_state": False,
            "icons": {"idle": "", "recording": "", "processing": "", "success": "", "error": ""},
            "apply_state_tint": apply_tint,
            "tint_opacity": tint_opacity,
            "shape_mode": shape_mode if shape_mode in ("auto", "circle", "alpha", "subject") else "auto",
            "character_pack": None,
        }
        self.save()

    def clear_custom_icon(self) -> None:
        """Remove custom icon settings."""
        self.widget_appearance["custom_icon"] = {
            "enabled": False,
            "path": "",
            "per_state": False,
            "icons": {"idle": "", "recording": "", "processing": "", "success": "", "error": ""},
            "apply_state_tint": True,
            "tint_opacity": 0.3,
            "shape_mode": "auto",
            "character_pack": None,
        }
        self.save()

    def reset_appearance(self) -> None:
        """Reset appearance to default."""
        self.widget_appearance = {
            "theme": "default",
            "colors": {
                "idle": {"background": "#232329", "icon": "#66A5FF", "background_hover": "#383840"},
                "recording": {"background": "#D92626", "icon": "#FFFFFF"},
                "processing": {"background": "#BF8C19", "icon": "#FFFFFF"},
                "success": {"background": "#3FB950", "icon": "#FFFFFF"},
                "error": {"background": "#F85149", "icon": "#FFFFFF"},
            },
            "custom_icon": {
                "enabled": False,
                "path": "",
                "per_state": False,
                "icons": {"idle": "", "recording": "", "processing": "", "success": "", "error": ""},
                "apply_state_tint": True,
                "tint_opacity": 0.3,
                "shape_mode": "auto",
                "character_pack": None,
            },
        }
        self.save()

    def set_custom_icon_shape_mode(self, mode: str) -> None:
        """Set the shape mode for custom icons.

        Args:
            mode: Shape mode - "auto", "circle", "alpha", or "subject"
                - auto: Use alpha if present, else detect subject, else circle
                - circle: Always crop to circle (default behavior)
                - alpha: Use image's alpha channel directly (for PNGs with transparency)
                - subject: AI-powered subject extraction (removes background)
        """
        if mode in ("auto", "circle", "alpha", "subject"):
            if "custom_icon" not in self.widget_appearance:
                self.widget_appearance["custom_icon"] = {}
            self.widget_appearance["custom_icon"]["shape_mode"] = mode
            self.save()

    def export_settings(self, filepath: str) -> bool:
        """
        Export settings to a JSON file.

        Args:
            filepath: Path to export file

        Returns:
            True if export succeeded
        """
        try:
            export_data = {"whisper_hud_export": True, "version": "1.0", "settings": asdict(self)}
            # Remove sensitive/transient data
            export_data["settings"].pop("history", None)
            export_data["settings"].pop("total_transcriptions", None)
            export_data["settings"].pop("total_cost", None)
            # Remove fields that leak local app/session names and filesystem paths
            export_data["settings"].pop("paste_target_identifier", None)
            export_data["settings"].pop("paste_target_recent", None)
            # Strip custom icon filesystem paths from widget_appearance
            widget = export_data["settings"].get("widget_appearance", {})
            custom_icon = widget.get("custom_icon", {})
            if custom_icon:
                custom_icon.pop("path", None)
                icons = custom_icon.get("icons", {})
                for state in list(icons.keys()):
                    icons[state] = ""

            export_path = Path(filepath)
            fd, tmp_path = tempfile.mkstemp(dir=str(export_path.parent), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(export_data, f, indent=2)
                os.replace(tmp_path, filepath)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            try:
                os.chmod(filepath, 0o600)
            except Exception:
                pass
            return True
        except Exception as e:
            logger.error(f"Failed to export settings: {e}")
            return False

    @classmethod
    def import_settings(cls, filepath: str) -> tuple[bool, str, Optional["Config"]]:
        """
        Import settings from a JSON file.

        Args:
            filepath: Path to import file

        Returns:
            Tuple of (success, message, config_or_none)
        """
        try:
            with open(filepath) as f:
                data = json.load(f)

            # Validate it's a WhisperHUD export
            if not data.get("whisper_hud_export"):
                return False, "Not a valid WhisperHUD settings file", None

            settings = data.get("settings", {})
            if not settings:
                return False, "No settings found in file", None
            # Drop sensitive/transient fields even if present in import
            settings.pop("history", None)
            settings.pop("total_transcriptions", None)
            settings.pop("total_cost", None)
            # Drop fields that leak local app/session names and filesystem paths
            settings.pop("paste_target_identifier", None)
            settings.pop("paste_target_recent", None)
            # Strip custom icon filesystem paths from widget_appearance
            widget = settings.get("widget_appearance", {})
            custom_icon = widget.get("custom_icon", {})
            if custom_icon:
                custom_icon.pop("path", None)
                icons = custom_icon.get("icons", {})
                for state in list(icons.keys()):
                    icons[state] = ""

            # Create config from imported settings
            valid_fields = {k: v for k, v in settings.items() if k in cls.__dataclass_fields__}
            imported_config = cls(**valid_fields)

            return True, "Settings imported successfully", imported_config
        except json.JSONDecodeError:
            return False, "Invalid JSON file", None
        except Exception as e:
            logger.error(f"Failed to import settings: {e}")
            return False, f"Import failed: {str(e)}", None
