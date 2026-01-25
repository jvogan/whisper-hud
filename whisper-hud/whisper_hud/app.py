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

import rumps
import threading
import time
from typing import Optional

from .logging_config import get_logger
from .recorder import AudioRecorder
from .transcribe import TranscriptionManager
from .translate import TranslationManager
from .hotkey import HotkeyListener, HotkeyCapture, format_hotkey_display, string_to_key
from .hud import create_hud
from .paste import insert_text, check_accessibility_permission, get_accessibility_error_message, open_accessibility_settings
from .paste_targets import PasteTargetManager, PasteTarget, TargetType
from .config import Config
from .keychain import set_api_key, get_api_key, get_configured_providers, mask_api_key, validate_api_key
from .floating_widget import create_floating_widget
from .streaming_panel import create_streaming_panel
from .setup_wizard import show_setup_wizard
from .branding import MenuBarIcons, APPEARANCE_THEMES, get_theme_colors, get_available_themes
from .image_processor import ImageProcessor
from .character_packs import CharacterPackManager

logger = get_logger("app")


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

        # Components
        self.config = Config.load()
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

        # Floating widget for click-to-record
        self.widget = create_floating_widget(
            on_record_start=self._widget_start_recording,
            on_record_stop=self._widget_stop_recording,
            size=self.config.widget_size
        )

        # Apply appearance to widget and HUD
        self._apply_appearance_to_components()

        # State
        self._is_recording = False
        self._is_downloading = False
        self._lock = threading.Lock()
        self._recording_lock = threading.Lock()  # Dedicated lock for recording operations
        self._hotkey_capture: Optional[HotkeyCapture] = None
        self._is_capturing_hotkey = False
        self._setup_wizard = None
        self._level_monitor_thread: Optional[threading.Thread] = None

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

        # Show setup wizard on first run (when no API keys configured and setup not completed)
        configured = get_configured_providers()
        if not configured and not self.config.setup_completed:
            self._show_setup_wizard()
        elif not configured:
            self._show_setup_reminder()

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

        self.menu.clear()

        # Status header with clear status icons
        configured = get_configured_providers()
        provider_name = self._get_provider_display_name(self.config.default_provider)
        current_provider = self.transcriber.get_provider(self.config.default_provider)

        if self._is_downloading:
            status = "⬇️ Downloading model..."
        elif current_provider and current_provider.is_configured():
            status = f"✓ Ready • {provider_name}"
        elif self.config.default_provider in configured:
            status = f"✓ Ready • {provider_name}"
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

        # === Provider Selection with Categories ===
        provider_menu = rumps.MenuItem("Provider")
        providers = self.transcriber.get_available_providers()

        # Cloud providers
        provider_menu.add(rumps.MenuItem("── Cloud ──", callback=None))
        for p in providers:
            if p["category"] != "cloud":
                continue
            is_configured = p["configured"]
            is_default = p["id"] == self.config.default_provider

            # Better status icons: ✓ ready, ⚠️ needs API key
            if is_configured:
                status_icon = "✓"
            else:
                status_icon = "⚠️"  # Needs API key

            prefix = "● " if is_default else "   "

            item = rumps.MenuItem(
                f"{prefix}{p['name']} {status_icon}",
                callback=lambda sender, pid=p["id"]: self._select_provider(pid)
            )
            provider_menu.add(item)

        provider_menu.add(rumps.separator)

        # Local providers
        provider_menu.add(rumps.MenuItem("── Local ──", callback=None))
        for p in providers:
            if p["category"] != "local":
                continue
            is_configured = p["configured"]
            is_default = p["id"] == self.config.default_provider

            # Better status icons for local providers:
            # ✓ ready, ⬇️ needs download, ⚠️ other issue
            if is_configured:
                status_icon = "✓"
            elif p.get("requires_download", False):
                status_icon = "⬇️"  # Needs model download
            else:
                status_icon = "⚠️"  # Other configuration needed

            prefix = "● " if is_default else "   "

            # Add download hint for local providers that need it
            name = p["name"]
            if p.get("requires_download", False) and not is_configured:
                name = f"{name} [download]"

            item = rumps.MenuItem(
                f"{prefix}{name} {status_icon}",
                callback=lambda sender, pid=p["id"], prov=p: self._select_or_download_provider(pid, prov)
            )
            provider_menu.add(item)

        self.menu.add(provider_menu)

        # === Model Selection ===
        model_menu = rumps.MenuItem("Model")
        current_provider = self.transcriber.get_provider(self.config.default_provider)
        if current_provider:
            current_model = current_provider.get_current_model()
            all_models = current_provider.get_models()

            # Check if models have category info (local providers)
            has_categories = any(m.get("category") for m in all_models)

            if has_categories:
                # Group models by category for better organization
                categories = {"speed": [], "balanced": [], "quality": []}
                for model in all_models:
                    cat = model.get("category", "balanced")
                    if cat in categories:
                        categories[cat].append(model)
                    else:
                        categories["balanced"].append(model)

                category_labels = {
                    "speed": "── Fastest ──",
                    "balanced": "── Balanced ──",
                    "quality": "── Best Quality ──"
                }

                for cat_id in ["speed", "balanced", "quality"]:
                    cat_models = categories[cat_id]
                    if not cat_models:
                        continue

                    model_menu.add(rumps.MenuItem(category_labels[cat_id], callback=None))

                    for model in cat_models:
                        is_selected = model["id"] == current_model
                        prefix = "● " if is_selected else "   "
                        downloaded = model.get('downloaded', True)
                        recommended = model.get('recommended', False)

                        # Build label
                        label = model['name']
                        if recommended:
                            label += " (recommended)"
                        if not downloaded:
                            label += " [download]"

                        item = rumps.MenuItem(
                            f"{prefix}{label}",
                            callback=lambda sender, mid=model["id"], dl=downloaded: self._select_model_or_download(mid, dl)
                        )
                        model_menu.add(item)
            else:
                # Cloud providers - simple list with cost
                for model in all_models:
                    is_selected = model["id"] == current_model
                    prefix = "● " if is_selected else "   "
                    cost = model.get('cost_per_minute', 0)
                    cost_str = f"${cost:.3f}/min" if cost > 0 else "Free"
                    downloaded = model.get('downloaded', True)

                    if not downloaded:
                        size_mb = model.get('size_mb', 0)
                        cost_str = f"{size_mb}MB - click to download"

                    item = rumps.MenuItem(
                        f"{prefix}{model['name']} ({cost_str})",
                        callback=lambda sender, mid=model["id"], dl=downloaded: self._select_model_or_download(mid, dl)
                    )
                    model_menu.add(item)

        self.menu.add(model_menu)

        self.menu.add(rumps.separator)

        # === API Keys ===
        keys_menu = rumps.MenuItem("API Keys")

        # OpenAI
        openai_key = get_api_key("openai")
        openai_status = mask_api_key(openai_key) if openai_key else "Not set"
        keys_menu.add(rumps.MenuItem(
            f"OpenAI: {openai_status}",
            callback=self._set_openai_key
        ))

        # Gemini
        gemini_key = get_api_key("gemini")
        gemini_status = mask_api_key(gemini_key) if gemini_key else "Not set"
        keys_menu.add(rumps.MenuItem(
            f"Gemini: {gemini_status}",
            callback=self._set_gemini_key
        ))

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

        # Translation provider submenu with categories
        trans_provider_menu = rumps.MenuItem("Provider")
        trans_providers = self.translator.get_available_providers()

        # Local translation providers
        trans_provider_menu.add(rumps.MenuItem("── Local ──", callback=None))
        for tp in trans_providers:
            if tp["category"] != "local":
                continue
            is_selected = self.translator.get_current_provider() == tp["id"]
            is_available = tp["available"]
            prefix = "● " if is_selected else "   "
            status = "✓" if is_available else "○"

            trans_provider_menu.add(rumps.MenuItem(
                f"{prefix}{tp['name']} {status}",
                callback=lambda sender, pid=tp["id"]: self._set_translation_provider(pid)
            ))

        trans_provider_menu.add(rumps.separator)

        # Cloud translation providers
        trans_provider_menu.add(rumps.MenuItem("── Cloud ──", callback=None))
        for tp in trans_providers:
            if tp["category"] != "cloud":
                continue
            is_selected = self.translator.get_current_provider() == tp["id"]
            is_available = tp["available"]
            prefix = "● " if is_selected else "   "
            status = "✓" if is_available else "○"

            trans_provider_menu.add(rumps.MenuItem(
                f"{prefix}{tp['name']} {status}",
                callback=lambda sender, pid=tp["id"]: self._set_translation_provider(pid)
            ))

        translation_menu.add(trans_provider_menu)

        # Target language submenu (grouped by region)
        lang_menu = rumps.MenuItem("Target language")
        languages = self.translator.get_supported_languages()

        # Group languages for easier navigation
        common_langs = ["es", "fr", "de", "it", "pt", "zh", "ja", "ko", "ar", "ru"]
        other_langs = sorted(
            [k for k in languages.keys() if k not in common_langs],
            key=lambda x: languages[x]
        )

        # Common languages first
        lang_menu.add(rumps.MenuItem("── Common ──", callback=None))
        for code in common_langs:
            if code in languages:
                is_selected = self.config.target_language == code
                prefix = "● " if is_selected else "   "
                lang_menu.add(rumps.MenuItem(
                    f"{prefix}{languages[code]} ({code})",
                    callback=lambda sender, c=code: self._set_target_language(c)
                ))

        lang_menu.add(rumps.separator)
        lang_menu.add(rumps.MenuItem("── All Languages ──", callback=None))
        for code in other_langs:
            is_selected = self.config.target_language == code
            prefix = "● " if is_selected else "   "
            lang_menu.add(rumps.MenuItem(
                f"{prefix}{languages[code]} ({code})",
                callback=lambda sender, c=code: self._set_target_language(c)
            ))

        translation_menu.add(lang_menu)

        # Model selection submenu for current translation provider (with category grouping)
        trans_model_menu = rumps.MenuItem("Model")
        models = self.translator.get_models()
        current_trans_model = self.translator.get_current_model()

        # Group models by category
        categories = {"speed": [], "balanced": [], "quality": []}
        for model_info in models:
            cat = model_info.get("category", "balanced")
            if cat in categories:
                categories[cat].append(model_info)
            else:
                categories["balanced"].append(model_info)

        category_labels = {
            "speed": "── Fastest ──",
            "balanced": "── Balanced ──",
            "quality": "── Best Quality ──"
        }

        for cat_id in ["speed", "balanced", "quality"]:
            cat_models = categories[cat_id]
            if not cat_models:
                continue

            trans_model_menu.add(rumps.MenuItem(category_labels[cat_id], callback=None))

            for model_info in cat_models:
                is_selected = current_trans_model == model_info["id"]
                prefix = "● " if is_selected else "   "
                suffix = " (recommended)" if model_info.get("recommended") else ""

                trans_model_menu.add(rumps.MenuItem(
                    f"{prefix}{model_info['name']}{suffix}",
                    callback=lambda sender, mid=model_info["id"]: self._set_translation_model(mid)
                ))

        translation_menu.add(trans_model_menu)

        translation_menu.add(rumps.separator)

        # Ollama-specific options (only show if Ollama is selected)
        if self.translator.get_current_provider() == "ollama":
            status = self.translator.get_status()
            if not status.get("ollama_installed", False):
                translation_menu.add(rumps.MenuItem(
                    "Install Ollama...",
                    callback=self._install_ollama
                ))
            elif not status.get("ollama_running", False):
                translation_menu.add(rumps.MenuItem(
                    "Start Ollama",
                    callback=self._start_ollama
                ))
            elif not status.get("downloaded", False):
                translation_menu.add(rumps.MenuItem(
                    f"Download model ({status.get('size_gb', 0)}GB)...",
                    callback=self._download_translation_model
                ))
            else:
                translation_menu.add(rumps.MenuItem(
                    f"✓ Model ready ({status.get('size_gb', 0)}GB)",
                    callback=None
                ))

            translation_menu.add(rumps.separator)

            # Auto-start Ollama toggle
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
        configured_providers = get_configured_providers()
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
            api_keys_menu.add(rumps.MenuItem("No API keys configured", callback=None))
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
        self.menu.add(rumps.MenuItem(f"About WhisperHUD v{__version__}", callback=self._show_about))

        # === Check for Updates ===
        self.menu.add(rumps.MenuItem("Check for Updates...", callback=self._check_for_updates))

        self.menu.add(rumps.separator)

        # === Quit ===
        self.menu.add(rumps.MenuItem("Quit WhisperHUD", callback=self._quit))

        # Update menu bar icon to reflect target lock status
        if not self._is_recording and not self._is_downloading:
            self._set_title(self._get_idle_icon())

    def _get_provider_display_name(self, provider_id: str) -> str:
        """Get display name for a provider."""
        names = {
            "openai": "OpenAI",
            "gemini": "Gemini",
            "apple": "Apple",
            "whisper_local": "Whisper",
            "parakeet": "Parakeet",
        }
        return names.get(provider_id, provider_id.title())

    def _select_or_download_provider(self, provider_id: str, provider_info: dict):
        """Select a provider, or prompt for download if needed."""
        # If provider isn't available due to missing deps or OS constraints, show guidance
        if not provider_info.get("configured", False):
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
        self._build_menu()

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
                self._build_menu()

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

    def _start_recording(self):
        """Called when hotkey is pressed."""
        # Use dedicated recording lock to prevent race conditions
        # when rapidly toggling or clicking widget while hotkey is held
        with self._recording_lock:
            with self._lock:
                if self._is_recording:
                    return
                self._is_recording = True

            self._set_title(self.ICON_RECORDING)

            if self.config.show_hud:
                self.hud.show_recording()

            if self.widget:
                self.widget.set_recording()

            # Configure silence detection
            try:
                if self.config.auto_stop:
                    self.recorder.set_silence_settings(
                        enabled=True,
                        silence_duration=self.config.silence_duration
                    )
                    self.recorder.start(on_silence=self._on_silence_detected)
                else:
                    self.recorder.start()
            except Exception as e:
                logger.error(f"Failed to start recording: {e}")
                with self._lock:
                    self._is_recording = False
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

            # Start audio level monitoring for HUD
            if self.config.show_hud:
                self._start_level_monitor()

    def _start_level_monitor(self):
        """Start monitoring audio levels for HUD display."""
        def monitor_levels():
            while self._is_recording:
                level = self.recorder.get_audio_level()
                self.hud.update_audio_level(level)
                time.sleep(0.05)  # ~20 updates per second

        self._level_monitor_thread = threading.Thread(target=monitor_levels, daemon=True)
        self._level_monitor_thread.start()

    def _on_silence_detected(self):
        """Called when silence is detected after speech."""
        # Auto-stop recording
        self._stop_recording()

    def _stop_recording(self):
        """Called when hotkey is released."""
        # Use dedicated recording lock to prevent race conditions
        # when rapidly toggling or clicking widget while hotkey is held
        with self._recording_lock:
            with self._lock:
                if not self._is_recording:
                    return
                self._is_recording = False

            self._set_title(self.ICON_PROCESSING)

            if self.config.show_hud:
                self.hud.show_processing()

            if self.widget:
                self.widget.set_processing()

            # Get audio data
            audio_bytes = self.recorder.stop()

        if not audio_bytes or len(audio_bytes) < 1000:  # Too short
            self.hud.hide()
            self._set_title(self._get_idle_icon())
            if self.widget:
                self.widget.set_idle()
            return

        # Transcribe in background thread
        def do_transcribe():
            try:
                # Check if streaming is enabled
                use_streaming = self.config.streaming_enabled

                if use_streaming:
                    # Show streaming panel
                    self.streaming_panel.show_transcribing(
                        show_translation=self.config.translation_enabled
                    )

                    # Transcribe with streaming
                    result = self.transcriber.transcribe_streaming(
                        audio_bytes,
                        on_chunk=self.streaming_panel.update_transcription
                    )
                else:
                    # Regular non-streaming transcription
                    result = self.transcriber.transcribe(audio_bytes)

                if result.text:
                    final_text = result.text
                    did_translate = False

                    # Translate if enabled
                    if self.config.translation_enabled:
                        try:
                            if self.config.show_hud:
                                self.hud.show_processing("Translating...")

                            if use_streaming:
                                self.streaming_panel.show_translating()

                            # Check if translation provider supports streaming
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

                            # Get target language name for display
                            lang_name = self.translator.get_supported_languages().get(
                                self.config.target_language,
                                self.config.target_language
                            )
                            word_count = len(final_text.split())
                            self._set_title(self.ICON_SUCCESS)

                            if self.config.show_hud:
                                self.hud.show_success(f"✓ {word_count} words → {lang_name}")

                        except Exception as e:
                            # Translation failed, use original text
                            logger.warning(f"Translation failed: {e}")
                            final_text = result.text
                            word_count = len(final_text.split())
                            self._set_title(self.ICON_SUCCESS)
                            if self.config.show_hud:
                                self.hud.show_success(f"✓ {word_count} words (translation failed)")
                    else:
                        # No translation, just show word count
                        word_count = len(final_text.split())
                        self._set_title(self.ICON_SUCCESS)
                        if self.config.show_hud:
                            self.hud.show_success(f"✓ {word_count} words")

                    # Play completion sound if enabled
                    self._play_completion_sound()

                    # Show completion on streaming panel
                    if use_streaming:
                        self.streaming_panel.show_complete()

                    # Save to history
                    self.config.add_to_history(
                        text=final_text,
                        provider=result.provider,
                        translated=did_translate,
                        original_text=result.text if did_translate else ""
                    )

                    # Auto-paste if enabled
                    if self.config.auto_paste:
                        time.sleep(0.1)  # Brief delay
                        self._paste_to_target(final_text)
                else:
                    self._set_title(self.ICON_ERROR)
                    if self.config.show_hud:
                        self.hud.show_error("No speech detected")
                    if use_streaming:
                        self.streaming_panel.hide()

            except ValueError as e:
                # Configuration error (no API key)
                self._set_title(self.ICON_ERROR)
                error_msg = str(e).lower()
                if "api key" in error_msg or "not configured" in error_msg:
                    display_error = "API key required"
                else:
                    display_error = str(e)[:25]
                if self.config.show_hud:
                    self.hud.show_error(display_error)
                if self.config.streaming_enabled:
                    self.streaming_panel.hide()
                # Show notification with action
                self._notify(
                    "WhisperHUD",
                    "Configuration Required",
                    "Click the menu bar icon to add your API key."
                )

            except Exception as e:
                error_str = str(e).lower()
                logger.error(f"Transcription error: {e}")
                self._set_title(self.ICON_ERROR)

                # Provide specific, helpful error messages
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
                else:
                    display_error = "Transcription failed"
                    detail = str(e)[:50]

                if self.config.show_hud:
                    self.hud.show_error(display_error)
                if self.config.streaming_enabled:
                    self.streaming_panel.hide()

                # Show detailed notification
                self._notify(
                    "WhisperHUD",
                    display_error,
                    detail
                )

            finally:
                # Reset icon after a brief delay
                time.sleep(1.5)
                self._set_title(self._get_idle_icon())
                if self.widget:
                    self.widget.set_idle()
                self._build_menu()  # Refresh menu to update stats

        threading.Thread(target=do_transcribe, daemon=True).start()

    def _select_provider(self, provider_id: str):
        """Change default provider."""
        self.config.default_provider = provider_id
        self.config.save()
        self._build_menu()

    def _select_model(self, model_id: str):
        """Change model for current provider."""
        self.transcriber.set_provider_model(
            self.config.default_provider,
            model_id
        )
        self._build_menu()

    def _set_openai_key(self, _):
        """Prompt for OpenAI API key using AppleScript for proper paste support."""
        current = get_api_key("openai") or ""
        key = self._applescript_input_dialog(
            "OpenAI API Key",
            "Enter your OpenAI API key.\n\nGet your key at: platform.openai.com/api-keys",
            current
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
                    set_api_key("openai", key)
                    # Reset cached clients so new key is used immediately
                    self.transcriber.reset_provider("openai")
                    self.translator.reset_provider("openai")
                    self._build_menu()
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
        current = get_api_key("gemini") or ""
        key = self._applescript_input_dialog(
            "Gemini API Key",
            "Enter your Google AI API key.\n\nGet your key at: aistudio.google.com/apikey",
            current
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
                    set_api_key("gemini", key)
                    # Reset cached clients so new key is used immediately
                    self.transcriber.reset_provider("gemini")
                    self.translator.reset_provider("gemini")
                    self._build_menu()
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

    def _applescript_input_dialog(self, title: str, message: str, default: str = "") -> Optional[str]:
        """Show an AppleScript input dialog that supports copy-paste."""
        import subprocess

        # Escape quotes for AppleScript
        message_escaped = message.replace('"', '\\"').replace('\n', '\\n')
        default_escaped = default.replace('"', '\\"')
        title_escaped = title.replace('"', '\\"')

        script = f'''
        tell application "System Events"
            activate
            set userInput to display dialog "{message_escaped}" default answer "{default_escaped}" with title "{title_escaped}" buttons {{"Cancel", "Save"}} default button "Save"
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
        self._build_menu()

    def _set_widget_size(self, size: str):
        """Change widget size."""
        self.config.widget_size = size
        self.config.save()
        if self.widget:
            self.widget.set_size(size)
        self._build_menu()

    def _toggle_hud(self, sender):
        """Toggle HUD visibility setting."""
        self.config.show_hud = not self.config.show_hud
        self.config.save()
        self.hud.set_enabled(self.config.show_hud)
        self._build_menu()

    def _toggle_auto_stop(self, sender):
        """Toggle auto-stop on silence setting."""
        self.config.auto_stop = not self.config.auto_stop
        self.config.save()
        self._build_menu()

    def _toggle_auto_paste(self, sender):
        """Toggle auto-paste setting."""
        self.config.auto_paste = not self.config.auto_paste
        self.config.save()
        self._build_menu()

    def _toggle_restore_clipboard(self, sender):
        """Toggle clipboard restoration setting."""
        self.config.restore_clipboard = not self.config.restore_clipboard
        self.config.save()
        self._build_menu()

    def _toggle_play_sound(self, sender):
        """Toggle completion sound setting."""
        self.config.play_sound = not self.config.play_sound
        self.config.save()
        self._build_menu()

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
        self._build_menu()

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
                self._build_menu()
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
                self._build_menu()

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
                    "Your existing encrypted history will still be readable "
                    "(the key stays in your Mac's Keychain)."
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
            # Enabling encryption - should already be installed if we get here
            success = self.config.enable_history_encryption()
            if success:
                self._notify(
                    "WhisperHUD",
                    "🔐 Encryption On",
                    "Your transcription history is now encrypted."
                )
            else:
                # Shouldn't happen, but handle gracefully
                self._setup_encryption(sender)
                return

        self._build_menu()

    def _setup_encryption(self, sender):
        """Set up encryption - installs cryptography if needed."""
        from .encryption import is_cryptography_installed

        if is_cryptography_installed():
            # Already installed, just enable
            self._toggle_history_encryption(sender)
            return

        # Explain and offer to install
        response = rumps.alert(
            title="Set Up Encryption",
            message=(
                "Encryption protects your saved transcriptions so only you "
                "can read them—even if someone accesses your files.\n\n"
                "A small download (~2MB) is needed for the first-time setup.\n\n"
                "Your encryption key will be stored securely in your "
                "Mac's Keychain."
            ),
            ok="Set Up Now",
            cancel="Not Now"
        )

        if response != 1:
            return

        # Start installation
        self._install_cryptography()

    def _install_cryptography(self):
        """Install cryptography package in the background."""
        import sys
        import subprocess

        self._notify(
            "WhisperHUD",
            "Setting Up Encryption",
            "Installing... this takes a moment."
        )

        def do_install():
            try:
                # Use the same Python that's running this app
                python_path = sys.executable

                # Install cryptography
                result = subprocess.run(
                    [python_path, "-m", "pip", "install", "cryptography>=41.0.0"],
                    capture_output=True,
                    text=True,
                    timeout=120
                )

                if result.returncode == 0:
                    # Verify it installed correctly
                    verify = subprocess.run(
                        [python_path, "-c", "import cryptography; print('ok')"],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )

                    if verify.returncode == 0 and "ok" in verify.stdout:
                        # Force reimport of cryptography in this process
                        import importlib
                        try:
                            import cryptography
                            importlib.reload(cryptography)
                        except ImportError:
                            # First import after install
                            pass

                        # Reimport our encryption module to pick up cryptography
                        from . import encryption
                        importlib.reload(encryption)

                        # Now enable encryption
                        success = self.config.enable_history_encryption()
                        if success:
                            self._notify(
                                "WhisperHUD",
                                "🔐 Encryption Ready",
                                "Your transcription history is now encrypted."
                            )
                            self._build_menu()
                            return

                # Installation failed
                logger.error(f"Cryptography install failed: {result.stderr}")
                self._show_manual_install_help(result.stderr)

            except subprocess.TimeoutExpired:
                self._show_manual_install_help("Installation timed out. Please try again.")
            except Exception as e:
                logger.error(f"Cryptography install error: {e}")
                self._show_manual_install_help(str(e))

        threading.Thread(target=do_install, daemon=True).start()

    def _show_manual_install_help(self, error_detail: str = ""):
        """Show manual installation instructions when auto-install fails."""
        # Run on main thread for UI
        def show_alert():
            detail = ""
            if error_detail and len(error_detail) < 200:
                detail = f"\n\nError: {error_detail}"

            rumps.alert(
                title="Setup Needs Your Help",
                message=(
                    "Automatic setup didn't work. You can set up encryption "
                    "manually:\n\n"
                    "1. Open Terminal\n"
                    "2. Run: pip install cryptography\n"
                    "3. Restart WhisperHUD\n\n"
                    "Then encryption will be available in the Privacy menu."
                    f"{detail}"
                )
            )

        try:
            from PyObjCTools import AppHelper
            AppHelper.callAfter(show_alert)
        except Exception:
            show_alert()

    def _toggle_notifications(self, sender):
        """Toggle system notifications."""
        self.config.show_notifications = not self.config.show_notifications
        self.config.save()
        self._build_menu()

    def _set_audio_device(self, device_id):
        """Set the audio input device."""
        self.config.audio_input_device = device_id
        self.config.save()
        # Update the recorder
        self.recorder.set_device(device_id)
        self._build_menu()

        # Get device name for notification
        if device_id is None:
            device_name = "System Default"
        else:
            from .recorder import get_input_devices
            devices = get_input_devices()
            device_name = next(
                (d['name'] for d in devices if d['id'] == device_id),
                f"Device {device_id}"
            )
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
            self._build_menu()
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
                        # Preserve history and stats
                        imported_config.history = self.config.history
                        imported_config.total_transcriptions = self.config.total_transcriptions
                        imported_config.total_cost = self.config.total_cost

                        self.config.update_from(imported_config)
                        self.config.save()

                        # Reload components
                        self.transcriber.reload_config()
                        self.translator.reload_config()
                        self.recorder.set_device(self.config.audio_input_device)
                        self._restart_hotkey_listener()
                        self._apply_appearance_to_components()
                        self._build_menu()

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
        from . import __version__
        import platform

        response = rumps.alert(
            title="About WhisperHUD",
            message=(
                f"Version {__version__}\n\n"
                f"Voice-to-text transcription for macOS\n\n"
                f"System: macOS {platform.mac_ver()[0]}\n"
                f"Python: {platform.python_version()}\n\n"
                "github.com/jacobvogan/whisper-hud"
            ),
            ok="OK",
            other="Open GitHub"
        )

        if response == 0:  # "Open GitHub" clicked
            import subprocess
            subprocess.run(
                ["open", "https://github.com/jacobvogan/whisper-hud"],
                capture_output=True
            )

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
                ["open", "https://github.com/jacobvogan/whisper-hud/releases"],
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
        self._build_menu()

    def _toggle_paste_return_focus(self, sender):
        """Toggle return focus after paste setting."""
        self.config.paste_target_return_focus = not self.config.paste_target_return_focus
        self.config.save()
        self._build_menu()

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

        self._build_menu()

    def _refresh_paste_targets_cache(self):
        """Refresh cached paste target data (called on init and manual refresh)."""
        self._cached_tmux_sessions = self.paste_target_manager.get_tmux_sessions()
        self._cached_iterm2_running = self.paste_target_manager.is_iterm2_running()
        self._cached_terminal_running = self.paste_target_manager.is_terminal_running()
        self._cached_running_apps = self.paste_target_manager.get_running_apps()

    def _refresh_paste_targets(self, sender):
        """Refresh available paste targets (rescans running apps/sessions)."""
        self._refresh_paste_targets_cache()
        self._build_menu()

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

            self._build_menu()
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

        self._build_menu()

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

        self._build_menu()

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
            self._build_menu()
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
            self._build_menu()
            self._notify(
                "WhisperHUD",
                "Statistics Reset",
                "Transcription statistics have been reset."
            )

    def _clear_image_cache(self, sender):
        """Clear the image cache."""
        from .image_processor import clear_cache
        clear_cache()
        self._build_menu()
        self._notify(
            "WhisperHUD",
            "Cache Cleared",
            "Image cache has been cleared."
        )

    def _delete_api_key(self, provider: str):
        """Delete a specific API key."""
        from .keychain import delete_api_key
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
            delete_api_key(provider)
            # Reset the provider to clear cached client
            self.transcriber.reset_provider(provider)
            self._build_menu()
            self._notify(
                "WhisperHUD",
                "API Key Deleted",
                f"{provider_name} API key has been removed."
            )

    def _delete_all_api_keys(self, sender):
        """Delete all API keys."""
        from .keychain import delete_api_key, get_configured_providers
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
                self.transcriber.reset_provider(provider)
            self._build_menu()
            self._notify(
                "WhisperHUD",
                "API Keys Deleted",
                "All API keys have been removed."
            )

    def _reset_all_settings(self, sender):
        """Reset all settings to defaults."""
        from .keychain import get_configured_providers
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
            # Note: API keys are preserved (not deleted)
            _ = get_configured_providers()  # Verify keychain access works

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
            self._build_menu()
            self._apply_appearance_to_components()

            self._notify(
                "WhisperHUD",
                "Settings Reset",
                "All settings have been reset to defaults."
            )

    def _toggle_translation(self, sender):
        """Toggle translation on/off."""
        # Check if translation is available before enabling
        if not self.config.translation_enabled:
            if not self.translator.is_available():
                provider_name = self.translator.provider.display_name
                rumps.alert(
                    title="Translation Not Available",
                    message=(
                        f"Translation provider '{provider_name}' is not available.\n\n"
                        f"Please configure the provider or select a different one."
                    )
                )
                return

        self.config.translation_enabled = not self.config.translation_enabled
        self.config.save()
        self._build_menu()

    def _set_translation_provider(self, provider_id: str):
        """Set the translation provider."""
        self.translator.set_provider(provider_id)
        self._build_menu()

    def _set_target_language(self, lang_code: str):
        """Set the target translation language."""
        self.config.target_language = lang_code
        self.config.save()
        self._build_menu()

    def _set_translation_model(self, model_id: str):
        """Set the translation model."""
        self.translator.set_model(model_id)
        self._build_menu()

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
            self._build_menu()

        threading.Thread(target=do_download, daemon=True).start()

    def _toggle_streaming(self, sender):
        """Toggle streaming display on/off."""
        self.config.streaming_enabled = not self.config.streaming_enabled
        self.config.save()
        self.streaming_panel.set_enabled(self.config.streaming_enabled)
        self._build_menu()

    def _toggle_ollama_auto_start(self, sender):
        """Toggle Ollama auto-start setting."""
        self.config.ollama_auto_start = not self.config.ollama_auto_start
        self.config.save()
        self._build_menu()

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

            self._build_menu()

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

            self._build_menu()

        threading.Thread(target=do_start, daemon=True).start()

    def _auto_start_ollama(self):
        """Auto-start Ollama if installed but not running."""
        status = self.translator.get_status()
        if status.get("ollama_installed", False) and not status.get("ollama_running", False):
            def do_start():
                success, pid = self.translator.start_ollama_server()
                if success:
                    logger.info("Ollama auto-started successfully")
                    self._build_menu()

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
            self._build_menu()
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
        if self.widget:
            self.widget.set_recording()

    def _widget_stop_recording(self):
        """Called when widget is clicked to stop recording."""
        self._stop_recording()

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
        self._build_menu()

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
            self._build_menu()

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
        self._build_menu()

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
            self._build_menu()
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
        self._build_menu()
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
            self._build_menu()

    def _show_setup_reminder(self):
        """Show reminder to set up API keys."""
        self._notify(
            "WhisperHUD",
            "Welcome!",
            "Click the menu bar icon to add your API key and start transcribing."
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
        self.hotkey_listener.stop()
        self.hud.hide()
        self.streaming_panel.hide()
        if self.widget:
            self.widget.hide()
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
