"""
Main menu bar application using rumps.

This is the heart of the app - coordinates all components:
- Menu bar icon with status indication
- Recording via hotkey
- Transcription via API
- Text insertion via paste
- Settings management
- Streaming display panel
- Setup wizard for onboarding
"""

import os
import rumps
import threading
import time
import weakref
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .logging_config import get_logger
from .recorder import AudioRecorder
from .transcribe import TranscriptionManager
from .translate import TranslationManager
from .providers.base import LiveTranscriptionSession, TranscriptionResult
from .hotkey import HotkeyListener, HotkeyCapture, format_hotkey_display, string_to_key
from .hud import create_hud
from .paste import insert_text, check_accessibility_permission, get_accessibility_error_message, open_accessibility_settings, escape_applescript_string
from .paste_targets import PasteTargetManager, PasteTarget, TargetType
from .config import Config
from .keychain import (
    set_api_key,
    get_api_key,
    delete_api_key,
    get_configured_providers,
    mask_api_key,
    validate_api_key,
    get_storage_mode,
    get_storage_mode_label,
    has_passphrase_store,
    is_passphrase_unlocked,
    unlock_passphrase_store,
    lock_passphrase_store,
    change_passphrase,
    export_api_keys,
    import_api_keys,
    clear_api_keys,
)
from .floating_widget import create_floating_widget
from .streaming_panel import create_streaming_panel
from .setup_wizard import show_setup_wizard
from .branding import MenuBarIcons, APPEARANCE_THEMES, get_theme_colors, get_available_themes
from .image_processor import ImageProcessor
from .character_packs import CharacterPackManager
from .encryption import (
    ensure_history_encryption_unlocked,
    is_history_encryption_unlocked,
    lock_history_encryption,
)

logger = get_logger("app")


class RecordingTurnPhase(Enum):
    """Lifecycle states for one recording turn."""

    IDLE = "idle"
    STARTING = "starting"
    STREAMING = "streaming"
    DEGRADED_BATCH = "degraded_batch"
    STOP_REQUESTED = "stop_requested"
    FINALIZING = "finalizing"


@dataclass
class ActiveTranscriptionTurn:
    """Per-turn runtime state shared across recorder, live provider, and UI callbacks."""

    turn_id: int
    provider_id: str
    phase: RecordingTurnPhase = RecordingTurnPhase.STARTING
    live_session: Optional[LiveTranscriptionSession] = None
    connect_timer: Optional[threading.Timer] = None
    finalize_timer: Optional[threading.Timer] = None
    audio_bytes: bytes = b""
    stop_reason: str = ""
    batch_fallback_started: bool = False
    result_processing_started: bool = False


class WhisperHUDApp(rumps.App):
    """Menu bar application for voice-to-text transcription."""

    # Menu bar emoji states (from branding module)
    ICON_IDLE = MenuBarIcons.IDLE
    ICON_RECORDING = MenuBarIcons.RECORDING
    ICON_PROCESSING = MenuBarIcons.PROCESSING
    ICON_SUCCESS = MenuBarIcons.SUCCESS
    ICON_ERROR = MenuBarIcons.ERROR
    ICON_DOWNLOADING = MenuBarIcons.DOWNLOADING

    def __init__(self):
        super().__init__(
            "WhisperHUD",
            icon=None,
            title=self.ICON_IDLE,
            quit_button=None  # We'll add our own quit
        )

        self._menu_is_open = False
        self._pending_menu_rebuild = False
        self._menu_delegate = None
        self._menu_observer = None
        self._pending_menu_actions: list = []
        self._menu_action_lock = threading.Lock()
        self._menu_notification_center = None
        self._last_menu_close_time = 0.0

        # Ensure alerts are visible for this menu bar app
        self._patch_rumps_alert()

        # Components
        self.config = Config.load()

        # Validate saved audio device is still valid before using it
        from .recorder import is_valid_input_device, get_device_name
        if self.config.audio_input_device is not None:
            if not is_valid_input_device(self.config.audio_input_device):
                saved_device = self.config.audio_input_device
                device_name = get_device_name(saved_device)
                logger.warning(
                    f"Saved audio device '{device_name}' (ID: {saved_device}) is not a valid "
                    "input device. Resetting to system default."
                )
                self.config.audio_input_device = None
                self.config.save()

        self.recorder = AudioRecorder(device=self.config.audio_input_device)
        self.transcriber = TranscriptionManager(self.config)
        self.translator = TranslationManager(self.config)
        self.hud = create_hud()
        self.hud.set_enabled(self.config.show_hud)

        # Clean up any orphaned temp files from crashed sessions
        self._cleanup_orphaned_temp_files()

        # Streaming panel for live display
        self.streaming_panel = create_streaming_panel()
        self.streaming_panel.set_enabled(self.config.streaming_enabled)

        # Paste target manager for directing output to specific apps
        self.paste_target_manager = PasteTargetManager()
        # Cache target lists to avoid slow subprocess calls on every menu open
        self._cached_tmux_sessions: list = []
        self._cached_iterm2_running: bool = False
        self._cached_terminal_running: bool = False
        self._cached_running_apps: list = []
        self._refresh_paste_targets_cache()  # Initial population

        # Image processor for custom widget icons
        self.image_processor = ImageProcessor(self.config)

        # Character pack manager for fun icon themes
        self.character_pack_manager = CharacterPackManager(self.config)

        # Floating widget for click-to-record (with position persistence)
        self.widget = create_floating_widget(
            on_record_start=self._widget_start_recording,
            on_record_stop=self._widget_stop_recording,
            size=self.config.widget_size,
            initial_position=self.config.widget_position,
            on_position_changed=self._save_widget_position
        )

        # Apply appearance to widget and HUD
        self._apply_appearance_to_components()

        # State
        self._is_recording = False
        self._is_downloading = False
        self._lock = threading.Lock()
        self._recording_lock = threading.Lock()  # Dedicated lock for recording operations
        self._turn_counter = 0
        self._active_turn: Optional[ActiveTranscriptionTurn] = None
        self._hotkey_capture: Optional[HotkeyCapture] = None
        self._is_capturing_hotkey = False
        self._setup_wizard = None
        self._level_monitor_thread: Optional[threading.Thread] = None
        self._translation_availability: dict[str, bool] = {}
        self._translation_availability_inflight = False
        self._translation_availability_last_checked = 0.0
        self._menu_rebuild_scheduled = False

        # Attach menu delegate to avoid rebuilding while menu is open
        self._attach_menu_delegate()

        # Build menu
        self._build_menu()

        # Build hotkey set from config
        hotkey_set = self._build_hotkey_set()

        # Start hotkey listener with config settings
        self.hotkey_listener = HotkeyListener(
            on_start=self._start_recording,
            on_stop=self._stop_recording,
            hotkey=hotkey_set,
            mode=self.config.hotkey_mode
        )
        self.hotkey_listener.start()

        # Show floating widget if enabled
        if self.config.show_widget and self.widget:
            self.widget.show()

        # Auto-start Ollama if enabled and translation is configured
        if self.config.ollama_auto_start and self.config.translation_enabled:
            self._auto_start_ollama()

        # Show setup wizard on first run without querying credential storage.
        if not self.config.setup_completed:
            self._show_setup_wizard()
        else:
            if self._should_query_keychain():
                configured = self._get_configured_cloud_providers()
                if not configured and not self._is_passphrase_store_locked():
                    self._show_setup_reminder()

    @staticmethod
    def _is_cloud_transcription_provider(provider_id: str) -> bool:
        """Return True for transcription providers that require API keys."""
        return provider_id in {"openai", "openai_realtime", "gemini"}

    @staticmethod
    def _transcription_credential_provider(provider_id: str) -> str:
        """Map providers to the API key they rely on."""
        if provider_id == "openai_realtime":
            return "openai"
        return provider_id

    @staticmethod
    def _is_cloud_translation_provider(provider_id: str) -> bool:
        """Return True for translation providers that require API keys."""
        return provider_id in {"openai", "gemini", "anthropic"}

    def _should_query_keychain(self) -> bool:
        """
        Only query keychain when cloud providers are actively selected.

        This prevents startup/menu keychain prompts for local-only users.
        """
        if self._is_cloud_transcription_provider(self.config.default_provider):
            return True
        return (
            self.config.translation_enabled
            and self._is_cloud_translation_provider(self.config.translation_provider)
        )

    def _get_configured_cloud_providers(self) -> list[str]:
        """Return configured cloud providers when keychain lookup is needed."""
        if not self._should_query_keychain():
            return []
        return get_configured_providers()

    def _is_transcription_provider_configured(self, provider_id: str, configured: list[str]) -> bool:
        """Check cloud configuration using the provider's backing credential."""
        if not self._is_cloud_transcription_provider(provider_id):
            provider = self.transcriber.get_provider(provider_id)
            return bool(provider and provider.is_configured())
        credential_provider = self._transcription_credential_provider(provider_id)
        return credential_provider in configured

    def _credential_mode(self) -> str:
        """Return active API key storage mode."""
        return get_storage_mode(self.config)

    def _is_passphrase_mode(self) -> bool:
        return self._credential_mode() == "passphrase"

    def _is_passphrase_store_locked(self) -> bool:
        return self._is_passphrase_mode() and has_passphrase_store() and not is_passphrase_unlocked()

    def _reset_cloud_clients(self) -> None:
        """Reset provider clients so credential changes take effect immediately."""
        for provider in ("openai", "openai_realtime", "gemini"):
            self.transcriber.reset_provider(provider)
        for provider in ("openai", "gemini", "anthropic"):
            self.translator.reset_provider(provider)

    def _requires_cloud_credentials(self) -> bool:
        """Return True when current settings require cloud API key access."""
        if self._is_cloud_transcription_provider(self.config.default_provider):
            return True
        return (
            self.config.translation_enabled
            and self._is_cloud_translation_provider(self.config.translation_provider)
        )

    def _ensure_cloud_credentials_ready(self, allow_create: bool = False) -> bool:
        """
        Just-in-time unlock for cloud operations.

        This avoids startup prompts and only asks when the user does an action
        that actually needs locked API keys.
        """
        if not self._is_passphrase_mode():
            return True
        if not self._requires_cloud_credentials():
            return True
        if not self._is_passphrase_store_locked():
            return True
        return self._ensure_passphrase_unlocked(allow_create=allow_create)

    def _ensure_translation_provider_credentials(self, provider_id: str) -> bool:
        """Ensure credentials are unlocked for a specific translation provider."""
        if not self._is_passphrase_mode():
            return True
        if not self._is_cloud_translation_provider(provider_id):
            return True
        if not self._is_passphrase_store_locked():
            return True
        return self._ensure_passphrase_unlocked(allow_create=False)

    def _ensure_history_encryption_session(
        self,
        create_if_missing: bool = False,
        prompt_unlock: bool = False,
    ) -> bool:
        """Ensure history encryption key is unlocked for this app session."""
        if not self.config.history_encrypted:
            return True
        if is_history_encryption_unlocked():
            return True

        ok, message = ensure_history_encryption_unlocked(create_if_missing=create_if_missing)
        if ok:
            return True

        if (
            prompt_unlock
            and self._is_passphrase_mode()
            and self._is_passphrase_store_locked()
            and self._ensure_passphrase_unlocked(allow_create=False)
        ):
            ok, message = ensure_history_encryption_unlocked(create_if_missing=create_if_missing)
            if ok:
                return True

        if prompt_unlock:
            if not self._is_passphrase_mode():
                message = (
                    "History encryption uses passphrase-based unlock.\n\n"
                    "Switch API Key Storage to 'Passphrase (Encrypted Local)', "
                    "then unlock once in this session."
                )
            elif not message:
                message = (
                    "Unlock your passphrase in Privacy & Security, then try again."
                )
            rumps.alert(
                title="History Encryption Locked",
                message=message,
            )
        return False

    def _ensure_passphrase_unlocked(self, allow_create: bool = True) -> bool:
        """Ensure passphrase credential store is unlocked for this app session."""
        if not self._is_passphrase_mode():
            return True
        if is_passphrase_unlocked():
            return True

        if has_passphrase_store():
            passphrase = self._applescript_input_dialog(
                "Unlock API Key Store",
                "Enter your API key storage passphrase.",
                hidden=True,
            )
            if not passphrase:
                return False

            ok, message = unlock_passphrase_store(passphrase)
            if not ok:
                rumps.alert(title="Unlock Failed", message=message)
                return False

            self._ensure_history_encryption_session(create_if_missing=False, prompt_unlock=False)
            self._notify("WhisperHUD", "API Keys Unlocked", "Credential store unlocked for this session.")
            self._schedule_menu_rebuild()
            return True

        if not allow_create:
            rumps.alert(
                title="Passphrase Required",
                message="Create a passphrase first to store API keys securely."
            )
            return False

        first = self._applescript_input_dialog(
            "Create API Key Passphrase",
            (
                "Create a passphrase to encrypt API keys locally.\n\n"
                "You'll enter this passphrase when you restart the app."
            ),
            hidden=True,
        )
        if not first:
            return False

        if len(first) < 8:
            rumps.alert(
                title="Passphrase Too Short",
                message="Use at least 8 characters."
            )
            return False

        second = self._applescript_input_dialog(
            "Confirm Passphrase",
            "Re-enter your passphrase.",
            hidden=True,
        )
        if first != second:
            rumps.alert(title="Passphrase Mismatch", message="The passphrases do not match.")
            return False

        ok, message = unlock_passphrase_store(first)
        if not ok:
            rumps.alert(title="Passphrase Setup Failed", message=message)
            return False

        self._ensure_history_encryption_session(create_if_missing=False, prompt_unlock=False)
        self._notify("WhisperHUD", "Passphrase Ready", "API key storage is encrypted and unlocked.")
        self._schedule_menu_rebuild()
        return True

    def _collect_api_keys_for_mode(self, mode: str) -> Optional[dict[str, str]]:
        """Collect API keys from a specific storage mode for migration."""
        ok, keys, message = export_api_keys(mode=mode)
        if ok:
            return keys

        if mode == "passphrase" and "locked" in message.lower():
            if not self._ensure_passphrase_unlocked():
                return None
            ok, keys, message = export_api_keys(mode=mode)
            if ok:
                return keys

        rumps.alert(
            title="Storage Error",
            message=message or "Could not access existing API keys."
        )
        return None

    def _set_credential_storage_mode(self, mode: str) -> None:
        """Switch API key credential storage mode and migrate keys."""
        target_mode = mode if mode in {"passphrase", "keychain", "none"} else "passphrase"
        current_mode = self._credential_mode()
        if target_mode == current_mode:
            return

        if target_mode != "passphrase" and self.config.history_encrypted:
            response = rumps.alert(
                title="History Encryption Uses Passphrase",
                message=(
                    "History encryption is tied to passphrase unlock for this app session.\n\n"
                    "If you switch API key storage away from passphrase, encrypted history "
                    "will stay locked until you switch back and unlock.\n\n"
                    "Switch API key storage anyway?"
                ),
                ok="Switch Anyway",
                cancel="Cancel",
            )
            if response != 1:
                return

        existing_keys = self._collect_api_keys_for_mode(current_mode)
        if existing_keys is None:
            return

        self.config.credential_storage_mode = target_mode
        self.config.save()

        if target_mode == "passphrase" and not self._ensure_passphrase_unlocked():
            self.config.credential_storage_mode = current_mode
            self.config.save()
            return

        ok, message = import_api_keys(existing_keys, mode=target_mode, replace=True)
        if not ok:
            self.config.credential_storage_mode = current_mode
            self.config.save()
            rumps.alert(
                title="Storage Switch Failed",
                message=message or "Could not migrate API keys to the selected mode."
            )
            return

        cleanup_ok = True
        cleanup_message = ""
        if current_mode != target_mode:
            cleanup_ok, cleanup_message = clear_api_keys(mode=current_mode)

        if target_mode != "passphrase":
            lock_passphrase_store()
            lock_history_encryption()

        self._reset_cloud_clients()
        self._schedule_menu_rebuild()
        if not cleanup_ok:
            logger.warning(
                "Credential storage switched to %s, but cleanup of %s failed: %s",
                target_mode,
                current_mode,
                cleanup_message,
            )
            rumps.alert(
                title="Previous Keys Still Stored",
                message=(
                    "WhisperHUD switched to the new storage mode and copied your API keys, "
                    "but it could not remove the old copies.\n\n"
                    f"Previous storage: {get_storage_mode_label(current_mode)}\n"
                    f"Details: {cleanup_message}"
                ),
            )
        self._notify(
            "WhisperHUD",
            "Credential Storage Updated",
            f"Now using: {get_storage_mode_label(target_mode)}"
        )

    def _unlock_api_key_store(self, _):
        """Unlock passphrase-based API key storage."""
        if not self._is_passphrase_mode():
            rumps.alert(title="Not Needed", message="Current storage mode does not require unlocking.")
            return
        self._ensure_passphrase_unlocked()

    def _lock_api_key_store(self, _):
        """Lock passphrase-based API key storage."""
        if not self._is_passphrase_mode():
            return
        lock_passphrase_store()
        lock_history_encryption()
        self._reset_cloud_clients()
        self._schedule_menu_rebuild()
        self._notify("WhisperHUD", "API Keys Locked", "Passphrase store locked for this session.")

    def _change_api_key_passphrase(self, _):
        """Change passphrase used for encrypted API key storage."""
        if not self._is_passphrase_mode():
            rumps.alert(
                title="Unavailable",
                message="Switch to Passphrase storage mode first."
            )
            return

        if not has_passphrase_store():
            if not self._ensure_passphrase_unlocked(allow_create=True):
                return
            return

        current = self._applescript_input_dialog(
            "Current Passphrase",
            "Enter your current passphrase.",
            hidden=True,
        )
        if not current:
            return

        new_one = self._applescript_input_dialog(
            "New Passphrase",
            "Enter a new passphrase (8+ characters).",
            hidden=True,
        )
        if not new_one:
            return
        if len(new_one) < 8:
            rumps.alert(title="Passphrase Too Short", message="Use at least 8 characters.")
            return

        new_two = self._applescript_input_dialog(
            "Confirm New Passphrase",
            "Re-enter your new passphrase.",
            hidden=True,
        )
        if new_one != new_two:
            rumps.alert(title="Passphrase Mismatch", message="The passphrases do not match.")
            return

        ok, message = change_passphrase(current, new_one)
        if ok:
            self._notify("WhisperHUD", "Passphrase Updated", "API key storage passphrase has been changed.")
            self._schedule_menu_rebuild()
        else:
            rumps.alert(title="Passphrase Update Failed", message=message)

    def _build_menu(self):
        """Build the menu bar menu."""
        # Ensure UI updates happen on the main thread
        if threading.current_thread() is not threading.main_thread():
            try:
                from PyObjCTools import AppHelper
                AppHelper.callAfter(self._build_menu)
                return
            except Exception:
                pass

        self._log_menu_trace("Menu rebuild requested")

        if self._menu_is_open:
            with self._menu_action_lock:
                self._pending_menu_rebuild = True
            self._log_menu_trace("Menu rebuild deferred (menu open)")
            logger.debug("Menu rebuild deferred (menu open)")
            return

        # Clear rumps callback registry for existing menu items to avoid leaks
        self._clear_menu_callback_registry(self.menu)

        self.menu.clear()

        # Status header with clear status icons
        configured = self._get_configured_cloud_providers()
        provider_name = self._get_provider_display_name(self.config.default_provider)
        current_provider = self.transcriber.get_provider(self.config.default_provider)
        provider_is_cloud = self._is_cloud_transcription_provider(self.config.default_provider)
        cloud_keys_locked = provider_is_cloud and self._is_passphrase_store_locked()
        provider_ready = (
            self._is_transcription_provider_configured(self.config.default_provider, configured)
            if provider_is_cloud
            else bool(current_provider and current_provider.is_configured())
        )

        if self._is_downloading:
            status = "⬇️ Downloading model..."
        elif cloud_keys_locked:
            status = f"🔒 {provider_name} key locked"
        elif provider_ready:
            status = f"✓ Ready • {provider_name}"
        elif provider_is_cloud:
            status = f"⚠️ {provider_name} needs setup"
        elif configured:
            # Has some providers but current one needs setup
            status = f"⚠️ {provider_name} needs setup"
        else:
            status = "⚠️ No provider configured"

        self.menu.add(rumps.MenuItem(status, callback=None))

        # Show paste target status if locked to a specific target
        target_enabled = self.config.paste_target_enabled and self.config.paste_target_type != "focused"
        if target_enabled:
            target_name = self._get_paste_target_display_name()
            self.menu.add(rumps.MenuItem(f"📍 Output → {target_name}", callback=None))

        self.menu.add(rumps.separator)

        # === Combined Provider/Model Selection ===
        provider_menu = rumps.MenuItem("Provider")
        providers = self.transcriber.get_available_providers(configured_providers=configured)
        current_provider_id = self.config.default_provider
        current_provider_obj = self.transcriber.get_provider(current_provider_id)
        current_model_id = current_provider_obj.get_current_model() if current_provider_obj else ""

        # Cloud providers with model submenus
        provider_menu.add(rumps.MenuItem("── Cloud ──", callback=None))
        for p in providers:
            if p["category"] != "cloud":
                continue
            is_configured = p["configured"]
            is_provider_selected = p["id"] == current_provider_id

            # Status icons: ✓ ready, ⚠️ needs API key
            status_icon = "✓" if is_configured else "⚠️"
            prefix = "● " if is_provider_selected else "   "

            # Create provider submenu with its models
            provider_obj = self.transcriber.get_provider(p["id"])
            provider_models = provider_obj.get_models() if provider_obj else []

            if len(provider_models) > 1:
                # Multiple models - create submenu
                provider_submenu = rumps.MenuItem(f"{prefix}{p['name']} {status_icon}")
                for model in provider_models:
                    is_model_selected = is_provider_selected and model["id"] == current_model_id
                    model_prefix = "● " if is_model_selected else "   "
                    suffix = " ★" if model.get("recommended") else ""
                    provider_submenu.add(rumps.MenuItem(
                        f"{model_prefix}{model['name']}{suffix}",
                        callback=lambda sender, pid=p["id"], mid=model["id"]: self._select_provider_and_model(pid, mid)
                    ))
                provider_menu.add(provider_submenu)
            elif len(provider_models) == 1:
                # Single model - just select provider directly
                model = provider_models[0]
                provider_menu.add(rumps.MenuItem(
                    f"{prefix}{p['name']} {status_icon}",
                    callback=lambda sender, pid=p["id"], mid=model["id"]: self._select_provider_and_model(pid, mid)
                ))
            else:
                # No models defined
                provider_menu.add(rumps.MenuItem(
                    f"{prefix}{p['name']} {status_icon}",
                    callback=lambda sender, pid=p["id"]: self._select_provider(pid)
                ))

        provider_menu.add(rumps.separator)

        # Local providers with model submenus
        provider_menu.add(rumps.MenuItem("── Local ──", callback=None))
        for p in providers:
            if p["category"] != "local":
                continue
            is_configured = p["configured"]
            is_provider_selected = p["id"] == current_provider_id

            # Status icons: ✓ ready, ⬇️ needs download, ⚠️ other issue
            if is_configured:
                status_icon = "✓"
            elif p.get("requires_download", False):
                status_icon = "⬇️"
            else:
                status_icon = "⚠️"

            prefix = "● " if is_provider_selected else "   "
            name = p["name"]
            if p.get("requires_download", False) and not is_configured:
                name = f"{name} [download]"

            # Create provider submenu with its models
            provider_obj = self.transcriber.get_provider(p["id"])
            provider_models = provider_obj.get_models() if provider_obj else []

            if len(provider_models) > 1:
                # Multiple models - create submenu with categories
                provider_submenu = rumps.MenuItem(f"{prefix}{name} {status_icon}")

                # Check if models have categories
                has_categories = any(m.get("category") for m in provider_models)
                if has_categories:
                    categories = {"speed": [], "balanced": [], "quality": []}
                    for model in provider_models:
                        cat = model.get("category", "balanced")
                        if cat in categories:
                            categories[cat].append(model)
                        else:
                            categories["balanced"].append(model)

                    category_labels = {"speed": "── Fast ──", "balanced": "── Balanced ──", "quality": "── Quality ──"}
                    for cat_id in ["speed", "balanced", "quality"]:
                        cat_models = categories[cat_id]
                        if not cat_models:
                            continue
                        provider_submenu.add(rumps.MenuItem(category_labels[cat_id], callback=None))
                        for model in cat_models:
                            is_model_selected = is_provider_selected and model["id"] == current_model_id
                            model_prefix = "● " if is_model_selected else "   "
                            downloaded = model.get('downloaded', True)
                            suffix = " ★" if model.get("recommended") else ""
                            if not downloaded:
                                suffix += " [download]"
                            provider_submenu.add(rumps.MenuItem(
                                f"{model_prefix}{model['name']}{suffix}",
                                callback=lambda sender, pid=p["id"], mid=model["id"], dl=downloaded, prov=p: self._select_provider_model_or_download(pid, mid, dl, prov)
                            ))
                else:
                    for model in provider_models:
                        is_model_selected = is_provider_selected and model["id"] == current_model_id
                        model_prefix = "● " if is_model_selected else "   "
                        downloaded = model.get('downloaded', True)
                        suffix = " ★" if model.get("recommended") else ""
                        if not downloaded:
                            suffix += " [download]"
                        provider_submenu.add(rumps.MenuItem(
                            f"{model_prefix}{model['name']}{suffix}",
                            callback=lambda sender, pid=p["id"], mid=model["id"], dl=downloaded, prov=p: self._select_provider_model_or_download(pid, mid, dl, prov)
                        ))

                provider_menu.add(provider_submenu)
            else:
                # Single or no models - select provider directly
                provider_menu.add(rumps.MenuItem(
                    f"{prefix}{name} {status_icon}",
                    callback=lambda sender, pid=p["id"], prov=p: self._select_or_download_provider(pid, prov)
                ))

        self.menu.add(provider_menu)

        self.menu.add(rumps.separator)

        # === API Keys ===
        keys_menu = rumps.MenuItem("API Keys")
        credential_mode = self._credential_mode()
        keys_menu.add(rumps.MenuItem(f"Storage: {get_storage_mode_label(credential_mode)}", callback=None))
        if credential_mode == "passphrase":
            if self._is_passphrase_store_locked():
                keys_menu.add(rumps.MenuItem("Unlock API key store...", callback=self._unlock_api_key_store))
            elif is_passphrase_unlocked():
                keys_menu.add(rumps.MenuItem("Lock API key store", callback=self._lock_api_key_store))
            else:
                keys_menu.add(rumps.MenuItem("Create passphrase...", callback=self._unlock_api_key_store))
        keys_menu.add(rumps.separator)

        passphrase_locked = self._is_passphrase_store_locked()
        defer_keychain_reads = credential_mode == "keychain" and not self._should_query_keychain()

        if defer_keychain_reads:
            openai_status = "Deferred"
            gemini_status = "Deferred"
            anthropic_status = "Deferred"
        else:
            openai_key = None if passphrase_locked else get_api_key("openai")
            openai_status = "Locked" if passphrase_locked else (mask_api_key(openai_key) if openai_key else "Not set")

            gemini_key = None if passphrase_locked else get_api_key("gemini")
            gemini_status = "Locked" if passphrase_locked else (mask_api_key(gemini_key) if gemini_key else "Not set")

            anthropic_key = None if passphrase_locked else get_api_key("anthropic")
            anthropic_status = "Locked" if passphrase_locked else (
                mask_api_key(anthropic_key) if anthropic_key else "Not set"
            )

        # OpenAI
        keys_menu.add(rumps.MenuItem(
            f"OpenAI: {openai_status}",
            callback=self._set_openai_key
        ))

        # Gemini
        keys_menu.add(rumps.MenuItem(
            f"Gemini: {gemini_status}",
            callback=self._set_gemini_key
        ))

        # Anthropic
        keys_menu.add(rumps.MenuItem(
            f"Anthropic: {anthropic_status}",
            callback=self._set_anthropic_key
        ))

        if defer_keychain_reads:
            keys_menu.add(rumps.separator)
            keys_menu.add(rumps.MenuItem("Keychain lookup deferred until cloud mode", callback=None))

        if credential_mode == "none":
            keys_menu.add(rumps.separator)
            keys_menu.add(rumps.MenuItem("Session-only mode: keys are not saved to disk", callback=None))

        self.menu.add(keys_menu)

        self.menu.add(rumps.separator)

        # === Settings ===
        settings_menu = rumps.MenuItem("Settings")

        settings_menu.add(rumps.MenuItem(
            f"{'✓ ' if self.config.show_widget else '   '}Show floating button",
            callback=self._toggle_widget
        ))

        # Widget size submenu
        size_menu = rumps.MenuItem("   Button size")
        for size_id, size_name in [("small", "Small"), ("medium", "Medium"), ("large", "Large"), ("xlarge", "Extra Large")]:
            is_selected = self.config.widget_size == size_id
            prefix = "● " if is_selected else "   "
            size_menu.add(rumps.MenuItem(
                f"{prefix}{size_name}",
                callback=lambda sender, s=size_id: self._set_widget_size(s)
            ))
        settings_menu.add(size_menu)

        settings_menu.add(rumps.separator)

        settings_menu.add(rumps.MenuItem(
            f"{'✓ ' if self.config.show_hud else '   '}Show HUD overlay",
            callback=self._toggle_hud
        ))
        settings_menu.add(rumps.MenuItem(
            f"{'✓ ' if self.config.auto_stop else '   '}Auto-stop on silence",
            callback=self._toggle_auto_stop
        ))

        # Max recording duration submenu
        max_dur_menu = rumps.MenuItem("Max recording duration")
        duration_options = [
            (60, "1 minute"),
            (120, "2 minutes"),
            (300, "5 minutes"),
            (600, "10 minutes"),
            (900, "15 minutes"),
            (1800, "30 minutes"),
        ]
        for seconds, label in duration_options:
            is_selected = self.config.max_recording_duration == seconds
            prefix = "● " if is_selected else "   "
            max_dur_menu.add(rumps.MenuItem(
                f"{prefix}{label}",
                callback=lambda s, sec=seconds: self._set_max_duration(sec)
            ))
        settings_menu.add(max_dur_menu)

        settings_menu.add(rumps.MenuItem(
            f"{'✓ ' if self.config.auto_paste else '   '}Auto-paste text",
            callback=self._toggle_auto_paste
        ))
        settings_menu.add(rumps.MenuItem(
            f"{'✓ ' if self.config.restore_clipboard else '   '}Restore clipboard",
            callback=self._toggle_restore_clipboard
        ))
        # History toggle (disabled in private mode)
        if self.config.private_mode:
            settings_menu.add(rumps.MenuItem(
                "   Save transcription history (disabled in private mode)",
                callback=None
            ))
        else:
            settings_menu.add(rumps.MenuItem(
                f"{'✓ ' if self.config.history_enabled else '   '}Save transcription history",
                callback=self._toggle_history
            ))
        settings_menu.add(rumps.MenuItem(
            f"{'✓ ' if self.config.play_sound else '   '}Play sound on completion",
            callback=self._toggle_play_sound
        ))

        settings_menu.add(rumps.separator)

        # === Privacy Settings ===
        privacy_menu = rumps.MenuItem("Privacy & Security")

        # Private mode - maximum privacy option
        if self.config.private_mode:
            privacy_menu.add(rumps.MenuItem(
                "✓ Private Mode enabled",
                callback=None
            ))
            privacy_menu.add(rumps.MenuItem(
                "   Turn off Private Mode",
                callback=self._toggle_private_mode
            ))
        else:
            privacy_menu.add(rumps.MenuItem(
                "🔒 Enable Private Mode...",
                callback=self._toggle_private_mode
            ))
            privacy_menu.add(rumps.MenuItem(
                "   No transcriptions saved to disk",
                callback=None
            ))

        privacy_menu.add(rumps.separator)

        # API key credential storage mode
        storage_menu = rumps.MenuItem("API Key Storage")
        current_storage_mode = self._credential_mode()
        mode_items = [
            ("passphrase", "Passphrase (Encrypted Local)"),
            ("keychain", "macOS Keychain"),
            ("none", "Session Only (No Persistence)"),
        ]
        for mode_id, mode_label in mode_items:
            prefix = "● " if current_storage_mode == mode_id else "   "
            storage_menu.add(rumps.MenuItem(
                f"{prefix}{mode_label}",
                callback=lambda s, m=mode_id: self._set_credential_storage_mode(m)
            ))

        if current_storage_mode == "passphrase":
            storage_menu.add(rumps.separator)
            if self._is_passphrase_store_locked():
                storage_menu.add(rumps.MenuItem("Unlock...", callback=self._unlock_api_key_store))
            elif is_passphrase_unlocked():
                storage_menu.add(rumps.MenuItem("Lock now", callback=self._lock_api_key_store))
                storage_menu.add(rumps.MenuItem("Change passphrase...", callback=self._change_api_key_passphrase))
            else:
                storage_menu.add(rumps.MenuItem("Create passphrase...", callback=self._unlock_api_key_store))

        privacy_menu.add(storage_menu)

        privacy_menu.add(rumps.separator)

        # Encrypt history - only when not in private mode
        if self.config.private_mode:
            privacy_menu.add(rumps.MenuItem(
                "🔐 Encryption (not needed in Private Mode)",
                callback=None
            ))
        else:
            from .encryption import is_cryptography_installed
            if self.config.history_encrypted:
                privacy_menu.add(rumps.MenuItem(
                    "✓ History encryption enabled",
                    callback=None
                ))
                privacy_menu.add(rumps.MenuItem(
                    "   Turn off encryption...",
                    callback=self._toggle_history_encryption
                ))
            elif is_cryptography_installed():
                privacy_menu.add(rumps.MenuItem(
                    "🔐 Encrypt saved history...",
                    callback=self._toggle_history_encryption
                ))
                privacy_menu.add(rumps.MenuItem(
                    "   Protects transcriptions at rest",
                    callback=None
                ))
            else:
                privacy_menu.add(rumps.MenuItem(
                    "🔐 Set up encryption...",
                    callback=self._setup_encryption
                ))
                privacy_menu.add(rumps.MenuItem(
                    "   One-time setup required",
                    callback=None
                ))

        settings_menu.add(privacy_menu)
        settings_menu.add(rumps.MenuItem(
            f"{'✓ ' if self.config.show_notifications else '   '}Show notifications",
            callback=self._toggle_notifications
        ))

        settings_menu.add(rumps.separator)

        settings_menu.add(rumps.MenuItem(
            f"{'✓ ' if self.config.streaming_enabled else '   '}Live streaming display",
            callback=self._toggle_streaming
        ))

        settings_menu.add(rumps.separator)

        # === Audio Input Device ===
        from .recorder import get_input_devices
        devices = get_input_devices()
        device_menu = rumps.MenuItem("Audio Input Device")

        # System default option
        is_default = self.config.audio_input_device is None
        device_menu.add(rumps.MenuItem(
            f"{'● ' if is_default else '   '}System Default",
            callback=lambda s: self._set_audio_device(None)
        ))

        device_menu.add(rumps.separator)

        # List available devices
        for device in devices:
            is_selected = self.config.audio_input_device == device['id']
            prefix = "● " if is_selected else "   "
            # Truncate long device names
            name = device['name'][:35] + "..." if len(device['name']) > 38 else device['name']
            device_menu.add(rumps.MenuItem(
                f"{prefix}{name}",
                callback=lambda s, d=device['id']: self._set_audio_device(d)
            ))

        settings_menu.add(device_menu)

        settings_menu.add(rumps.separator)

        # === Launch at Login ===
        from .launch_agent import is_launch_at_login_enabled
        launch_enabled = is_launch_at_login_enabled()
        settings_menu.add(rumps.MenuItem(
            f"{'✓ ' if launch_enabled else '   '}Launch at login",
            callback=self._toggle_launch_at_login
        ))

        settings_menu.add(rumps.separator)

        # === Appearance Submenu ===
        appearance_menu = rumps.MenuItem("Appearance")

        # Theme header
        appearance_menu.add(rumps.MenuItem("── Themes ──", callback=None))

        # Get current theme
        current_theme = self.config.widget_appearance.get("theme", "default")

        # Add theme options
        for theme_id, theme_name in get_available_themes():
            is_selected = current_theme == theme_id
            prefix = "● " if is_selected else "   "
            appearance_menu.add(rumps.MenuItem(
                f"{prefix}{theme_name}",
                callback=lambda s, tid=theme_id: self._apply_theme(tid)
            ))

        appearance_menu.add(rumps.separator)

        # === Character Packs ===
        appearance_menu.add(rumps.MenuItem("── Character Packs ──", callback=None))

        # Get available packs
        available_packs = self.character_pack_manager.get_pack_for_menu()
        current_pack_id = self.character_pack_manager.get_current_pack_id()

        # Default (no pack) option
        is_default = current_pack_id is None
        appearance_menu.add(rumps.MenuItem(
            f"{'● ' if is_default else '   '}Default (circle icon)",
            callback=self._clear_character_pack
        ))

        # Add each available pack
        for pack in available_packs:
            is_selected = pack["active"]
            prefix = "● " if is_selected else "   "
            appearance_menu.add(rumps.MenuItem(
                f"{prefix}{pack['name']}",
                callback=lambda s, pid=pack["id"]: self._apply_character_pack(pid)
            ))

        appearance_menu.add(rumps.separator)

        # Create new pack option
        appearance_menu.add(rumps.MenuItem(
            "Create Character Pack...",
            callback=self._open_pack_creator
        ))

        appearance_menu.add(rumps.separator)

        # Customize option
        appearance_menu.add(rumps.MenuItem(
            "Customize Colors & Icon...",
            callback=self._open_appearance_editor
        ))

        # Reset option
        appearance_menu.add(rumps.MenuItem(
            "Reset to Default",
            callback=self._reset_appearance
        ))

        settings_menu.add(appearance_menu)

        self.menu.add(settings_menu)

        self.menu.add(rumps.separator)

        # === Paste Target ===
        # Show current target in menu title for quick visibility
        target_enabled = self.config.paste_target_enabled and self.config.paste_target_type != "focused"

        # Check if configured target is still available (use cached data for speed)
        target_stale = False
        if target_enabled:
            target_stale = not self._is_target_available_cached(
                self.config.paste_target_type,
                self.config.paste_target_identifier
            )

        if target_enabled:
            target_display = self._get_paste_target_display_name()
            if target_stale:
                paste_target_menu = rumps.MenuItem(f"Paste Target → {target_display} ⚠️")
            else:
                paste_target_menu = rumps.MenuItem(f"Paste Target → {target_display}")
        else:
            paste_target_menu = rumps.MenuItem("Paste Target")

        # Current status at top
        if target_enabled:
            if target_stale:
                paste_target_menu.add(rumps.MenuItem(
                    f"⚠️ Target unavailable: {self._get_paste_target_display_name()}",
                    callback=None
                ))
                paste_target_menu.add(rumps.MenuItem(
                    "   Will use focused window as fallback",
                    callback=None
                ))
            else:
                paste_target_menu.add(rumps.MenuItem(
                    f"📍 Locked to: {self._get_paste_target_display_name()}",
                    callback=None
                ))
            paste_target_menu.add(rumps.MenuItem(
                "   Disable target lock",
                callback=self._disable_paste_target
            ))
            paste_target_menu.add(rumps.separator)

        # Recent targets first (most likely what user wants)
        recent_targets = self._get_valid_recent_targets()
        if recent_targets:
            paste_target_menu.add(rumps.MenuItem("── Quick Select ──", callback=None))
            for target_key in recent_targets[:4]:  # Show up to 4 recent
                target_type, target_id = target_key.split(":", 1)
                is_selected = (target_enabled
                               and self.config.paste_target_type == target_type
                               and self.config.paste_target_identifier == target_id)
                display_name = self._format_target_for_menu(target_type, target_id)
                paste_target_menu.add(rumps.MenuItem(
                    f"{'● ' if is_selected else '   '}{display_name}",
                    callback=lambda s, t=target_type, i=target_id: self._set_paste_target(t, i)
                ))
            paste_target_menu.add(rumps.separator)

        # Focused (default) - selecting this disables target lock
        is_focused = not target_enabled
        paste_target_menu.add(rumps.MenuItem(
            f"{'● ' if is_focused else '   '}Focused Window (default)",
            callback=lambda s: self._set_paste_target("focused", "", notify=False)
        ))

        # tmux sessions (if any) - these don't require focus change
        tmux_sessions = self._cached_tmux_sessions if hasattr(self, '_cached_tmux_sessions') else []
        if tmux_sessions:
            paste_target_menu.add(rumps.MenuItem("── tmux (no focus change) ──", callback=None))
            for session in tmux_sessions:
                is_selected = (target_enabled and self.config.paste_target_type == "tmux"
                               and self.config.paste_target_identifier == session)
                paste_target_menu.add(rumps.MenuItem(
                    f"{'● ' if is_selected else '   '}{session}",
                    callback=lambda s, sess=session: self._set_paste_target("tmux", sess)
                ))

        # iTerm2 (no focus change - uses AppleScript write)
        has_iterm = hasattr(self, '_cached_iterm2_running') and self._cached_iterm2_running
        if has_iterm:
            is_selected = target_enabled and self.config.paste_target_type == "iterm2"
            paste_target_menu.add(rumps.MenuItem(
                f"{'● ' if is_selected else '   '}iTerm2 (no focus change)",
                callback=lambda s: self._set_paste_target("iterm2", "iTerm2")
            ))

        # Terminal.app (requires focus change, but kept for compatibility)
        has_terminal = hasattr(self, '_cached_terminal_running') and self._cached_terminal_running
        if has_terminal:
            is_selected = target_enabled and self.config.paste_target_type == "terminal"
            paste_target_menu.add(rumps.MenuItem(
                f"{'● ' if is_selected else '   '}Terminal.app",
                callback=lambda s: self._set_paste_target("terminal", "Terminal")
            ))

        # Running apps - use submenu if more than 8 apps
        running_apps = self._cached_running_apps if hasattr(self, '_cached_running_apps') else []
        # Filter out terminals since they have special handling above
        running_apps = [a for a in running_apps if a not in ("iTerm2", "Terminal")]

        if running_apps:
            if len(running_apps) <= 8:
                # Show directly in menu for quick access
                paste_target_menu.add(rumps.MenuItem("── Apps ──", callback=None))
                for app in running_apps:
                    is_selected = (target_enabled and self.config.paste_target_type == "app"
                                   and self.config.paste_target_identifier == app)
                    paste_target_menu.add(rumps.MenuItem(
                        f"{'● ' if is_selected else '   '}{app}",
                        callback=lambda s, a=app: self._set_paste_target("app", a)
                    ))
            else:
                # Use submenu to keep main menu clean
                apps_submenu = rumps.MenuItem(f"Apps ({len(running_apps)} running)")
                for app in running_apps:
                    is_selected = (target_enabled and self.config.paste_target_type == "app"
                                   and self.config.paste_target_identifier == app)
                    apps_submenu.add(rumps.MenuItem(
                        f"{'● ' if is_selected else '   '}{app}",
                        callback=lambda s, a=app: self._set_paste_target("app", a)
                    ))
                paste_target_menu.add(apps_submenu)

        # Settings for app targets (only show when an app target is selected)
        if target_enabled and self.config.paste_target_type == "app":
            paste_target_menu.add(rumps.separator)
            paste_target_menu.add(rumps.MenuItem(
                f"{'✓ ' if self.config.paste_target_return_focus else '   '}Return focus after paste",
                callback=self._toggle_paste_return_focus
            ))

        # Refresh option
        paste_target_menu.add(rumps.separator)
        paste_target_menu.add(rumps.MenuItem("⟳ Refresh targets", callback=self._refresh_paste_targets))

        self.menu.add(paste_target_menu)

        self.menu.add(rumps.separator)

        # === Translation ===
        translation_menu = rumps.MenuItem("Translation")

        # Enable/disable toggle
        translation_menu.add(rumps.MenuItem(
            f"{'✓ ' if self.config.translation_enabled else '   '}Enable translation",
            callback=self._toggle_translation
        ))

        translation_menu.add(rumps.separator)

        current_trans_provider = self.translator.get_current_provider()
        current_trans_model = self.translator.get_current_model()
        current_trans_provider_name = self._get_provider_display_name(current_trans_provider)

        if not self.config.translation_enabled:
            translation_menu.add(rumps.MenuItem("Translation is currently off", callback=None))
            translation_menu.add(rumps.MenuItem(
                f"Current selection: {current_trans_provider_name} ({current_trans_model})",
                callback=None,
            ))
            translation_menu.add(rumps.MenuItem(
                "Enable translation to choose provider, model, and languages",
                callback=None,
            ))
        else:
            # Combined Provider/Model submenu - hovering shows models as submenu
            trans_provider_menu = rumps.MenuItem("Provider & model")
            trans_provider_menu.add(rumps.MenuItem("Legend: ✓ ready  ○ needs setup  … checking", callback=None))
            trans_provider_menu.add(rumps.separator)
            trans_providers = self.translator.get_available_providers(
                check_availability=False,
                availability_override=self._translation_availability
            )
            provider_ids = [tp["id"] for tp in trans_providers]

            # Refresh translation availability in background to avoid UI blocking
            if not self._translation_availability_inflight:
                now = time.time()
                if now - self._translation_availability_last_checked > 10.0:
                    self._translation_availability_inflight = True
                    self._translation_availability_last_checked = now

                    should_check_cloud_translation = (
                        self.config.translation_enabled
                        and self._is_cloud_translation_provider(current_trans_provider)
                    )

                    def _check_translation_availability():
                        results = {}
                        for pid in provider_ids:
                            if (
                                self._is_cloud_translation_provider(pid)
                                and not should_check_cloud_translation
                            ):
                                continue
                            provider = self.translator.get_provider(pid)
                            try:
                                results[pid] = provider.is_available() if provider else False
                            except Exception:
                                results[pid] = False

                        def _apply():
                            self._translation_availability.update(results)
                            self._translation_availability_inflight = False
                            # Don't rebuild menu here - it causes greying while menu is open
                            # Menu will refresh with new availability next time it's opened

                        try:
                            from PyObjCTools import AppHelper
                            AppHelper.callAfter(_apply)
                        except Exception:
                            _apply()

                    threading.Thread(target=_check_translation_availability, daemon=True).start()

            # Local translation providers with model submenus
            trans_provider_menu.add(rumps.MenuItem("── Local ──", callback=None))
            for tp in trans_providers:
                if tp["category"] != "local":
                    continue
                is_provider_selected = current_trans_provider == tp["id"]
                is_available = tp["available"]
                provider_prefix = "● " if is_provider_selected else "   "
                if is_available is None:
                    status = "…"
                else:
                    status = "✓" if is_available else "○"

                # Create provider submenu with its models
                provider_submenu = rumps.MenuItem(f"{provider_prefix}{tp['name']} {status}")

                # Add models as submenu items
                provider_models = tp.get("models", [])
                if provider_models:
                    for model_info in provider_models:
                        is_model_selected = is_provider_selected and current_trans_model == model_info["id"]
                        model_prefix = "● " if is_model_selected else "   "
                        suffix = " ★" if model_info.get("recommended") else ""
                        provider_submenu.add(rumps.MenuItem(
                            f"{model_prefix}{model_info['name']}{suffix}",
                            callback=lambda sender, pid=tp["id"], mid=model_info["id"]: self._set_translation_provider_and_model(pid, mid)
                        ))
                else:
                    # Provider with no model selection (e.g., Apple)
                    provider_submenu.add(rumps.MenuItem(
                        "● Use this provider" if is_provider_selected else "   Use this provider",
                        callback=lambda sender, pid=tp["id"]: self._set_translation_provider(pid)
                    ))

                trans_provider_menu.add(provider_submenu)

            trans_provider_menu.add(rumps.separator)

            # Cloud translation providers with model submenus
            trans_provider_menu.add(rumps.MenuItem("── Cloud ──", callback=None))
            for tp in trans_providers:
                if tp["category"] != "cloud":
                    continue
                is_provider_selected = current_trans_provider == tp["id"]
                is_available = tp["available"]
                provider_prefix = "● " if is_provider_selected else "   "
                if is_available is None:
                    status = "…"
                else:
                    status = "✓" if is_available else "○"

                # Create provider submenu with its models
                provider_submenu = rumps.MenuItem(f"{provider_prefix}{tp['name']} {status}")

                # Add models as submenu items, grouped by category
                provider_models = tp.get("models", [])
                if provider_models:
                    # Group models by category
                    categories = {"speed": [], "balanced": [], "quality": []}
                    for model_info in provider_models:
                        cat = model_info.get("category", "balanced")
                        if cat in categories:
                            categories[cat].append(model_info)
                        else:
                            categories["balanced"].append(model_info)

                    category_labels = {
                        "speed": "── Fast ──",
                        "balanced": "── Balanced ──",
                        "quality": "── Quality ──"
                    }

                    for cat_id in ["speed", "balanced", "quality"]:
                        cat_models = categories[cat_id]
                        if not cat_models:
                            continue

                        provider_submenu.add(rumps.MenuItem(category_labels[cat_id], callback=None))

                        for model_info in cat_models:
                            is_model_selected = is_provider_selected and current_trans_model == model_info["id"]
                            model_prefix = "● " if is_model_selected else "   "
                            suffix = " ★" if model_info.get("recommended") else ""
                            provider_submenu.add(rumps.MenuItem(
                                f"{model_prefix}{model_info['name']}{suffix}",
                                callback=lambda sender, pid=tp["id"], mid=model_info["id"]: self._set_translation_provider_and_model(pid, mid)
                            ))
                else:
                    provider_submenu.add(rumps.MenuItem(
                        "● Use this provider" if is_provider_selected else "   Use this provider",
                        callback=lambda sender, pid=tp["id"]: self._set_translation_provider(pid)
                    ))

                trans_provider_menu.add(provider_submenu)

            translation_menu.add(trans_provider_menu)

            # Target language submenu (grouped by region)
            lang_menu = rumps.MenuItem("Target language")
            languages = self.translator.get_supported_languages()

            # Group languages for easier navigation
            common_langs = ["en", "zh", "zh-TW", "es", "fr", "de", "it", "pt", "ja", "ko", "ar", "ru"]
            other_langs = sorted(
                [k for k in languages.keys() if k not in common_langs],
                key=lambda x: languages[x]
            )

            # Recent languages first (if any)
            recent_targets = [c for c in self.config.recent_target_languages if c in languages]
            if recent_targets:
                lang_menu.add(rumps.MenuItem("── Recent ──", callback=None))
                for code in recent_targets:
                    is_selected = self.config.target_language == code
                    prefix = "● " if is_selected else "   "
                    lang_menu.add(rumps.MenuItem(
                        f"{prefix}{languages[code]} ({code})",
                        callback=lambda sender, c=code: self._set_target_language(c)
                    ))
                lang_menu.add(rumps.separator)

            # Common languages
            lang_menu.add(rumps.MenuItem("── Common ──", callback=None))
            for code in common_langs:
                if code in languages and code not in recent_targets:
                    is_selected = self.config.target_language == code
                    prefix = "● " if is_selected else "   "
                    lang_menu.add(rumps.MenuItem(
                        f"{prefix}{languages[code]} ({code})",
                        callback=lambda sender, c=code: self._set_target_language(c)
                    ))

            lang_menu.add(rumps.separator)
            lang_menu.add(rumps.MenuItem("── All Languages ──", callback=None))
            for code in other_langs:
                if code not in recent_targets:  # Skip if already in recent
                    is_selected = self.config.target_language == code
                    prefix = "● " if is_selected else "   "
                    lang_menu.add(rumps.MenuItem(
                        f"{prefix}{languages[code]} ({code})",
                        callback=lambda sender, c=code: self._set_target_language(c)
                    ))

            translation_menu.add(lang_menu)

            # Source language submenu (includes auto-detect)
            source_menu = rumps.MenuItem("Source language")
            source_common = ["en", "zh", "zh-TW", "es", "fr", "de", "it", "pt", "ja", "ko", "ar", "ru"]

            # Auto-detect option always at top
            src_prefix = "● " if self.config.source_language == "auto" else "   "
            source_menu.add(rumps.MenuItem(
                f"{src_prefix}Auto (detect)",
                callback=lambda sender: self._set_source_language("auto")
            ))
            source_menu.add(rumps.separator)

            # Recent languages (if any)
            recent_sources = [c for c in self.config.recent_source_languages if c in languages]
            if recent_sources:
                source_menu.add(rumps.MenuItem("── Recent ──", callback=None))
                for code in recent_sources:
                    is_selected = self.config.source_language == code
                    prefix = "● " if is_selected else "   "
                    source_menu.add(rumps.MenuItem(
                        f"{prefix}{languages[code]} ({code})",
                        callback=lambda sender, c=code: self._set_source_language(c)
                    ))
                source_menu.add(rumps.separator)

            # Common languages
            source_menu.add(rumps.MenuItem("── Common ──", callback=None))
            for code in source_common:
                if code in languages and code not in recent_sources:
                    is_selected = self.config.source_language == code
                    prefix = "● " if is_selected else "   "
                    source_menu.add(rumps.MenuItem(
                        f"{prefix}{languages[code]} ({code})",
                        callback=lambda sender, c=code: self._set_source_language(c)
                    ))

            source_menu.add(rumps.separator)
            source_menu.add(rumps.MenuItem("── All Languages ──", callback=None))
            source_other_langs = sorted(
                [k for k in languages.keys() if k not in source_common],
                key=lambda x: languages[x]
            )
            for code in source_other_langs:
                if code not in recent_sources:  # Skip if already in recent
                    is_selected = self.config.source_language == code
                    prefix = "● " if is_selected else "   "
                    source_menu.add(rumps.MenuItem(
                        f"{prefix}{languages[code]} ({code})",
                        callback=lambda sender, c=code: self._set_source_language(c)
                    ))

            translation_menu.add(source_menu)

            # Quick swap for English/Chinese
            translation_menu.add(rumps.MenuItem(
                "Swap EN ↔ ZH",
                callback=self._swap_translation_languages
            ))

            translation_menu.add(rumps.separator)

            # Ollama-specific options (only show if Ollama is selected)
            # Note: We avoid calling get_status() here as it makes blocking network calls
            if self.translator.get_current_provider() == "ollama":
                # Show generic setup option - detailed status checked when clicked
                translation_menu.add(rumps.MenuItem(
                    "Ollama Setup...",
                    callback=self._show_ollama_setup
                ))

                translation_menu.add(rumps.separator)

                # Auto-start Ollama toggle (doesn't need network call)
                translation_menu.add(rumps.MenuItem(
                    f"{'✓ ' if self.config.ollama_auto_start else '   '}Auto-start Ollama",
                    callback=self._toggle_ollama_auto_start
                ))

        self.menu.add(translation_menu)

        self.menu.add(rumps.separator)

        # === Stats ===
        stats = self.transcriber.get_stats()
        stats_text = f"Transcriptions: {stats['total_transcriptions']} • ${stats['total_cost']:.4f}"
        self.menu.add(rumps.MenuItem(stats_text, callback=None))

        self.menu.add(rumps.separator)

        # === History ===
        history_items = self.config.get_history(limit=10) if self.config.history_enabled else []
        if self.config.private_mode:
            self.menu.add(rumps.MenuItem("History 🔒 Private Mode", callback=None))
        elif not self.config.history_enabled:
            self.menu.add(rumps.MenuItem("History (saving disabled)", callback=None))
        elif history_items:
            history_menu = rumps.MenuItem(f"History ({len(history_items)})")

            for i, item in enumerate(history_items[:10]):
                # Format: truncated text + timestamp
                text = item.get("text", "")
                truncated = text[:40] + "..." if len(text) > 43 else text
                # Replace newlines with spaces for menu display
                truncated = truncated.replace("\n", " ")

                # Format timestamp
                import datetime
                ts = item.get("timestamp", 0)
                dt = datetime.datetime.fromtimestamp(ts)
                time_str = dt.strftime("%H:%M")

                # Show translation indicator if translated
                translated = "→" if item.get("translated") else ""

                history_menu.add(rumps.MenuItem(
                    f"{time_str} {translated} {truncated}",
                    callback=lambda s, idx=i: self._copy_from_history(idx)
                ))

            history_menu.add(rumps.separator)
            history_menu.add(rumps.MenuItem(
                "Clear History",
                callback=self._clear_history
            ))

            self.menu.add(history_menu)
        else:
            self.menu.add(rumps.MenuItem("History (empty)", callback=None))

        self.menu.add(rumps.separator)

        # === Hotkey Settings ===
        hotkey_menu = rumps.MenuItem("Hotkey")

        # Current hotkey display
        hotkey_display = format_hotkey_display(self.config.hotkey)
        mode_text = "hold" if self.config.hotkey_mode == "push_to_talk" else "press"
        hotkey_menu.add(rumps.MenuItem(
            f"Current: {hotkey_display} ({mode_text})",
            callback=None
        ))

        hotkey_menu.add(rumps.separator)

        # Change hotkey
        hotkey_menu.add(rumps.MenuItem(
            "Change Hotkey...",
            callback=self._change_hotkey
        ))

        # Reset to default
        hotkey_menu.add(rumps.MenuItem(
            "Reset to Default (⌘⇧Space)",
            callback=self._reset_hotkey
        ))

        hotkey_menu.add(rumps.separator)

        # Mode selection
        is_push_to_talk = self.config.hotkey_mode == "push_to_talk"
        hotkey_menu.add(rumps.MenuItem(
            f"{'● ' if is_push_to_talk else '   '}Hold to record (push-to-talk)",
            callback=lambda _: self._set_hotkey_mode("push_to_talk")
        ))
        hotkey_menu.add(rumps.MenuItem(
            f"{'● ' if not is_push_to_talk else '   '}Press to toggle recording",
            callback=lambda _: self._set_hotkey_mode("toggle")
        ))

        self.menu.add(hotkey_menu)

        self.menu.add(rumps.separator)

        # === Hotkey hint ===
        hotkey_hint = format_hotkey_display(self.config.hotkey)
        hint_action = "Hold" if self.config.hotkey_mode == "push_to_talk" else "Press"
        self.menu.add(rumps.MenuItem(
            f"{hint_action} {hotkey_hint} to record",
            callback=None
        ))

        self.menu.add(rumps.separator)

        # === Data & Privacy ===
        data_menu = rumps.MenuItem("Data & Privacy")

        # Clear history - show appropriate state
        if self.config.private_mode:
            data_menu.add(rumps.MenuItem(
                "Clear History (Private Mode—nothing saved)",
                callback=None
            ))
        else:
            history_count = len(self.config.history) if self.config.history_enabled else 0
            if history_count > 0:
                encryption_note = " 🔐" if self.config.history_encrypted else ""
                data_menu.add(rumps.MenuItem(
                    f"Clear History ({history_count} items{encryption_note})",
                    callback=self._clear_history
                ))
            else:
                data_menu.add(rumps.MenuItem(
                    "Clear History (empty)",
                    callback=None
                ))

        # Reset statistics
        stats = self.transcriber.get_stats()
        data_menu.add(rumps.MenuItem(
            f"Reset Statistics ({stats['total_transcriptions']} transcriptions)",
            callback=self._reset_statistics
        ))

        # Clear image cache
        data_menu.add(rumps.MenuItem(
            "Clear Image Cache",
            callback=self._clear_image_cache
        ))

        data_menu.add(rumps.separator)

        # Delete API keys submenu
        api_keys_menu = rumps.MenuItem("Delete API Keys")
        configured_providers = configured
        if configured_providers:
            for provider in configured_providers:
                provider_name = self._get_provider_display_name(provider)
                api_keys_menu.add(rumps.MenuItem(
                    f"Delete {provider_name} Key",
                    callback=lambda s, p=provider: self._delete_api_key(p)
                ))
            api_keys_menu.add(rumps.separator)
            api_keys_menu.add(rumps.MenuItem(
                "Delete All API Keys",
                callback=self._delete_all_api_keys
            ))
        else:
            for provider in ["openai", "gemini", "anthropic"]:
                provider_name = self._get_provider_display_name(provider)
                api_keys_menu.add(rumps.MenuItem(
                    f"Delete {provider_name} Key",
                    callback=lambda s, p=provider: self._delete_api_key(p)
                ))
            api_keys_menu.add(rumps.separator)
            api_keys_menu.add(rumps.MenuItem(
                "Delete All API Keys",
                callback=self._delete_all_api_keys
            ))
        data_menu.add(api_keys_menu)

        data_menu.add(rumps.separator)

        # Export/Import settings
        data_menu.add(rumps.MenuItem(
            "Export Settings...",
            callback=self._export_settings
        ))
        data_menu.add(rumps.MenuItem(
            "Import Settings...",
            callback=self._import_settings
        ))

        data_menu.add(rumps.separator)

        # Reset all settings
        data_menu.add(rumps.MenuItem(
            "Reset All Settings...",
            callback=self._reset_all_settings
        ))

        self.menu.add(data_menu)

        self.menu.add(rumps.separator)

        # === Setup Wizard ===
        self.menu.add(rumps.MenuItem("Run Setup Wizard...", callback=self._run_setup_wizard))

        self.menu.add(rumps.separator)

        # === About ===
        from . import __version__
        about_menu = rumps.MenuItem(f"WhisperHUD v{__version__}")

        about_menu.add(rumps.MenuItem("About WhisperHUD", callback=self._show_about))
        about_menu.add(rumps.MenuItem("Check for Updates...", callback=self._check_for_updates))
        about_menu.add(rumps.separator)
        about_menu.add(rumps.MenuItem("View on GitHub", callback=self._open_github))
        about_menu.add(rumps.MenuItem("System Info", callback=self._show_system_info))

        self.menu.add(about_menu)

        self.menu.add(rumps.separator)

        # === Quit ===
        self.menu.add(rumps.MenuItem("Quit WhisperHUD", callback=self._quit))

        # Wrap callbacks so actions run after menu tracking ends
        self._wrap_menu_callbacks(self.menu)

        # Update menu bar icon to reflect target lock status
        if not self._is_recording and not self._is_downloading:
            self._set_title(self._get_idle_icon())

    def _schedule_menu_rebuild(self, delay: float = 0.5) -> None:
        """Rebuild menu after a short delay to avoid blocking menu callbacks."""
        if self._menu_is_open:
            with self._menu_action_lock:
                self._pending_menu_rebuild = True
            self._log_menu_trace("Menu rebuild deferred (menu open)")
            logger.debug("Menu rebuild scheduled after close (menu open)")
            return

        if self._menu_rebuild_scheduled:
            logger.debug("Menu rebuild already scheduled, skipping")
            return

        self._menu_rebuild_scheduled = True
        logger.debug(f"Scheduling menu rebuild in {delay}s")

        def _trigger():
            self._menu_rebuild_scheduled = False
            # Check if menu was reopened during delay - if so, defer to pending
            if self._menu_is_open:
                with self._menu_action_lock:
                    self._pending_menu_rebuild = True
                logger.debug("Menu rebuild deferred (menu reopened during delay)")
                return
            logger.debug("Executing scheduled menu rebuild")
            # Use AppHelper to run on main thread - UI operations need main thread
            try:
                from PyObjCTools import AppHelper
                AppHelper.callAfter(self._build_menu)
            except Exception:
                self._build_menu()

        threading.Timer(delay, _trigger).start()

    def _defer_menu_action(self, action, delay: float = 0.05) -> None:
        """Run a menu action after the menu closes to prevent greying."""
        # Also defer if menu JUST closed (within 0.3s) to handle race condition
        # where callback fires after menuDidEndTracking but before UI is ready.
        recently_closed = (time.time() - self._last_menu_close_time) < 0.3

        if self._menu_is_open or recently_closed:
            with self._menu_action_lock:
                self._pending_menu_actions.append(action)
            logger.debug(f"Menu action deferred (open={self._menu_is_open}, recent={recently_closed})")
            # Ensure post-close tasks are scheduled to pick this up
            self._schedule_post_close_tasks()
            return

        action()

    def _wrap_menu_callbacks(self, menu_obj) -> None:
        """Wrap menu callbacks so they run after menu tracking ends."""
        try:
            items = list(menu_obj.values())
        except Exception:
            return

        for item in items:
            try:
                cb = item.callback
            except Exception:
                cb = None

            if cb and not getattr(cb, "_whisperhud_wrapped", False):
                def _make_wrapper(callback_func):
                    def _wrapped(sender):
                        self._defer_menu_action(lambda: callback_func(sender))
                    _wrapped._whisperhud_wrapped = True  # type: ignore[attr-defined]
                    return _wrapped

                item.set_callback(_make_wrapper(cb))

            # Recurse into submenus
            try:
                if len(item) > 0:
                    self._wrap_menu_callbacks(item)
            except Exception:
                pass

    def _clear_menu_callback_registry(self, menu_obj) -> None:
        """Remove menu items from rumps callback registry to avoid leaks."""
        try:
            from rumps import rumps as rumps_mod
            registry = rumps_mod.NSApp._ns_to_py_and_callback
        except Exception:
            return

        for ns_item in self._collect_menu_nsitems(menu_obj):
            registry.pop(ns_item, None)

    def _collect_menu_nsitems(self, menu_obj):
        items = []
        try:
            values = list(menu_obj.values())
        except Exception:
            return items

        for item in values:
            try:
                if hasattr(item, "_menuitem"):
                    items.append(item._menuitem)
            except Exception:
                pass
            try:
                if len(item) > 0:
                    items.extend(self._collect_menu_nsitems(item))
            except Exception:
                pass
        return items

    def _run_pending_menu_actions(self) -> None:
        """Run any deferred menu actions on the main thread."""
        with self._menu_action_lock:
            if not self._pending_menu_actions:
                return
            actions = self._pending_menu_actions[:]
            self._pending_menu_actions.clear()

        def _apply():
            for action in actions:
                try:
                    action()
                except Exception as e:
                    logger.debug(f"Deferred menu action failed: {e}")

        try:
            from PyObjCTools import AppHelper
            AppHelper.callAfter(_apply)
        except Exception:
            _apply()

    def _schedule_post_close_tasks(self, delay: float = 0.15) -> None:
        """Schedule pending rebuilds and actions after menu fully closes.

        Adds a delay to ensure the menu is visually dismissed before any
        modifications, preventing the "greyed out" menu issue.
        """
        with self._menu_action_lock:
            if not self._pending_menu_rebuild and not self._pending_menu_actions:
                return

        def _do_tasks():
            # Don't run if menu was reopened during delay - pending state is preserved
            # and will be picked up when menu closes again
            if self._menu_is_open:
                logger.debug("Post-close tasks deferred (menu reopened)")
                # Keep pending state so it runs when menu closes again
                return

            try:
                from PyObjCTools import AppHelper

                def _apply():
                    with self._menu_action_lock:
                        rebuild = self._pending_menu_rebuild
                        self._pending_menu_rebuild = False
                        actions = self._pending_menu_actions[:]
                        self._pending_menu_actions.clear()

                    if rebuild:
                        logger.debug("Applying deferred menu rebuild")
                        self._build_menu()

                    for action in actions:
                        try:
                            action()
                        except Exception as e:
                            logger.debug(f"Deferred action failed: {e}")

                AppHelper.callAfter(_apply)
            except Exception:
                with self._menu_action_lock:
                    rebuild = self._pending_menu_rebuild
                    self._pending_menu_rebuild = False
                if rebuild:
                    self._build_menu()
                self._run_pending_menu_actions()

        threading.Timer(delay, _do_tasks).start()
        logger.debug(f"Post-close tasks scheduled in {delay}s")

    def _patch_rumps_alert(self) -> None:
        """Wrap rumps.alert to activate the app so alerts are visible."""
        if getattr(rumps.alert, "_whisperhud_wrapped", False):
            return

        original_alert = rumps.alert

        def _alert_with_activate(*args, **kwargs):
            try:
                from AppKit import NSApplication
                NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            except Exception:
                pass
            return original_alert(*args, **kwargs)

        _alert_with_activate._whisperhud_wrapped = True  # type: ignore[attr-defined]
        rumps.alert = _alert_with_activate

    def _log_menu_trace(self, label: str) -> None:
        """Optionally log a short stack trace for menu rebuild debugging."""
        if not os.environ.get("WHISPER_HUD_MENU_TRACE"):
            return
        import traceback
        stack = "".join(traceback.format_stack(limit=8))
        logger.debug(f"{label}\n{stack}")

    def _attach_menu_delegate(self) -> None:
        """Attach an NSMenu delegate to track open/close state."""
        try:
            import objc
            from AppKit import NSObject
            from AppKit import NSMenuDidBeginTrackingNotification, NSMenuDidEndTrackingNotification
            from Foundation import NSNotificationCenter

            app_ref = weakref.ref(self)

            class _MenuDelegate(NSObject):
                def init(self):  # type: ignore[override]
                    self = objc.super(_MenuDelegate, self).init()
                    return self

                def menuWillOpen_(self, _menu):  # noqa: N802
                    app = app_ref()
                    if app:
                        app._menu_is_open = True
                        logger.debug("Menu opened")

                def menuDidClose_(self, _menu):  # noqa: N802
                    app = app_ref()
                    if not app:
                        return
                    app._menu_is_open = False
                    app._last_menu_close_time = time.time()
                    logger.debug("Menu closed")
                    # Delay rebuild/actions to ensure menu is fully dismissed visually
                    app._schedule_post_close_tasks()

            self._menu_delegate = _MenuDelegate.alloc().init()
            self._menu_observer = None
            if hasattr(self.menu, "_menu"):
                self.menu._menu.setDelegate_(self._menu_delegate)

                class _MenuObserver(NSObject):
                    def menuDidBeginTracking_(self, _notif):  # noqa: N802
                        app = app_ref()
                        if app:
                            app._menu_is_open = True
                            logger.debug("Menu tracking began (notification)")

                    def menuDidEndTracking_(self, _notif):  # noqa: N802
                        app = app_ref()
                        if not app:
                            return
                        app._menu_is_open = False
                        app._last_menu_close_time = time.time()
                        logger.debug("Menu tracking ended (notification)")
                        # Delay rebuild/actions to ensure menu is fully dismissed visually
                        app._schedule_post_close_tasks()

                self._menu_observer = _MenuObserver.alloc().init()
                center = NSNotificationCenter.defaultCenter()
                self._menu_notification_center = center
                center.addObserver_selector_name_object_(
                    self._menu_observer,
                    "menuDidBeginTracking:",
                    NSMenuDidBeginTrackingNotification,
                    self.menu._menu,
                )
                center.addObserver_selector_name_object_(
                    self._menu_observer,
                    "menuDidEndTracking:",
                    NSMenuDidEndTrackingNotification,
                    self.menu._menu,
                )
                logger.debug("Menu delegate and notifications attached")
        except Exception as e:
            logger.debug(f"Menu delegate not attached: {e}")

    def _detach_menu_observers(self) -> None:
        """Remove NSMenu observers/delegates to avoid leaks on shutdown."""
        try:
            center = self._menu_notification_center
            if center and self._menu_observer:
                center.removeObserver_(self._menu_observer)
        except Exception:
            pass

        try:
            if hasattr(self.menu, "_menu"):
                self.menu._menu.setDelegate_(None)
        except Exception:
            pass

        self._menu_notification_center = None
        self._menu_observer = None
        self._menu_delegate = None

    def _get_provider_display_name(self, provider_id: str) -> str:
        """Get display name for a provider."""
        names = {
            "openai": "OpenAI",
            "openai_realtime": "OpenAI Realtime",
            "gemini": "Gemini",
            "anthropic": "Anthropic",
            "apple": "Apple",
            "whisper_local": "Whisper",
            "parakeet": "Parakeet",
        }
        return names.get(provider_id, provider_id.title())

    def _select_or_download_provider(self, provider_id: str, provider_info: dict):
        """Select a provider, or prompt for download if needed."""
        # If provider isn't available due to missing deps or OS constraints, show guidance
        if not provider_info.get("configured", False):
            # Special handling for Apple - show detailed setup help
            if provider_id == "apple":
                self._show_apple_setup_help()
                return

            availability_message = provider_info.get("availability_message")
            is_installed = provider_info.get("is_installed")

            if is_installed is False and availability_message:
                rumps.alert(
                    title="Provider Not Available",
                    message=availability_message
                )
                return

            if availability_message and not provider_info.get("requires_download", False):
                rumps.alert(
                    title="Provider Not Available",
                    message=availability_message
                )
                return

        # Check if provider needs download
        if provider_info.get("requires_download", False):
            provider = self.transcriber.get_provider(provider_id)
            if provider and not provider.is_configured():
                # Needs download
                self._prompt_model_download(provider_id)
                return

        self._select_provider(provider_id)

    def _prompt_model_download(self, provider_id: str):
        """Show download prompt for a local provider."""
        download_info = self.transcriber.get_download_info(provider_id)

        if download_info.get("downloaded", False):
            # Already downloaded
            self._select_provider(provider_id)
            return

        size_mb = download_info.get("size_mb", 0)
        has_space = download_info.get("has_disk_space", True)

        if not has_space:
            available_mb = download_info.get("available_mb", 0)
            rumps.alert(
                title="Insufficient Disk Space",
                message=(
                    f"Model requires {size_mb}MB but only "
                    f"{available_mb:.0f}MB available.\n\n"
                    f"Free up some disk space and try again."
                )
            )
            return

        # Show download confirmation
        provider_name = self._get_provider_display_name(provider_id)
        response = rumps.alert(
            title=f"Download {provider_name} Model",
            message=(
                f"Download {provider_name} model?\n\n"
                f"Size: ~{size_mb}MB\n"
                f"Location: ~/.cache/whisper-hud/\n\n"
                f"This may take a few minutes."
            ),
            ok="Download",
            cancel="Cancel"
        )

        if response != 1:
            return

        self._start_model_download(provider_id)

    def _start_model_download(self, provider_id: str):
        """Start downloading a model in the background."""
        self._is_downloading = True
        self._set_title(self.ICON_DOWNLOADING)
        self._schedule_menu_rebuild()

        self._notify(
            "WhisperHUD",
            "Downloading Model",
            "This will run in the background. You'll be notified when complete."
        )

        def do_download():
            def progress_callback(msg, pct):
                logger.debug(f"Download: {msg} ({pct:.0f}%)")

            success = self.transcriber.download_model(provider_id, progress_callback)

            self._is_downloading = False
            self._set_title(self._get_idle_icon())

            if success:
                self._notify(
                    "WhisperHUD",
                    "Download Complete",
                    f"Model is ready! Switching to {self._get_provider_display_name(provider_id)}."
                )
                self._select_provider(provider_id)
            else:
                self._notify(
                    "WhisperHUD",
                    "Download Failed",
                    "Check console for details."
                )
                self._schedule_menu_rebuild()

        threading.Thread(target=do_download, daemon=True).start()

    def _select_model_or_download(self, model_id: str, downloaded: bool):
        """Select a model, or download it first if needed."""
        if not downloaded:
            # Need to download
            provider_id = self.config.default_provider
            provider = self.transcriber.get_provider(provider_id)

            if provider and hasattr(provider, 'set_model'):
                provider.set_model(model_id)
                self.config.set_provider_model(provider_id, model_id)

            self._prompt_model_download(provider_id)
        else:
            self._select_model(model_id)

    def _get_active_turn(self, turn_id: int) -> Optional[ActiveTranscriptionTurn]:
        """Return the active turn when the callback still belongs to it."""
        turn = self._active_turn
        if turn and turn.turn_id == turn_id:
            return turn
        return None

    def _cancel_turn_timers(self, turn: ActiveTranscriptionTurn) -> None:
        """Cancel any outstanding timers for a turn."""
        for attr in ("connect_timer", "finalize_timer"):
            timer = getattr(turn, attr)
            if timer:
                timer.cancel()
                setattr(turn, attr, None)

    def _close_live_session(self, turn: ActiveTranscriptionTurn) -> None:
        """Close an active live session without raising into the app thread."""
        live_session = turn.live_session
        turn.live_session = None
        if live_session:
            try:
                live_session.close()
            except Exception:
                logger.debug("Failed to close live transcription session", exc_info=True)

    def _selected_live_language(self) -> Optional[str]:
        """Use explicit source language only; let Realtime detect when set to auto."""
        return None if self.config.source_language == "auto" else self.config.source_language

    def _get_batch_provider_id(self, provider_id: str) -> str:
        """Map live providers to their synchronous fallback provider."""
        if provider_id == "openai_realtime":
            return "openai"
        return provider_id

    def _start_live_connect_timer(self, turn_id: int) -> threading.Timer:
        """Downgrade to batch if the live provider never becomes ready."""
        def on_timeout():
            turn = self._get_active_turn(turn_id)
            if not turn or turn.phase != RecordingTurnPhase.STARTING:
                return
            logger.warning("OpenAI Realtime connect timeout for turn %s", turn_id)
            self._degrade_turn_to_batch(turn_id, "OpenAI Realtime connect timeout")

        timer = threading.Timer(1.5, on_timeout)
        timer.daemon = True
        timer.start()
        return timer

    def _start_live_finalize_timer(self, turn_id: int) -> threading.Timer:
        """Downgrade to batch if the final transcript never arrives after commit."""
        def on_timeout():
            turn = self._get_active_turn(turn_id)
            if not turn or turn.result_processing_started:
                return
            logger.warning("OpenAI Realtime finalization timeout for turn %s", turn_id)
            self._degrade_turn_to_batch(turn_id, "OpenAI Realtime finalization timeout")

        timer = threading.Timer(8.0, on_timeout)
        timer.daemon = True
        timer.start()
        return timer

    def _on_live_audio_chunk(self, turn_id: int, audio_chunk, sample_rate: int) -> None:
        """Forward recorder chunks to the active live session when available."""
        turn = self._get_active_turn(turn_id)
        if not turn or turn.phase in {RecordingTurnPhase.DEGRADED_BATCH, RecordingTurnPhase.FINALIZING}:
            return
        if turn.live_session:
            turn.live_session.push_audio(audio_chunk, sample_rate)

    def _on_live_session_ready(self, turn_id: int) -> None:
        """Mark the live session ready for this turn if it is still current."""
        turn = self._get_active_turn(turn_id)
        if not turn:
            return
        self._cancel_turn_timers(turn)
        if turn.phase != RecordingTurnPhase.STARTING:
            self._close_live_session(turn)
            return
        turn.phase = RecordingTurnPhase.STREAMING

    def _on_live_session_partial(self, turn_id: int, text: str) -> None:
        """Update the streaming panel with live partial transcript text."""
        turn = self._get_active_turn(turn_id)
        if not turn or turn.phase == RecordingTurnPhase.DEGRADED_BATCH:
            return
        if self.config.streaming_enabled and text:
            self.streaming_panel.update_transcription(text)

    def _on_live_session_final(self, turn_id: int, result: TranscriptionResult) -> None:
        """Complete the turn from the final live transcript."""
        turn = self._get_active_turn(turn_id)
        if not turn:
            return
        self._cancel_turn_timers(turn)
        self._process_turn_result(
            turn_id,
            result,
            use_streaming=self.config.streaming_enabled,
            stats_already_recorded=False,
        )

    def _on_live_session_error(self, turn_id: int, error: Exception) -> None:
        """Downgrade to batch when a live session fails."""
        logger.warning("Live transcription error on turn %s: %s", turn_id, error)
        self._degrade_turn_to_batch(turn_id, str(error))

    def _degrade_turn_to_batch(self, turn_id: int, reason: str) -> None:
        """Stop using live transcription and fall back to batch for this turn."""
        turn = self._get_active_turn(turn_id)
        if not turn:
            return

        self._cancel_turn_timers(turn)
        self._close_live_session(turn)

        if turn.result_processing_started:
            return

        turn.phase = RecordingTurnPhase.DEGRADED_BATCH
        if self._is_recording and self.config.streaming_enabled:
            self.streaming_panel.hide()

        if turn.audio_bytes and not turn.batch_fallback_started:
            turn.batch_fallback_started = True
            self._start_batch_transcription(turn_id)

        if reason:
            logger.info("Turn %s falling back to batch transcription: %s", turn_id, reason)

    def _start_batch_transcription(self, turn_id: int) -> None:
        """Run synchronous transcription for the active turn in a background thread."""
        turn = self._get_active_turn(turn_id)
        if not turn or not turn.audio_bytes:
            return

        audio_bytes = turn.audio_bytes
        provider_id = self._get_batch_provider_id(turn.provider_id)
        use_streaming = self.config.streaming_enabled

        def do_transcribe():
            try:
                if use_streaming:
                    self.streaming_panel.show_transcribing(
                        show_translation=self.config.translation_enabled
                    )
                    result = self.transcriber.transcribe_streaming(
                        audio_bytes,
                        on_chunk=self.streaming_panel.update_transcription,
                        provider_id=provider_id,
                    )
                else:
                    result = self.transcriber.transcribe(audio_bytes, provider_id=provider_id)

                self._process_turn_result(
                    turn_id,
                    result,
                    use_streaming=use_streaming,
                    stats_already_recorded=True,
                )
            except Exception as e:
                self._handle_transcription_error(turn_id, e, use_streaming)

        threading.Thread(target=do_transcribe, daemon=True).start()

    def _process_turn_result(
        self,
        turn_id: int,
        result: TranscriptionResult,
        *,
        use_streaming: bool,
        stats_already_recorded: bool,
    ) -> None:
        """Process the final transcript once, even if multiple callbacks race."""
        turn = self._get_active_turn(turn_id)
        if not turn or turn.result_processing_started:
            return

        turn.result_processing_started = True
        turn.phase = RecordingTurnPhase.FINALIZING
        self._cancel_turn_timers(turn)
        self._close_live_session(turn)

        def finalize_result():
            try:
                if not stats_already_recorded:
                    self.config.add_transcription_stats(result.cost_estimate)

                if use_streaming and result.text:
                    self.streaming_panel.update_transcription(result.text)

                has_transcription = bool(result.text and result.text.strip())

                if has_transcription:
                    final_text = result.text
                    did_translate = False

                    if self.config.translation_enabled:
                        try:
                            if self.config.show_hud:
                                self.hud.show_processing("Translating...")

                            if use_streaming:
                                self.streaming_panel.show_translating()

                            use_translation_streaming = (
                                use_streaming
                                and self.translator.supports_streaming()
                            )

                            source_lang = self.config.source_language
                            if source_lang == "auto" and result.language:
                                source_lang = result.language

                            if use_translation_streaming:
                                translation = self.translator.translate_streaming(
                                    text=result.text,
                                    on_chunk=self.streaming_panel.update_translation,
                                    source_lang=source_lang,
                                    target_lang=self.config.target_language
                                )
                            else:
                                translation = self.translator.translate(
                                    text=result.text,
                                    source_lang=source_lang,
                                    target_lang=self.config.target_language
                                )
                                if use_streaming:
                                    self.streaming_panel.update_translation(translation.text)

                            final_text = translation.text
                            did_translate = True

                            lang_name = self.translator.get_supported_languages().get(
                                self.config.target_language,
                                self.config.target_language
                            )
                            word_count = len(final_text.split())
                            self._set_title(self.ICON_SUCCESS)
                            if self.config.show_hud:
                                self.hud.show_success(f"✓ {word_count} words → {lang_name}")

                        except Exception as e:
                            logger.warning(f"Translation failed: {e}")
                            final_text = result.text
                            word_count = len(final_text.split())
                            self._set_title(self.ICON_SUCCESS)
                            if self.config.show_hud:
                                self.hud.show_success(f"✓ {word_count} words (translation failed)")
                    else:
                        word_count = len(final_text.split())
                        self._set_title(self.ICON_SUCCESS)
                        if self.config.show_hud:
                            self.hud.show_success(f"✓ {word_count} words")

                    self._play_completion_sound()

                    if use_streaming:
                        self.streaming_panel.show_complete()

                    self.config.add_to_history(
                        text=final_text,
                        provider=result.provider,
                        translated=did_translate,
                        original_text=result.text if did_translate else ""
                    )

                    if self.config.auto_paste:
                        time.sleep(0.1)
                        self._paste_to_target(final_text)
                else:
                    self._set_title(self.ICON_ERROR)
                    if self.config.show_hud:
                        self.hud.show_error("No speech detected")
                    if use_streaming:
                        self.streaming_panel.hide()
            except Exception as e:
                self._handle_transcription_error(turn_id, e, use_streaming, already_finalizing=True)
                return

            self._finish_turn_cleanup(turn_id)

        threading.Thread(target=finalize_result, daemon=True).start()

    def _handle_transcription_error(
        self,
        turn_id: int,
        error: Exception,
        use_streaming: bool,
        *,
        already_finalizing: bool = False,
    ) -> None:
        """Show a terminal transcription error and clean up if the turn is still current."""
        turn = self._get_active_turn(turn_id)
        if not turn:
            return

        if not already_finalizing:
            if turn.result_processing_started:
                return
            turn.result_processing_started = True
            turn.phase = RecordingTurnPhase.FINALIZING

        self._cancel_turn_timers(turn)
        self._close_live_session(turn)

        error_str = str(error).lower()
        logger.error(f"Transcription error: {error}")
        self._set_title(self.ICON_ERROR)

        if "timeout" in error_str or "timed out" in error_str:
            display_error = "Connection timeout"
            detail = "Check your internet connection"
        elif "connection" in error_str or "network" in error_str:
            display_error = "Network error"
            detail = "Check your internet connection"
        elif "401" in error_str or "unauthorized" in error_str or "invalid" in error_str:
            display_error = "Invalid API key"
            detail = "Update your API key in settings"
        elif "403" in error_str or "forbidden" in error_str:
            display_error = "Access denied"
            detail = "Check API key permissions"
        elif "429" in error_str or "rate" in error_str:
            display_error = "Rate limited"
            detail = "Too many requests, wait a moment"
        elif "500" in error_str or "502" in error_str or "503" in error_str:
            display_error = "Server error"
            detail = "API service temporarily unavailable"
        elif "microphone" in error_str or "audio" in error_str:
            display_error = "Mic access denied"
            detail = "Check microphone permissions"
        elif isinstance(error, ValueError):
            if "api key" in error_str or "not configured" in error_str:
                display_error = "API keys locked" if self._is_passphrase_store_locked() else "API key required"
                detail = "Unlock API key storage in Privacy & Security." if self._is_passphrase_store_locked() else "Click the menu bar icon to add your API key."
            else:
                display_error = str(error)[:25]
                detail = str(error)[:50]
        else:
            display_error = "Transcription failed"
            detail = str(error)[:50]

        if self.config.show_hud:
            self.hud.show_error(display_error)
        if use_streaming:
            self.streaming_panel.hide()

        if isinstance(error, ValueError) and ("api key" in error_str or "not configured" in error_str):
            if self._is_passphrase_store_locked():
                self._notify(
                    "WhisperHUD",
                    "Unlock Required",
                    "Unlock API key storage in Privacy & Security."
                )
            else:
                self._notify(
                    "WhisperHUD",
                    "Configuration Required",
                    "Click the menu bar icon to add your API key."
                )
        else:
            self._notify(
                "WhisperHUD",
                display_error,
                detail
            )

        self._finish_turn_cleanup(turn_id)

    def _finish_turn_cleanup(self, turn_id: int) -> None:
        """Reset UI for the finished turn without clobbering a newer one."""
        time.sleep(1.5)
        turn = self._get_active_turn(turn_id)
        if not turn:
            return

        self._cancel_turn_timers(turn)
        self._close_live_session(turn)
        self._active_turn = None
        self._set_title(self._get_idle_icon())
        if self.widget:
            self.widget.set_idle()
        self._schedule_menu_rebuild()

    def _start_recording(self):
        """Called when hotkey is pressed."""
        if not self._ensure_cloud_credentials_ready(allow_create=False):
            self._notify(
                "WhisperHUD",
                "Cloud Keys Locked",
                "Unlock passphrase storage to use cloud providers, or switch to Apple local.",
            )
            return

        if self.config.history_encrypted:
            self._ensure_history_encryption_session(create_if_missing=False, prompt_unlock=False)

        with self._recording_lock:
            with self._lock:
                if self._is_recording:
                    return
                self._is_recording = True
                self._turn_counter += 1
                turn = ActiveTranscriptionTurn(
                    turn_id=self._turn_counter,
                    provider_id=self.config.default_provider,
                )
                self._active_turn = turn

            self._set_title(self.ICON_RECORDING)

            if self.config.show_hud:
                self.hud.show_recording()

            if self.widget:
                self.widget.set_recording()

            on_audio_chunk = None
            try:
                if self.transcriber.supports_live_input(turn.provider_id):
                    turn.live_session = self.transcriber.create_live_session(
                        provider_id=turn.provider_id,
                        on_partial=lambda text, tid=turn.turn_id: self._on_live_session_partial(tid, text),
                        on_final=lambda result, tid=turn.turn_id: self._on_live_session_final(tid, result),
                        on_error=lambda error, tid=turn.turn_id: self._on_live_session_error(tid, error),
                        on_ready=lambda tid=turn.turn_id: self._on_live_session_ready(tid),
                        language=self._selected_live_language(),
                    )

                    def live_audio_chunk_handler(chunk, rate, tid=turn.turn_id):
                        self._on_live_audio_chunk(tid, chunk, rate)

                    on_audio_chunk = live_audio_chunk_handler
            except Exception as e:
                logger.error(f"Failed to prepare live transcription session: {e}")
                with self._lock:
                    self._is_recording = False
                    self._active_turn = None
                self._set_title(self._get_idle_icon())
                if self.config.show_hud:
                    self.hud.show_error("Provider setup required")
                if self.widget:
                    self.widget.set_idle()
                self._notify(
                    "WhisperHUD",
                    "Configuration Required",
                    "Add or unlock your OpenAI API key before using OpenAI Realtime."
                )
                return

            try:
                if self.config.auto_stop:
                    self.recorder.set_silence_settings(
                        enabled=True,
                        silence_duration=self.config.silence_duration,
                        silence_threshold=self.config.silence_threshold
                    )
                    self.recorder.start(
                        on_silence=self._on_silence_detected,
                        on_audio_chunk=on_audio_chunk,
                    )
                else:
                    self.recorder.start(on_audio_chunk=on_audio_chunk)
            except Exception as e:
                logger.error(f"Failed to start recording: {e}")
                with self._lock:
                    self._is_recording = False
                    self._active_turn = None
                if turn.live_session:
                    self._close_live_session(turn)
                self._set_title(self._get_idle_icon())
                if self.config.show_hud:
                    self.hud.show_error("Microphone error")
                if self.widget:
                    self.widget.set_idle()
                self._notify(
                    "WhisperHUD",
                    "Recording Failed",
                    "Check microphone permissions and device availability."
                )
                return

            if turn.live_session:
                if self.config.streaming_enabled:
                    self.streaming_panel.show_transcribing(
                        show_translation=self.config.translation_enabled
                    )
                turn.connect_timer = self._start_live_connect_timer(turn.turn_id)
                turn.live_session.start()

            self._start_level_monitor(turn.turn_id)
            self._start_max_duration_timer(turn.turn_id)

    def _start_level_monitor(self, turn_id: int):
        """Start monitoring audio levels for the current turn."""
        def monitor_levels():
            while self._is_recording and self._get_active_turn(turn_id):
                level = self.recorder.get_audio_level()
                if self.config.show_hud:
                    self.hud.update_audio_level(level)
                if self.streaming_panel and hasattr(self.streaming_panel, 'update_audio_level'):
                    self.streaming_panel.update_audio_level(level)
                time.sleep(0.05)

        self._level_monitor_thread = threading.Thread(target=monitor_levels, daemon=True)
        self._level_monitor_thread.start()

    def _start_max_duration_timer(self, turn_id: int):
        """Auto-stop a turn after the configured maximum duration."""
        max_duration = self.config.max_recording_duration

        def check_duration():
            start = time.time()
            while self._is_recording and self._get_active_turn(turn_id):
                if time.time() - start >= max_duration:
                    logger.info("Max recording duration (%ss) reached, auto-stopping", max_duration)
                    self._request_stop("max_duration")
                    break
                time.sleep(1)

        self._max_duration_thread = threading.Thread(target=check_duration, daemon=True)
        self._max_duration_thread.start()

    def _on_silence_detected(self):
        """Called when silence is detected after speech."""
        self._request_stop("silence")

    def _request_stop(self, reason: str) -> None:
        """Stop recording and choose live finalization or batch fallback once."""
        with self._recording_lock:
            with self._lock:
                turn = self._active_turn
                if not self._is_recording or not turn:
                    return
                self._is_recording = False
                if turn.phase in {RecordingTurnPhase.STOP_REQUESTED, RecordingTurnPhase.FINALIZING}:
                    return
                turn.phase = RecordingTurnPhase.STOP_REQUESTED
                turn.stop_reason = reason

            self._set_title(self.ICON_PROCESSING)

            if self.config.show_hud:
                self.hud.show_processing()

            if self.widget:
                self.widget.set_processing()

            turn.audio_bytes = self.recorder.stop()

        if not turn.audio_bytes or len(turn.audio_bytes) < 1000:
            self._cancel_turn_timers(turn)
            self._close_live_session(turn)
            self.hud.hide()
            if self.config.streaming_enabled:
                self.streaming_panel.hide()
            self._active_turn = None
            self._set_title(self._get_idle_icon())
            if self.widget:
                self.widget.set_idle()
            return

        if turn.live_session and turn.live_session.is_ready():
            turn.finalize_timer = self._start_live_finalize_timer(turn.turn_id)
            turn.live_session.request_stop()
            return

        turn.batch_fallback_started = True
        self._degrade_turn_to_batch(turn.turn_id, f"Stop requested before live session ready ({reason})")

    def _stop_recording(self):
        """Called when hotkey is released."""
        self._request_stop("manual_release")

    def _show_apple_setup_help(self):
        """Show setup help for Apple Speech Recognition."""
        from .providers.apple_speech import AppleSpeechProvider

        title, message = AppleSpeechProvider.get_setup_instructions()

        if title == "Ready":
            # It's actually ready now, just select it
            self._select_provider("apple")
            return

        if title == "Permissions Required":
            # Offer to open settings
            response = rumps.alert(
                title=title,
                message=message,
                ok="Open Settings",
                cancel="Cancel"
            )
            if response == 1:
                AppleSpeechProvider.open_speech_settings()
        else:
            # Just show the info
            rumps.alert(title=title, message=message)

    def _select_provider(self, provider_id: str):
        """Change default provider."""
        self.config.default_provider = provider_id
        self.config.save()
        self._schedule_menu_rebuild()

    def _select_provider_and_model(self, provider_id: str, model_id: str):
        """Change both provider and model in one action."""
        self.config.default_provider = provider_id
        self.transcriber.set_provider_model(provider_id, model_id)
        self._schedule_menu_rebuild()

    def _select_provider_model_or_download(self, provider_id: str, model_id: str, downloaded: bool, provider_info: dict):
        """Select provider/model, or prompt for download if needed."""
        if not downloaded:
            # Set provider first so download targets the right one
            self.config.default_provider = provider_id
            self.config.save()
            self._prompt_model_download(provider_id)
        else:
            self._select_provider_and_model(provider_id, model_id)

    def _select_model(self, model_id: str):
        """Change model for current provider."""
        self.transcriber.set_provider_model(
            self.config.default_provider,
            model_id
        )
        self._schedule_menu_rebuild()

    def _set_openai_key(self, _):
        """Prompt for OpenAI API key using AppleScript for proper paste support."""
        if self._is_passphrase_mode() and not self._ensure_passphrase_unlocked():
            return

        message = "Enter your OpenAI API key.\n\nGet your key at: platform.openai.com/api-keys"
        if get_api_key("openai"):
            message += "\n\nA key is already saved. Enter a new key to replace it."
        key = self._applescript_input_dialog(
            "OpenAI API Key",
            message,
        )

        if key:
            if not key.startswith("sk-"):
                rumps.alert(
                    title="Invalid Key Format",
                    message="OpenAI API keys should start with 'sk-'"
                )
                return

            # Validate the key with a quick API call
            self._notify(
                "WhisperHUD",
                "Validating API Key",
                "Checking key with OpenAI..."
            )

            def do_validate():
                is_valid, error = validate_api_key("openai", key)
                if is_valid:
                    if not set_api_key("openai", key):
                        self._notify(
                            "WhisperHUD",
                            "Could Not Save Key",
                            "Unlock API key storage first in Privacy & Security."
                        )
                        return
                    # Reset cached clients so new key is used immediately
                    self.transcriber.reset_provider("openai")
                    self.transcriber.reset_provider("openai_realtime")
                    self.translator.reset_provider("openai")
                    self._schedule_menu_rebuild()
                    self._notify(
                        "WhisperHUD",
                        "API Key Saved",
                        "OpenAI key validated and saved securely."
                    )
                else:
                    self._notify(
                        "WhisperHUD",
                        "Invalid API Key",
                        error or "Key validation failed"
                    )

            threading.Thread(target=do_validate, daemon=True).start()

    def _set_gemini_key(self, _):
        """Prompt for Gemini API key using AppleScript for proper paste support."""
        if self._is_passphrase_mode() and not self._ensure_passphrase_unlocked():
            return

        message = "Enter your Google AI API key.\n\nGet your key at: aistudio.google.com/apikey"
        if get_api_key("gemini"):
            message += "\n\nA key is already saved. Enter a new key to replace it."
        key = self._applescript_input_dialog(
            "Gemini API Key",
            message,
        )

        if key:
            # Validate the key with a quick API call
            self._notify(
                "WhisperHUD",
                "Validating API Key",
                "Checking key with Google AI..."
            )

            def do_validate():
                is_valid, error = validate_api_key("gemini", key)
                if is_valid:
                    if not set_api_key("gemini", key):
                        self._notify(
                            "WhisperHUD",
                            "Could Not Save Key",
                            "Unlock API key storage first in Privacy & Security."
                        )
                        return
                    # Reset cached clients so new key is used immediately
                    self.transcriber.reset_provider("gemini")
                    self.translator.reset_provider("gemini")
                    self._schedule_menu_rebuild()
                    self._notify(
                        "WhisperHUD",
                        "API Key Saved",
                        "Gemini key validated and saved securely."
                    )
                else:
                    self._notify(
                        "WhisperHUD",
                        "Invalid API Key",
                        error or "Key validation failed"
                    )

            threading.Thread(target=do_validate, daemon=True).start()

    def _set_anthropic_key(self, _):
        """Prompt for Anthropic API key using AppleScript for proper paste support."""
        if self._is_passphrase_mode() and not self._ensure_passphrase_unlocked():
            return

        message = (
            "Enter your Anthropic API key.\n\n"
            "Get your key at: console.anthropic.com/settings/keys"
        )
        if get_api_key("anthropic"):
            message += "\n\nA key is already saved. Enter a new key to replace it."
        key = self._applescript_input_dialog(
            "Anthropic API Key",
            message,
        )

        if key:
            if not key.startswith("sk-ant-"):
                rumps.alert(
                    title="Invalid Key Format",
                    message="Anthropic API keys should start with 'sk-ant-'"
                )
                return

            # Validate the key with a quick API call
            self._notify(
                "WhisperHUD",
                "Validating API Key",
                "Checking key with Anthropic..."
            )

            def do_validate():
                is_valid, error = validate_api_key("anthropic", key)
                if is_valid:
                    if not set_api_key("anthropic", key):
                        self._notify(
                            "WhisperHUD",
                            "Could Not Save Key",
                            "Unlock API key storage first in Privacy & Security."
                        )
                        return
                    # Reset cached client so new key is used immediately
                    self.translator.reset_provider("anthropic")
                    self._schedule_menu_rebuild()
                    self._notify(
                        "WhisperHUD",
                        "API Key Saved",
                        "Anthropic key validated and saved securely."
                    )
                else:
                    self._notify(
                        "WhisperHUD",
                        "Invalid API Key",
                        error or "Key validation failed"
                    )

            threading.Thread(target=do_validate, daemon=True).start()

    def _applescript_input_dialog(
        self,
        title: str,
        message: str,
        default: str = "",
        hidden: bool = False,
    ) -> Optional[str]:
        """Show an AppleScript input dialog that supports copy-paste."""
        import subprocess

        # Escape quotes for AppleScript
        message_escaped = escape_applescript_string(message).replace('\n', '\\n')
        default_escaped = escape_applescript_string(default)
        title_escaped = escape_applescript_string(title)
        hidden_clause = " with hidden answer" if hidden else ""

        script = f'''
        tell application "System Events"
            activate
            set userInput to display dialog "{message_escaped}" default answer "{default_escaped}" with title "{title_escaped}" buttons {{"Cancel", "Save"}} default button "Save"{hidden_clause}
            if button returned of userInput is "Save" then
                return text returned of userInput
            else
                return ""
            end if
        end tell
        '''

        try:
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            logger.error(f"Dialog error: {e}")

        return None

    def _toggle_widget(self, sender):
        """Toggle floating widget visibility."""
        self.config.show_widget = not self.config.show_widget
        self.config.save()
        if self.widget:
            if self.config.show_widget:
                self.widget.show()
            else:
                self.widget.hide()
        self._schedule_menu_rebuild()

    def _set_widget_size(self, size: str):
        """Change widget size."""
        self.config.widget_size = size
        self.config.save()
        if self.widget:
            self.widget.set_size(size)
        self._schedule_menu_rebuild()

    def _toggle_hud(self, sender):
        """Toggle HUD visibility setting."""
        self.config.show_hud = not self.config.show_hud
        self.config.save()
        self.hud.set_enabled(self.config.show_hud)
        self._schedule_menu_rebuild()

    def _toggle_auto_stop(self, sender):
        """Toggle auto-stop on silence setting."""
        self.config.auto_stop = not self.config.auto_stop
        self.config.save()
        self._schedule_menu_rebuild()

    def _set_max_duration(self, seconds: int):
        """Set max recording duration."""
        self.config.max_recording_duration = seconds
        self.config.save()
        self._schedule_menu_rebuild()

    def _toggle_auto_paste(self, sender):
        """Toggle auto-paste setting."""
        self.config.auto_paste = not self.config.auto_paste
        self.config.save()
        self._schedule_menu_rebuild()

    def _toggle_restore_clipboard(self, sender):
        """Toggle clipboard restoration setting."""
        self.config.restore_clipboard = not self.config.restore_clipboard
        self.config.save()
        self._schedule_menu_rebuild()

    def _toggle_play_sound(self, sender):
        """Toggle completion sound setting."""
        self.config.play_sound = not self.config.play_sound
        self.config.save()
        self._schedule_menu_rebuild()

    def _toggle_history(self, sender):
        """Toggle transcription history storage."""
        # Can't enable history in private mode
        if self.config.private_mode:
            return

        self.config.history_enabled = not self.config.history_enabled
        if not self.config.history_enabled:
            self.config.clear_history()
        else:
            self.config.save()
        self._schedule_menu_rebuild()

    def _toggle_private_mode(self, sender):
        """Toggle private mode (no transcription storage)."""
        if self.config.private_mode:
            # Disabling private mode
            response = rumps.alert(
                title="Turn Off Private Mode?",
                message=(
                    "You'll be able to save transcription history again.\n\n"
                    "History saving is off by default—you can enable it "
                    "separately if you want."
                ),
                ok="Turn Off",
                cancel="Keep Private"
            )

            if response == 1:
                self.config.disable_private_mode()
                self._notify(
                    "WhisperHUD",
                    "Private Mode Off",
                    "You can now save transcription history if desired."
                )
                self._schedule_menu_rebuild()
        else:
            # Enabling private mode - explain clearly
            history_count = len(self.config.history)
            history_warning = ""
            if history_count > 0:
                history_warning = f"\n\n⚠️ Your {history_count} saved transcription(s) will be deleted."

            response = rumps.alert(
                title="Enable Private Mode?",
                message=(
                    "Private Mode keeps your transcriptions completely private:\n\n"
                    "• Nothing is saved to disk—ever\n"
                    "• Audio files are securely wiped after use\n"
                    "• A 🔒 icon shows when active\n\n"
                    "You can still copy/paste transcriptions normally, "
                    "they just won't be stored."
                    f"{history_warning}"
                ),
                ok="Enable Private Mode",
                cancel="Cancel"
            )

            if response == 1:
                self.config.enable_private_mode()
                self._notify(
                    "WhisperHUD",
                    "🔒 Private Mode On",
                    "Your transcriptions won't be saved anywhere."
                )
                self._schedule_menu_rebuild()

    def _toggle_history_encryption(self, sender):
        """Toggle history encryption at rest."""
        if self.config.private_mode:
            return

        if self.config.history_encrypted:
            # Disabling encryption
            response = rumps.alert(
                title="Turn Off Encryption?",
                message=(
                    "New transcriptions will be saved without encryption.\n\n"
                    "Previously encrypted items stay encrypted on disk.\n"
                    "They are readable again after passphrase unlock."
                ),
                ok="Turn Off",
                cancel="Keep Encrypted"
            )

            if response == 1:
                self.config.disable_history_encryption()
                self._notify(
                    "WhisperHUD",
                    "Encryption Off",
                    "New transcriptions will be saved unencrypted."
                )
        else:
            if self._credential_mode() != "passphrase":
                rumps.alert(
                    title="Passphrase Mode Required",
                    message=(
                        "History encryption uses passphrase-based unlock.\n\n"
                        "Set API Key Storage to 'Passphrase (Encrypted Local)', "
                        "then enable history encryption."
                    ),
                )
                return

            if not self._ensure_passphrase_unlocked(allow_create=True):
                return

            # Enabling encryption - should already be installed if we get here
            success = self.config.enable_history_encryption()
            if success:
                self._ensure_history_encryption_session(create_if_missing=False, prompt_unlock=False)
                self._notify(
                    "WhisperHUD",
                    "🔐 Encryption On",
                    "Your transcription history is encrypted for this session."
                )
            else:
                rumps.alert(
                    title="Could Not Enable Encryption",
                    message=(
                        "Unlock passphrase storage in Privacy & Security and try again.\n\n"
                        "History encryption does not use macOS Keychain."
                    ),
                )
                return

        self._schedule_menu_rebuild()

    def _setup_encryption(self, sender):
        """Set up encryption if the required dependency is already available."""
        from .encryption import is_cryptography_installed

        if self._credential_mode() != "passphrase":
            rumps.alert(
                title="Passphrase Mode Required",
                message=(
                    "History encryption uses passphrase-based unlock.\n\n"
                    "Set API Key Storage to 'Passphrase (Encrypted Local)' first."
                ),
            )
            return

        if is_cryptography_installed():
            # Already installed, just enable
            self._toggle_history_encryption(sender)
            return

        self._show_encryption_setup_help()

    def _show_encryption_setup_help(self):
        """Explain how to enable encryption without installing code at runtime."""
        import sys

        install_cmd = f'"{sys.executable}" -m pip install "cryptography>=43.0.0"'
        rumps.alert(
            title="Encryption Setup Required",
            message=(
                "This WhisperHUD install is missing the encryption dependency.\n\n"
                "For safety, WhisperHUD does not download or run new code at runtime.\n\n"
                "To enable encrypted history:\n"
                "1. Reinstall or update WhisperHUD, or\n"
                "2. If you're running from source, install the dependency in this environment:\n"
                f"{install_cmd}\n\n"
                "Then restart WhisperHUD and enable encryption again."
            ),
        )

    def _toggle_notifications(self, sender):
        """Toggle system notifications."""
        self.config.show_notifications = not self.config.show_notifications
        self.config.save()
        self._schedule_menu_rebuild()

    def _set_audio_device(self, device_id):
        """Set the audio input device with validation."""
        from .recorder import is_valid_input_device, get_device_name

        # Validate the device is actually an input device
        if device_id is not None and not is_valid_input_device(device_id):
            device_name = get_device_name(device_id)
            logger.warning(f"Attempted to set invalid input device: {device_name} (ID: {device_id})")
            self._notify(
                "WhisperHUD",
                "Invalid Device",
                f"'{device_name}' is not an audio input device. Using system default."
            )
            device_id = None  # Fall back to system default

        self.config.audio_input_device = device_id
        self.config.save()
        # Update the recorder
        self.recorder.set_device(device_id)
        self._schedule_menu_rebuild()

        # Get device name for notification
        device_name = get_device_name(device_id)
        self._notify(
            "WhisperHUD",
            "Audio Device Changed",
            f"Now using: {device_name}"
        )

    def _toggle_launch_at_login(self, sender):
        """Toggle launch at login."""
        from .launch_agent import is_launch_at_login_enabled, toggle_launch_at_login

        current = is_launch_at_login_enabled()
        success, message = toggle_launch_at_login(not current)

        if success:
            self.config.launch_at_login = not current
            self.config.save()
            self._schedule_menu_rebuild()
            self._notify("WhisperHUD", "Startup Setting", message)
        else:
            rumps.alert(
                title="Error",
                message=message
            )

    def _export_settings(self, sender):
        """Export settings to a file."""
        try:
            from AppKit import NSSavePanel
            import os

            panel = NSSavePanel.savePanel()
            panel.setTitle_("Export WhisperHUD Settings")
            panel.setNameFieldStringValue_("whisper-hud-settings.json")
            panel.setAllowedFileTypes_(["json"])

            if panel.runModal() == 1:  # OK clicked
                filepath = str(panel.URL().path())
                if self.config.export_settings(filepath):
                    self._notify(
                        "WhisperHUD",
                        "Settings Exported",
                        f"Saved to {os.path.basename(filepath)}"
                    )
                else:
                    rumps.alert(
                        title="Export Failed",
                        message="Failed to export settings. Check the log for details."
                    )
        except Exception as e:
            logger.error(f"Export settings error: {e}")
            rumps.alert(
                title="Export Failed",
                message=str(e)
            )

    def _import_settings(self, sender):
        """Import settings from a file."""
        try:
            from AppKit import NSOpenPanel

            panel = NSOpenPanel.openPanel()
            panel.setTitle_("Import WhisperHUD Settings")
            panel.setAllowedFileTypes_(["json"])
            panel.setCanChooseFiles_(True)
            panel.setCanChooseDirectories_(False)

            if panel.runModal() == 1:  # OK clicked
                filepath = str(panel.URL().path())
                from .config import Config
                success, message, imported_config = Config.import_settings(filepath)

                if success and imported_config:
                    # Confirm import
                    response = rumps.alert(
                        title="Import Settings",
                        message=(
                            f"{message}\n\n"
                            "This will replace your current settings.\n"
                            "API keys and history will not be affected.\n\n"
                            "Continue?"
                        ),
                        ok="Import",
                        cancel="Cancel"
                    )

                    if response == 1:
                        imported_config = self.config.merge_imported_config(imported_config)

                        self.config.update_from(imported_config)
                        self.config.save()

                        # Reload components
                        self.transcriber.reload_config()
                        self.translator.reload_config()
                        self.recorder.set_device(self.config.audio_input_device)
                        self._restart_hotkey_listener()
                        self._apply_appearance_to_components()
                        self._schedule_menu_rebuild()

                        self._notify(
                            "WhisperHUD",
                            "Settings Imported",
                            "Your settings have been updated."
                        )
                else:
                    rumps.alert(
                        title="Import Failed",
                        message=message
                    )
        except Exception as e:
            logger.error(f"Import settings error: {e}")
            rumps.alert(
                title="Import Failed",
                message=str(e)
            )

    def _show_about(self, sender):
        """Show about dialog."""
        logger.debug("_show_about callback called!")
        try:
            from . import __version__

            logger.debug("About to show rumps.alert...")
            rumps.alert(
                title="About WhisperHUD",
                message=(
                    f"Version {__version__}\n\n"
                    f"Voice-to-text transcription for macOS\n\n"
                    "Fast, accurate speech-to-text with support for\n"
                    "multiple providers (OpenAI, Gemini, Apple, Parakeet)\n"
                    "and real-time translation."
                ),
                ok="OK"
            )
        except Exception as e:
            logger.error(f"Error in _show_about: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _open_github(self, sender):
        """Open the GitHub repository in browser."""
        import subprocess
        subprocess.run(
            ["open", "https://github.com/jvogan/whisper-hud"],
            capture_output=True
        )

    def _show_system_info(self, sender):
        """Show system information dialog."""
        try:
            from . import __version__
            import platform

            # Get provider info
            storage_mode = self._credential_mode()
            storage_status = get_storage_mode_label(storage_mode)
            if self._is_passphrase_store_locked():
                provider_status = "Locked (unlock required)"
            elif storage_mode == "keychain" and not self._should_query_keychain():
                provider_status = "Deferred (local mode)"
            else:
                configured = get_configured_providers()
                provider_status = ", ".join(configured) if configured else "None configured"

            # Get translation info
            trans_provider = self.translator.get_current_provider()
            trans_model = self.translator.get_current_model()

            rumps.alert(
                title="System Information",
                message=(
                    f"WhisperHUD v{__version__}\n\n"
                    f"── System ──\n"
                    f"macOS: {platform.mac_ver()[0]}\n"
                    f"Python: {platform.python_version()}\n"
                    f"Architecture: {platform.machine()}\n\n"
                    f"── Configuration ──\n"
                    f"Transcription: {self.config.default_provider}\n"
                    f"Translation: {trans_provider} ({trans_model})\n"
                    f"API Key Storage: {storage_status}\n"
                    f"API Keys: {provider_status}\n\n"
                    f"── Stats ──\n"
                    f"Total transcriptions: {self.config.total_transcriptions}\n"
                    f"Total cost: ${self.config.total_cost:.4f}"
                ),
                ok="OK"
            )
        except Exception as e:
            logger.error(f"Error in _show_system_info: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _check_for_updates(self, sender):
        """Check for app updates using Sparkle."""
        try:
            from .sparkle_updater import check_for_updates
            check_for_updates()
        except ImportError:
            logger.debug("Sparkle updater module not available")
            self._show_manual_update_dialog()
        except Exception as e:
            logger.error(f"Update check failed: {e}")
            self._show_manual_update_dialog()

    def _show_manual_update_dialog(self):
        """Show dialog when Sparkle isn't available."""
        from . import __version__
        response = rumps.alert(
            title="Check for Updates",
            message=(
                f"Current version: {__version__}\n\n"
                "Automatic updates are not available in this build.\n"
                "Please check GitHub for the latest release."
            ),
            ok="OK",
            other="Open GitHub Releases"
        )

        if response == 0:  # "Open GitHub Releases" clicked
            import subprocess
            subprocess.run(
                ["open", "https://github.com/jvogan/whisper-hud/releases"],
                capture_output=True
            )

    def _play_completion_sound(self):
        """Play a short system sound on successful completion."""
        if not self.config.play_sound:
            return

        # Use a standard macOS system sound
        sound_file = "/System/Library/Sounds/Pop.aiff"

        try:
            import subprocess

            subprocess.Popen(
                ["afplay", sound_file],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            logger.debug(f"Failed to play completion sound: {e}")

    def _notify(self, title: str, subtitle: str, message: str, force: bool = False) -> None:
        """
        Send a user notification on the main thread when possible.

        Args:
            title: Notification title
            subtitle: Notification subtitle
            message: Notification body
            force: If True, show even if notifications are disabled
        """
        # Skip if notifications are disabled (unless forced)
        if not force and not self.config.show_notifications:
            return

        def _send():
            rumps.notification(title, subtitle, message)

        if threading.current_thread() is not threading.main_thread():
            try:
                from PyObjCTools import AppHelper
                AppHelper.callAfter(_send)
                return
            except Exception:
                pass

        _send()

    def _set_title(self, title: str) -> None:
        """Set the menu bar title on the main thread when possible."""
        def _apply():
            self.title = title

        if threading.current_thread() is not threading.main_thread():
            try:
                from PyObjCTools import AppHelper
                AppHelper.callAfter(_apply)
                return
            except Exception:
                pass

        _apply()

    def _get_idle_icon(self) -> str:
        """Get the idle icon, with indicators for special modes."""
        base_icon = self.ICON_IDLE

        # Private mode indicator takes precedence
        if self.config.private_mode:
            return f"{MenuBarIcons.PRIVATE}"

        # Target lock indicator
        target_enabled = self.config.paste_target_enabled and self.config.paste_target_type != "focused"
        if target_enabled:
            return f"{base_icon}📍"

        return base_icon

    def _get_paste_target_display_name(self) -> str:
        """Get a short display name for the current paste target."""
        return self._format_target_for_menu(
            self.config.paste_target_type,
            self.config.paste_target_identifier,
            short=True
        )

    def _format_target_for_menu(self, target_type: str, target_id: str, short: bool = False) -> str:
        """Format a target type+id for display in menu."""
        if target_type == "focused":
            return "Focused"
        elif target_type == "tmux":
            return f"tmux:{target_id}" if short else f"tmux: {target_id}"
        elif target_type == "iterm2":
            return "iTerm2"
        elif target_type == "terminal":
            return "Terminal"
        else:
            # App name - truncate if short mode
            if short and len(target_id) > 13:
                return target_id[:12] + "…"
            return target_id

    def _get_valid_recent_targets(self) -> list:
        """Get recent targets that are still available (uses cached data for speed)."""
        valid = []

        # Use cached data instead of making subprocess calls for each check
        cached_tmux = set(self._cached_tmux_sessions) if hasattr(self, '_cached_tmux_sessions') else set()
        cached_apps = set(self._cached_running_apps) if hasattr(self, '_cached_running_apps') else set()
        iterm_running = getattr(self, '_cached_iterm2_running', False)
        terminal_running = getattr(self, '_cached_terminal_running', False)

        for target_key in self.config.paste_target_recent:
            if ":" not in target_key:
                continue
            target_type, target_id = target_key.split(":", 1)

            # Check availability using cached data (fast)
            is_available = False
            if target_type == "focused":
                is_available = True
            elif target_type == "tmux":
                is_available = target_id in cached_tmux
            elif target_type == "iterm2":
                is_available = iterm_running
            elif target_type == "terminal":
                is_available = terminal_running
            elif target_type == "app":
                is_available = target_id in cached_apps

            if is_available:
                # Don't include if it's the current target (will be shown as selected elsewhere)
                if not (self.config.paste_target_enabled
                        and self.config.paste_target_type == target_type
                        and self.config.paste_target_identifier == target_id):
                    valid.append(target_key)
        return valid

    def _add_to_recent_targets(self, target_type: str, target_id: str):
        """Add a target to the recent targets list."""
        if target_type == "focused":
            return  # Don't track "focused" as a recent target

        target_key = f"{target_type}:{target_id}"

        # Remove if already in list (will re-add at front)
        recent = [t for t in self.config.paste_target_recent if t != target_key]

        # Add to front
        recent.insert(0, target_key)

        # Keep only last 10
        self.config.paste_target_recent = recent[:10]

    def _disable_paste_target(self, sender):
        """Disable paste target lock (return to focused window behavior)."""
        self.config.paste_target_enabled = False
        self.config.paste_target_type = "focused"
        self.config.paste_target_identifier = ""
        self.config.save()
        self._schedule_menu_rebuild()

    def _toggle_paste_return_focus(self, sender):
        """Toggle return focus after paste setting."""
        self.config.paste_target_return_focus = not self.config.paste_target_return_focus
        self.config.save()
        self._schedule_menu_rebuild()

    def _set_paste_target(self, target_type: str, identifier: str, notify: bool = True):
        """Set the paste target."""
        # If selecting "focused", just disable target lock
        if target_type == "focused":
            self._disable_paste_target(None)
            return

        # Check if this is actually a change
        was_enabled = self.config.paste_target_enabled
        was_same_target = (
            self.config.paste_target_type == target_type
            and self.config.paste_target_identifier == identifier
        )

        self.config.paste_target_type = target_type
        self.config.paste_target_identifier = identifier
        self.config.paste_target_enabled = True

        # Track in recent targets
        self._add_to_recent_targets(target_type, identifier)

        self.config.save()

        # Only notify if this is a new target selection (not just re-selecting same target)
        if notify and not (was_enabled and was_same_target):
            target_name = self._get_paste_target_display_name()
            self._notify(
                "WhisperHUD",
                "Paste Target Locked",
                f"Transcriptions → {target_name}"
            )

        self._schedule_menu_rebuild()

    def _refresh_paste_targets_cache(self):
        """Refresh cached paste target data (called on init and manual refresh)."""
        self._cached_tmux_sessions = self.paste_target_manager.get_tmux_sessions()
        self._cached_iterm2_running = self.paste_target_manager.is_iterm2_running()
        self._cached_terminal_running = self.paste_target_manager.is_terminal_running()
        self._cached_running_apps = self.paste_target_manager.get_running_apps()

    def _refresh_paste_targets(self, sender):
        """Refresh available paste targets (rescans running apps/sessions)."""
        self._refresh_paste_targets_cache()
        self._schedule_menu_rebuild()

    def _is_target_available_cached(self, target_type: str, identifier: str) -> bool:
        """Check if target is available using cached data (fast, no subprocess calls)."""
        if target_type == "focused":
            return True
        elif target_type == "tmux":
            cached = getattr(self, '_cached_tmux_sessions', [])
            return identifier in cached
        elif target_type == "iterm2":
            return getattr(self, '_cached_iterm2_running', False)
        elif target_type == "terminal":
            return getattr(self, '_cached_terminal_running', False)
        elif target_type == "app":
            cached = getattr(self, '_cached_running_apps', [])
            return identifier in cached
        return False

    def _paste_to_target(self, text: str) -> bool:
        """
        Paste text to the configured target.

        Returns True if successful, False otherwise.
        """
        # Check if target lock is enabled and target is not focused
        if not self.config.paste_target_enabled or self.config.paste_target_type == "focused":
            # Default: paste to focused window
            return insert_text(text, restore_clipboard=self.config.restore_clipboard)

        target_type = self.config.paste_target_type
        target_id = self.config.paste_target_identifier
        target_display = self._get_paste_target_display_name()

        # Check if target is still available (using cached data for speed)
        if not self._is_target_available_cached(target_type, target_id):
            # Target not available, fallback to focused window
            self._notify(
                "WhisperHUD",
                "Target Unavailable",
                f"{target_display} not found. Pasted to focused window."
            )
            return insert_text(text, restore_clipboard=self.config.restore_clipboard)

        # Create target and paste
        target = PasteTarget(
            type=TargetType(target_type),
            name=target_id,
            identifier=target_id
        )

        success = self.paste_target_manager.paste_to_target(
            text,
            target,
            return_focus=self.config.paste_target_return_focus,
            restore_clipboard=self.config.restore_clipboard
        )

        if not success:
            # Paste failed, notify user
            self._notify(
                "WhisperHUD",
                "Paste Failed",
                f"Could not paste to {target_display}. Try refreshing targets."
            )

        return success

    def _build_hotkey_set(self):
        """Build a set of keys from config hotkey list."""
        hotkey_set = set()
        for key_name in self.config.hotkey:
            key = string_to_key(key_name)
            if key:
                hotkey_set.add(key)
        return hotkey_set if hotkey_set else HotkeyListener.DEFAULT_HOTKEY

    def _change_hotkey(self, _):
        """Start hotkey capture process."""
        if self._is_capturing_hotkey:
            return

        self._is_capturing_hotkey = True

        # Pause the main hotkey listener during capture
        self.hotkey_listener.stop()

        # Show notification to user
        self._notify(
            "WhisperHUD",
            "Recording Hotkey",
            "Press your desired key combination now..."
        )

        # Start capture
        self._hotkey_capture = HotkeyCapture(
            on_captured=self._on_hotkey_captured,
            on_key_change=None  # We'll use notifications instead of live preview
        )
        self._hotkey_capture.start()

        # Set a timeout to cancel capture after 10 seconds
        def timeout():
            if self._is_capturing_hotkey:
                self._cancel_hotkey_capture()
                self._notify(
                    "WhisperHUD",
                    "Hotkey Capture Cancelled",
                    "No keys were pressed. Using previous hotkey."
                )

        threading.Timer(10.0, timeout).start()

    def _on_hotkey_captured(self, key_set, key_names):
        """Called when hotkey capture is complete."""
        if not self._is_capturing_hotkey:
            return

        self._is_capturing_hotkey = False

        if self._hotkey_capture:
            self._hotkey_capture.stop()
            self._hotkey_capture = None

        if key_names:
            # Save the new hotkey
            self.config.hotkey = key_names
            self.config.save()

            # Update the listener
            hotkey_set = self._build_hotkey_set()
            self.hotkey_listener = HotkeyListener(
                on_start=self._start_recording,
                on_stop=self._stop_recording,
                hotkey=hotkey_set,
                mode=self.config.hotkey_mode
            )
            self.hotkey_listener.start()

            # Notify user
            display = format_hotkey_display(key_names)
            self._notify(
                "WhisperHUD",
                "Hotkey Changed",
                f"New hotkey: {display}"
            )

            self._schedule_menu_rebuild()
        else:
            # Restart listener with old hotkey
            self._restart_hotkey_listener()

    def _cancel_hotkey_capture(self):
        """Cancel hotkey capture and restore listener."""
        self._is_capturing_hotkey = False

        if self._hotkey_capture:
            self._hotkey_capture.stop()
            self._hotkey_capture = None

        self._restart_hotkey_listener()

    def _restart_hotkey_listener(self):
        """Restart the hotkey listener with current config."""
        if self.hotkey_listener.is_listening():
            self.hotkey_listener.stop()

        hotkey_set = self._build_hotkey_set()
        self.hotkey_listener = HotkeyListener(
            on_start=self._start_recording,
            on_stop=self._stop_recording,
            hotkey=hotkey_set,
            mode=self.config.hotkey_mode
        )
        self.hotkey_listener.start()

    def _reset_hotkey(self, _):
        """Reset hotkey to default (Cmd+Shift+Space)."""
        self.config.hotkey = ["cmd", "shift", "space"]
        self.config.save()

        self.hotkey_listener.update_hotkey(HotkeyListener.DEFAULT_HOTKEY)

        self._notify(
            "WhisperHUD",
            "Hotkey Reset",
            "Hotkey reset to ⌘⇧Space"
        )

        self._schedule_menu_rebuild()

    def _set_hotkey_mode(self, mode: str):
        """Change the hotkey mode."""
        if self.config.hotkey_mode == mode:
            return

        self.config.hotkey_mode = mode
        self.config.save()

        self.hotkey_listener.update_mode(mode)

        mode_name = "Hold to record" if mode == "push_to_talk" else "Press to toggle"
        self._notify(
            "WhisperHUD",
            "Mode Changed",
            f"Recording mode: {mode_name}"
        )

        self._schedule_menu_rebuild()

    def _copy_from_history(self, index: int):
        """Copy a history item to clipboard."""
        import pyperclip
        history = self.config.get_history()
        if index < len(history):
            item = history[index]
            text = item.get("text", "")
            if text:
                pyperclip.copy(text)
                self._notify(
                    "WhisperHUD",
                    "Copied to Clipboard",
                    text[:50] + "..." if len(text) > 50 else text
                )

    def _clear_history(self, sender):
        """Clear all transcription history."""
        response = rumps.alert(
            title="Clear History",
            message="Are you sure you want to clear all transcription history?",
            ok="Clear",
            cancel="Cancel"
        )
        if response == 1:
            self.config.clear_history()
            self._schedule_menu_rebuild()
            self._notify(
                "WhisperHUD",
                "History Cleared",
                "All transcription history has been cleared."
            )

    def _reset_statistics(self, sender):
        """Reset transcription statistics."""
        stats = self.transcriber.get_stats()
        response = rumps.alert(
            title="Reset Statistics",
            message=(
                f"This will reset your transcription statistics:\n\n"
                f"• {stats['total_transcriptions']} transcriptions\n"
                f"• ${stats['total_cost']:.4f} estimated cost\n\n"
                f"Are you sure?"
            ),
            ok="Reset",
            cancel="Cancel"
        )
        if response == 1:
            self.config.reset_stats()
            self._schedule_menu_rebuild()
            self._notify(
                "WhisperHUD",
                "Statistics Reset",
                "Transcription statistics have been reset."
            )

    def _clear_image_cache(self, sender):
        """Clear the image cache."""
        from .image_processor import clear_cache
        clear_cache()
        self._schedule_menu_rebuild()
        self._notify(
            "WhisperHUD",
            "Cache Cleared",
            "Image cache has been cleared."
        )

    def _delete_api_key(self, provider: str):
        """Delete a specific API key."""
        if self._is_passphrase_mode() and not self._ensure_passphrase_unlocked():
            return

        provider_name = self._get_provider_display_name(provider)
        response = rumps.alert(
            title=f"Delete {provider_name} API Key",
            message=(
                f"Are you sure you want to delete your {provider_name} API key?\n\n"
                f"You'll need to re-enter it to use this provider again."
            ),
            ok="Delete",
            cancel="Cancel"
        )
        if response == 1:
            if not delete_api_key(provider):
                rumps.alert(
                    title="Delete Failed",
                    message="Could not delete API key. Unlock storage first if needed."
                )
                return

            self._reset_cloud_clients()
            self._schedule_menu_rebuild()
            self._notify(
                "WhisperHUD",
                "API Key Deleted",
                f"{provider_name} API key has been removed."
            )

    def _delete_all_api_keys(self, sender):
        """Delete all API keys."""
        if self._is_passphrase_mode() and not self._ensure_passphrase_unlocked():
            return

        configured = get_configured_providers()
        if not configured:
            rumps.alert(
                title="No API Keys",
                message="There are no API keys to delete."
            )
            return

        response = rumps.alert(
            title="Delete All API Keys",
            message=(
                f"This will delete {len(configured)} API key(s):\n\n"
                f"• {', '.join(self._get_provider_display_name(p) for p in configured)}\n\n"
                f"You'll need to re-enter them to use these providers again.\n\n"
                f"Are you sure?"
            ),
            ok="Delete All",
            cancel="Cancel"
        )
        if response == 1:
            for provider in configured:
                delete_api_key(provider)
            self._reset_cloud_clients()
            self._schedule_menu_rebuild()
            self._notify(
                "WhisperHUD",
                "API Keys Deleted",
                "All API keys have been removed."
            )

    def _reset_all_settings(self, sender):
        """Reset all settings to defaults."""
        from .image_processor import clear_cache
        from .config import Config

        response = rumps.alert(
            title="Reset All Settings",
            message=(
                "This will reset WhisperHUD to factory defaults:\n\n"
                "• Clear all transcription history\n"
                "• Reset statistics\n"
                "• Reset hotkey to ⌘⇧Space\n"
                "• Reset appearance to default\n"
                "• Clear image cache\n\n"
                "Note: API keys will NOT be deleted.\n\n"
                "Are you sure?"
            ),
            ok="Reset All",
            cancel="Cancel"
        )
        if response == 1:
            # Reset to defaults
            fresh_config = Config()

            # Preserve API key related state by not deleting them
            # Just reset the config file
            self.config.update_from(fresh_config)
            self.config.save()

            # Clear caches
            clear_cache()

            # Reset hotkey listener
            self._restart_hotkey_listener()

            # Rebuild UI
            self._schedule_menu_rebuild()
            self._apply_appearance_to_components()

            self._notify(
                "WhisperHUD",
                "Settings Reset",
                "All settings have been reset to defaults."
            )

    def _toggle_translation(self, sender):
        """Toggle translation on/off."""
        enabling = not self.config.translation_enabled
        logger.debug(f"_toggle_translation called, enabling={enabling}")

        if enabling and not self._ensure_translation_provider_credentials(self.config.translation_provider):
            return

        # Optimistically toggle on/off to keep the menu responsive
        self.config.translation_enabled = enabling
        self.config.save()
        logger.debug("Config saved, scheduling menu rebuild")
        self._schedule_menu_rebuild()

        if not enabling:
            logger.debug("Translation disabled, returning early")
            return

        # Check availability off the UI thread to avoid freezing the menu
        def _check_availability():
            try:
                available = self.translator.is_available()
            except Exception:
                available = False

            if available:
                return

            provider_name = self.translator.provider.display_name

            def _revert():
                # Only revert if translation is still enabled
                if not self.config.translation_enabled:
                    return

                self.config.translation_enabled = False
                self.config.save()
                self._schedule_menu_rebuild()

                rumps.alert(
                    title="Translation Not Available",
                    message=(
                        f"Translation provider '{provider_name}' is not available.\n\n"
                        f"Please configure the provider or select a different one."
                    )
                )

            try:
                from PyObjCTools import AppHelper
                AppHelper.callAfter(_revert)
            except Exception:
                _revert()

        threading.Thread(target=_check_availability, daemon=True).start()

    def _set_translation_provider(self, provider_id: str):
        """Set the translation provider."""
        if not self._ensure_translation_provider_credentials(provider_id):
            return
        self.translator.set_provider(provider_id)
        self._schedule_menu_rebuild()

    def _set_translation_provider_and_model(self, provider_id: str, model_id: str):
        """Set both translation provider and model in one action."""
        if not self._ensure_translation_provider_credentials(provider_id):
            return
        self.translator.set_provider(provider_id)
        self.translator.set_model(model_id)
        self._schedule_menu_rebuild()

    def _set_target_language(self, lang_code: str):
        """Set the target translation language."""
        self.config.target_language = lang_code
        self.config.add_recent_target_language(lang_code)
        self._schedule_menu_rebuild()

    def _set_source_language(self, lang_code: str):
        """Set the source translation language."""
        self.config.source_language = lang_code
        if lang_code == "auto":
            self.config.save()
        else:
            self.config.add_recent_source_language(lang_code)
        self._schedule_menu_rebuild()

    def _swap_translation_languages(self, sender=None):
        """Swap source and target languages (defaults auto -> en)."""
        source_lang = self.config.source_language
        if source_lang == "auto":
            source_lang = "en"

        self.config.source_language = self.config.target_language
        self.config.target_language = source_lang
        self.config.save()
        self._schedule_menu_rebuild()

    def _set_translation_model(self, model_id: str):
        """Set the translation model."""
        self.translator.set_model(model_id)
        self._schedule_menu_rebuild()

    def _show_ollama_install_help(self, sender):
        """Show help for installing Ollama."""
        rumps.alert(
            title="Install Ollama",
            message=(
                "Ollama is required for local translation.\n\n"
                "Install with Homebrew:\n"
                "  brew install ollama\n\n"
                "Or download from:\n"
                "  https://ollama.ai\n\n"
                "After installing, run:\n"
                "  ollama serve"
            )
        )

    def _show_ollama_start_help(self, sender):
        """Show help for starting Ollama."""
        rumps.alert(
            title="Start Ollama",
            message=(
                "Ollama is installed but not running.\n\n"
                "Start it by running:\n"
                "  ollama serve\n\n"
                "Or start the Ollama app if you installed\n"
                "the desktop version."
            )
        )

    def _download_translation_model(self, sender):
        """Download the translation model."""
        # Check disk space first
        has_space, available_gb, required_gb = self.translator.check_disk_space()
        if not has_space:
            rumps.alert(
                title="Insufficient Disk Space",
                message=(
                    f"Model requires {required_gb:.1f}GB but only "
                    f"{available_gb:.1f}GB available.\n\n"
                    f"Free up some disk space and try again."
                )
            )
            return

        # Show confirmation
        model_info = next(
            (m for m in self.translator.get_models()
             if m["id"] == self.translator.get_current_model()),
            None
        )
        if not model_info:
            return

        response = rumps.alert(
            title="Download Translation Model",
            message=(
                f"Download {model_info['name']}?\n\n"
                f"Size: {model_info.get('size_gb', 0)}GB\n"
                f"RAM required: {model_info.get('ram_required', 'N/A')}\n\n"
                f"This may take a few minutes depending on\n"
                f"your internet connection."
            ),
            ok="Download",
            cancel="Cancel"
        )

        if response != 1:  # User clicked Cancel
            return

        # Show downloading notification
        self._notify(
            "WhisperHUD",
            "Downloading Translation Model",
            "This will run in the background. You'll be notified when complete."
        )

        # Download in background thread
        def do_download():
            def progress_callback(msg):
                logger.debug(f"Translation model download: {msg}")

            success = self.translator.download_model(progress_callback)

            if success:
                self._notify(
                    "WhisperHUD",
                    "Download Complete",
                    "Translation model is ready to use!"
                )
            else:
                self._notify(
                    "WhisperHUD",
                    "Download Failed",
                    "Check console for details."
                )

            # Refresh menu
            self._schedule_menu_rebuild()

        threading.Thread(target=do_download, daemon=True).start()

    def _toggle_streaming(self, sender):
        """Toggle streaming display on/off."""
        self.config.streaming_enabled = not self.config.streaming_enabled
        self.config.save()
        self.streaming_panel.set_enabled(self.config.streaming_enabled)
        self._schedule_menu_rebuild()

    def _toggle_ollama_auto_start(self, sender):
        """Toggle Ollama auto-start setting."""
        self.config.ollama_auto_start = not self.config.ollama_auto_start
        self.config.save()
        self._schedule_menu_rebuild()

    def _show_ollama_setup(self, sender):
        """Show Ollama setup options based on current status."""
        # Check status (OK to block here since user clicked)
        status = self.translator.get_status()

        if not status.get("ollama_installed", False):
            self._install_ollama(sender)
        elif not status.get("ollama_running", False):
            self._start_ollama(sender)
        elif not status.get("downloaded", False):
            self._download_translation_model(sender)
        else:
            rumps.alert(
                title="Ollama Ready",
                message=f"Ollama is installed and running.\nModel: {status.get('model', 'unknown')}\nSize: {status.get('size_gb', 0)}GB"
            )

    def _install_ollama(self, sender):
        """Install Ollama via Homebrew."""
        # Check if Homebrew is installed
        if not self.translator.is_homebrew_installed():
            rumps.alert(
                title="Homebrew Required",
                message=(
                    "Homebrew is required to install Ollama.\n\n"
                    "Install Homebrew from: https://brew.sh\n\n"
                    "After installing Homebrew, try again."
                )
            )
            return

        response = rumps.alert(
            title="Install Ollama",
            message=(
                "This will install Ollama using Homebrew.\n\n"
                "The installation may take a few minutes.\n"
                "You'll be notified when complete."
            ),
            ok="Install",
            cancel="Cancel"
        )

        if response != 1:
            return

        self._notify(
            "WhisperHUD",
            "Installing Ollama",
            "This will run in the background..."
        )

        def do_install():
            success = self.translator.install_ollama(
                progress_callback=lambda msg: logger.debug(f"Ollama install: {msg}")
            )

            if success:
                self._notify(
                    "WhisperHUD",
                    "Installation Complete",
                    "Ollama is now installed. Starting server..."
                )
                # Auto-start the server
                self._auto_start_ollama()
            else:
                self._notify(
                    "WhisperHUD",
                    "Installation Failed",
                    "Try running: brew install ollama"
                )

            self._schedule_menu_rebuild()

        threading.Thread(target=do_install, daemon=True).start()

    def _start_ollama(self, sender):
        """Start the Ollama server."""
        self._notify(
            "WhisperHUD",
            "Starting Ollama",
            "Starting Ollama server..."
        )

        def do_start():
            success, pid = self.translator.start_ollama_server()

            if success:
                self._notify(
                    "WhisperHUD",
                    "Ollama Started",
                    "Ollama server is now running."
                )
            else:
                self._notify(
                    "WhisperHUD",
                    "Failed to Start",
                    "Try running: ollama serve"
                )

            self._schedule_menu_rebuild()

        threading.Thread(target=do_start, daemon=True).start()

    def _auto_start_ollama(self):
        """Auto-start Ollama if installed but not running."""
        status = self.translator.get_status()
        if status.get("ollama_installed", False) and not status.get("ollama_running", False):
            def do_start():
                success, pid = self.translator.start_ollama_server()
                if success:
                    logger.info("Ollama auto-started successfully")
                    self._schedule_menu_rebuild()

            threading.Thread(target=do_start, daemon=True).start()

    def _show_setup_wizard(self):
        """Show the setup wizard for first-time setup."""
        def on_complete(result):
            logger.info(f"Setup wizard completed: {result}")
            # Reload config changes made by the wizard
            from .config import Config
            self.config.update_from(Config.load())
            self.transcriber.reload_config()
            self.translator.reload_config()
            self._schedule_menu_rebuild()
            self._notify(
                "WhisperHUD",
                "Setup Complete",
                "You're ready to start transcribing! Hold ⌘⇧Space to record."
            )

        def on_cancel():
            logger.info("Setup wizard cancelled")

        self._setup_wizard = show_setup_wizard(
            on_complete=on_complete,
            on_cancel=on_cancel
        )

    def _run_setup_wizard(self, sender):
        """Run the setup wizard from menu."""
        self._show_setup_wizard()

    def _widget_start_recording(self):
        """Called when widget is clicked to start recording."""
        self._start_recording()

    def _widget_stop_recording(self):
        """Called when widget is clicked to stop recording."""
        self._stop_recording()

    def _save_widget_position(self, x: float, y: float):
        """Save widget position to config when dragged."""
        self.config.widget_position = {"x": x, "y": y}
        self.config.save()

    # === Appearance Methods ===

    def _apply_appearance_to_components(self):
        """Apply appearance config to widget and HUD."""
        appearance = self.config.widget_appearance

        if self.widget:
            self.widget.set_appearance(appearance, self.image_processor)

        if self.hud:
            self.hud.set_appearance(appearance)

    def _apply_theme(self, theme_id: str):
        """Apply a preset theme."""
        colors = get_theme_colors(theme_id)
        self.config.set_appearance_theme(theme_id, colors)
        self._apply_appearance_to_components()
        self._schedule_menu_rebuild()

        # Show notification
        theme_name = APPEARANCE_THEMES.get(theme_id, {}).get("name", theme_id)
        self._notify(
            "WhisperHUD",
            "Theme Applied",
            f"Widget theme: {theme_name}"
        )

    def _apply_character_pack(self, pack_id: str):
        """Apply a character pack to the widget."""
        pack = self.character_pack_manager.get_pack(pack_id)
        if pack is None:
            rumps.alert(
                title="Pack Not Found",
                message=f"Character pack '{pack_id}' could not be found."
            )
            return

        if self.character_pack_manager.apply_pack(pack_id):
            # Clear image cache to load new icons
            self.image_processor.clear_cache()
            self._apply_appearance_to_components()
            self._schedule_menu_rebuild()

            self._notify(
                "WhisperHUD",
                "Character Pack Applied",
                f"Now using: {pack.name}"
            )
        else:
            rumps.alert(
                title="Failed to Apply Pack",
                message=f"Could not apply character pack '{pack.name}'."
            )

    def _clear_character_pack(self, sender):
        """Remove character pack and revert to default icons."""
        self.character_pack_manager.clear_pack()
        self.image_processor.clear_cache()
        self._apply_appearance_to_components()
        self._schedule_menu_rebuild()

        self._notify(
            "WhisperHUD",
            "Character Pack Removed",
            "Using default circle icons."
        )

    def _reset_appearance(self, sender):
        """Reset appearance to default."""
        response = rumps.alert(
            title="Reset Appearance",
            message="Reset widget appearance to default theme?",
            ok="Reset",
            cancel="Cancel"
        )
        if response == 1:
            self.config.reset_appearance()
            self.image_processor.clear_cache()
            self._apply_appearance_to_components()
            self._schedule_menu_rebuild()
            self._notify(
                "WhisperHUD",
                "Appearance Reset",
                "Widget appearance reset to default."
            )

    def _open_appearance_editor(self, sender):
        """Open the appearance customization editor."""
        try:
            from .appearance_editor import show_appearance_editor
            show_appearance_editor(
                config=self.config,
                image_processor=self.image_processor,
                on_save=self._on_appearance_saved,
                on_cancel=lambda: None
            )
        except ImportError as e:
            logger.error(f"Could not open appearance editor: {e}")
            rumps.alert(
                title="Editor Not Available",
                message="The appearance editor is not available. Use the theme presets instead."
            )

    def _on_appearance_saved(self, appearance_config):
        """Called when appearance is saved from editor."""
        self._apply_appearance_to_components()
        self._schedule_menu_rebuild()
        self._notify(
            "WhisperHUD",
            "Appearance Saved",
            "Your custom appearance has been applied."
        )

    def _open_pack_creator(self, sender):
        """Open the character pack creator wizard."""
        try:
            from .pack_creator import show_pack_creator
            show_pack_creator(
                image_processor=self.image_processor,
                pack_manager=self.character_pack_manager,
                on_save=self._on_pack_created,
                on_cancel=lambda: None
            )
        except ImportError as e:
            logger.error(f"Could not open pack creator: {e}")
            rumps.alert(
                title="Pack Creator Not Available",
                message="The character pack creator is not available."
            )

    def _on_pack_created(self, pack_id: str):
        """Called when a new pack is created."""
        # Refresh pack list
        self.character_pack_manager.refresh_packs()

        # Apply the new pack
        if self.character_pack_manager.apply_pack(pack_id):
            self.image_processor.clear_cache()
            self._apply_appearance_to_components()
            self._schedule_menu_rebuild()

    def _show_setup_reminder(self):
        """Show reminder to set up API keys."""
        self._notify(
            "WhisperHUD",
            "Welcome!",
            "Click the menu bar icon to add an API key, or switch to Apple (local) to start without one."
        )

    def _cleanup_orphaned_temp_files(self):
        """Clean up any orphaned temp files from crashed sessions."""
        try:
            from .encryption import cleanup_orphaned_temp_files
            cleaned = cleanup_orphaned_temp_files(prefix="whisper_hud")
            if cleaned > 0:
                logger.info(f"Cleaned up {cleaned} orphaned temp file(s) from previous session")
        except Exception as e:
            logger.debug(f"Temp file cleanup error: {e}")

    def _quit(self, _):
        """Clean shutdown."""
        lock_passphrase_store()
        lock_history_encryption()
        self.hotkey_listener.stop()
        self.hud.hide()
        self.streaming_panel.hide()
        if self.widget:
            self.widget.hide()
        self._detach_menu_observers()
        rumps.quit_application()


def print_startup_banner():
    """Print a welcome banner when the app starts."""
    # ANSI color codes
    CYAN = '\033[0;36m'
    WHITE = '\033[1;37m'
    DIM = '\033[0;90m'
    RESET = '\033[0m'

    banner = f"""
{CYAN}       ╭─────────────────────────────────────╮
       │                                     │
       │   ░▒▓  W H I S P E R H U D  ▓▒░    │
       │                                     │
       │      ┌─────────────────────┐        │
       │      │  ◉ ─ ─ ─ ╱╲ ─ ─ ─   │        │
       │      │    ░░▒▒▓▓██▓▓▒▒░░   │        │
       │      └─────────────────────┘        │
       │                                     │
       │   voice → text, invisibly           │
       │                                     │
       ╰─────────────────────────────────────╯{RESET}

  {WHITE}Ready!{RESET} Look for 🎙️ in your menu bar.
  {DIM}Hold ⌘⇧Space to record, release to transcribe.{RESET}
"""
    print(banner)


def run():
    """Entry point for the application."""
    # Print startup banner
    print_startup_banner()

    # Check for accessibility permission
    if not check_accessibility_permission():
        response = rumps.alert(
            title="Accessibility Permission Required",
            message=get_accessibility_error_message(),
            ok="Open Settings",
            cancel="Continue Anyway"
        )
        if response == 1:  # User clicked "Open Settings"
            open_accessibility_settings()

    app = WhisperHUDApp()
    app.run()
