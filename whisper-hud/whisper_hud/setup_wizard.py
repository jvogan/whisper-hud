"""
Setup wizard for WhisperHUD.

A multi-step wizard using PyObjC/AppKit that guides users through:
1. Welcome - Overview and what you'll set up
2. Transcription Mode - Choose between Cloud or Local transcription
3. Cloud Setup (if cloud selected) - Choose provider, enter API key
4. Local Setup (if local selected) - Download model
5. Translation Setup (Optional) - Configure translation provider
6. Complete - Summary and usage tips
"""

import threading
import platform
from typing import Callable, Optional
from enum import Enum

from .logging_config import get_logger

logger = get_logger("setup_wizard")

try:
    from AppKit import (
        NSWindow, NSView, NSColor, NSFont,
        NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
        NSBackingStoreBuffered, NSScreen, NSTextField,
        NSMakeRect, NSButton, NSApplication,
        NSSecureTextField, NSProgressIndicator,
        NSProgressIndicatorSpinningStyle, NSPopUpButton,
        NSLeftTextAlignment, NSAppearance, NSAppearanceNameAqua,
        NSAppearanceNameDarkAqua
    )
    from Foundation import (
        NSAttributedString,
        NSMutableParagraphStyle,
        NSFontAttributeName,
        NSForegroundColorAttributeName,
        NSParagraphStyleAttributeName,
    )
    from PyObjCTools import AppHelper
    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False


class WizardStep(Enum):
    WELCOME = 0
    TRANSCRIPTION_MODE = 1
    CLOUD_SETUP = 2
    LOCAL_SETUP = 3
    TRANSLATION = 4
    COMPLETE = 5


class SetupWizard:
    """
    Multi-step setup wizard for WhisperHUD.

    Guides users through API key setup, local model selection,
    and optional translation configuration.
    """

    WIDTH = 560
    HEIGHT = 480
    PADDING = 24

    def __init__(
        self,
        on_complete: Optional[Callable[[dict], None]] = None,
        on_cancel: Optional[Callable[[], None]] = None
    ):
        """
        Initialize the setup wizard.

        Args:
            on_complete: Called when wizard finishes with config dict
            on_cancel: Called when wizard is cancelled
        """
        self._on_complete = on_complete
        self._on_cancel = on_cancel
        self._window: Optional[NSWindow] = None
        self._current_step = WizardStep.WELCOME
        self._content_view: Optional[NSView] = None

        # Collected data
        # Default to easiest no-account path for first-time users.
        self._transcription_mode = "local"  # "cloud" or "local"
        self._selected_provider = "apple"  # Cloud: gemini/openai/openai_realtime, Local: apple/whisper_local/parakeet
        self._api_key = ""
        self._translation_enabled = False
        self._translation_provider = "apple"
        self._translation_target_language = "en"
        self._translation_source_language = "auto"
        self._translation_models = {
            "apple": "system",
            "ollama": "translategemma-4b",
            "gemini": "gemini-3-flash-preview",
            "openai": "gpt-5-mini",
            "anthropic": "claude-sonnet-4-5",
        }
        self._ollama_installed = False
        self._ollama_running = False
        self._model_downloaded = False

        # UI elements to track
        self._provider_buttons = {}
        self._mode_buttons = {}
        self._api_key_field = None
        self._api_key_status_icon = None
        self._api_key_status_label = None
        self._api_key_spinner = None
        self._skip_validation_button = None
        self._next_button = None
        self._progress_indicator = None
        self._status_label = None
        self._translation_provider_popup = None
        self._translation_model_popup = None
        self._translation_target_popup = None
        self._translation_source_popup = None
        self._translation_enable_popup = None
        self._translation_provider_choices = []
        self._translation_model_choices = []
        self._translation_target_choices = []
        self._translation_source_choices = []
        self._api_key_validation_status = "idle"
        self._api_key_validation_message = "Enter an API key to continue"
        self._api_key_validation_acknowledged = False
        self._api_key_validation_key = ""
        self._api_key_validation_provider = ""
        self._api_key_validation_timer = None
        self._api_key_validation_request_id = 0
        self._api_key_validation_lock = threading.Lock()

        # Prefill from current config when rerunning setup.
        try:
            from .config import Config

            existing = Config.load()
            self._translation_enabled = bool(existing.translation_enabled)
            self._translation_provider = getattr(existing, "translation_provider", "apple")
            self._translation_target_language = getattr(existing, "target_language", "en")
            self._translation_source_language = getattr(existing, "source_language", "auto")
            self._translation_models["ollama"] = getattr(existing, "translation_model", self._translation_models["ollama"])
            self._translation_models["gemini"] = getattr(
                existing,
                "gemini_translate_model",
                self._translation_models["gemini"],
            )
            self._translation_models["openai"] = getattr(
                existing,
                "openai_translate_model",
                self._translation_models["openai"],
            )
            self._translation_models["anthropic"] = getattr(
                existing,
                "anthropic_translate_model",
                self._translation_models["anthropic"],
            )
        except Exception:
            pass

    def show(self):
        """Show the setup wizard."""
        if not HAS_APPKIT:
            logger.warning("AppKit not available, using console mode")
            self._console_wizard()
            return

        def _show():
            self._create_window()
            self._show_step(WizardStep.WELCOME)
            self._window.makeKeyAndOrderFront_(None)
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

        AppHelper.callAfter(_show)

    def _create_window(self):
        """Create the wizard window."""
        # Center on screen
        screen = NSScreen.mainScreen()
        if screen:
            screen_rect = screen.visibleFrame()
            x = screen_rect.origin.x + (screen_rect.size.width - self.WIDTH) / 2
            y = screen_rect.origin.y + (screen_rect.size.height - self.HEIGHT) / 2
        else:
            x, y = 100, 100

        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, self.WIDTH, self.HEIGHT),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False
        )

        self._window.setTitle_("WhisperHUD Setup")
        self._content_view = self._window.contentView()
        self._refresh_appearance()

    def _clear_content(self):
        """Clear all subviews from content view."""
        self._cancel_api_key_validation_timer()
        if self._api_key_field:
            try:
                self._api_key_field.setDelegate_(None)
            except Exception:
                pass
        self._api_key_field = None
        self._api_key_status_icon = None
        self._api_key_status_label = None
        self._api_key_spinner = None
        self._skip_validation_button = None
        self._next_button = None
        if self._content_view:
            for subview in list(self._content_view.subviews()):
                subview.removeFromSuperview()

    def _show_step(self, step: WizardStep):
        """Show a specific wizard step."""
        self._current_step = step
        self._clear_content()
        self._refresh_appearance()
        self._add_step_progress(step)

        if step == WizardStep.WELCOME:
            self._show_welcome()
        elif step == WizardStep.TRANSCRIPTION_MODE:
            self._show_transcription_mode()
        elif step == WizardStep.CLOUD_SETUP:
            self._show_cloud_setup()
        elif step == WizardStep.LOCAL_SETUP:
            self._show_local_setup()
        elif step == WizardStep.TRANSLATION:
            self._show_translation()
        elif step == WizardStep.COMPLETE:
            self._show_complete()

    def _show_welcome(self):
        """Show welcome step."""
        y = self.HEIGHT - self.PADDING

        # Title
        y -= 40
        title = self._create_label(
            "Welcome to WhisperHUD",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 36),
            font_size=24,
            bold=True
        )
        self._content_view.addSubview_(title)

        # Description
        y -= 120
        desc = self._create_label(
            "WhisperHUD lets you transcribe speech to text using your voice.\n\n"
            "This setup wizard will help you:\n"
            "  1. Choose a transcription mode (Cloud or Local)\n"
            "  2. Configure your preferred provider\n"
            "  3. Optionally set up translation\n\n"
            "Tip: Local (Apple) is the fastest way to start and needs no API key.",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 120),
            font_size=14,
            align=NSLeftTextAlignment
        )
        self._content_view.addSubview_(desc)

        # Quick info
        y -= 80
        info = self._create_label(
            "Cloud: Fast, accurate, requires API key + internet\n"
            "Local: Private, works offline. Apple mode needs no download.",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 60),
            font_size=12,
            color=self._accent_text_color()
        )
        self._content_view.addSubview_(info)

        # Navigation buttons
        self._add_navigation_buttons(
            back_title=None,
            next_title="Get Started",
            next_action=lambda: self._show_step(WizardStep.TRANSCRIPTION_MODE)
        )

    def _show_transcription_mode(self):
        """Show transcription mode selection step."""
        y = self.HEIGHT - self.PADDING

        # Title
        y -= 36
        title = self._create_label(
            "Choose Transcription Mode",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 32),
            font_size=22,
            bold=True
        )
        self._content_view.addSubview_(title)

        # Description
        y -= 30
        desc = self._create_label(
            "How would you like to transcribe your speech? (You can change this anytime.)",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 24),
            font_size=14
        )
        self._content_view.addSubview_(desc)

        # Mode buttons - larger card-style
        y -= 130
        btn_width = (self.WIDTH - 2 * self.PADDING - 20) / 2
        btn_height = 120

        # Cloud mode button
        cloud_btn = self._create_mode_card(
            "Cloud",
            "Fast & Accurate",
            "Uses API (OpenAI or Gemini)\nRequires internet connection\nPay per use or free tier",
            NSMakeRect(self.PADDING, y, btn_width, btn_height),
            selected=self._transcription_mode == "cloud",
            action=lambda: self._select_mode("cloud")
        )
        self._content_view.addSubview_(cloud_btn)
        self._mode_buttons["cloud"] = cloud_btn

        # Local mode button
        local_btn = self._create_mode_card(
            "Local",
            "Private & Easiest",
            "Runs on your Mac\nNo API key needed for Apple\nOptional model download later",
            NSMakeRect(self.PADDING + btn_width + 20, y, btn_width, btn_height),
            selected=self._transcription_mode == "local",
            action=lambda: self._select_mode("local")
        )
        self._content_view.addSubview_(local_btn)
        self._mode_buttons["local"] = local_btn

        # Additional info
        y -= 60
        info = self._create_label(
            "You can change this later in the app settings.",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 24),
            font_size=12,
            color=self._secondary_text_color()
        )
        self._content_view.addSubview_(info)

        # Navigation
        self._add_navigation_buttons(
            back_title="Back",
            back_action=lambda: self._show_step(WizardStep.WELCOME),
            next_title="Next",
            next_action=self._continue_from_mode_selection
        )

    def _show_cloud_setup(self):
        """Show cloud provider setup step."""
        y = self.HEIGHT - self.PADDING

        # Title
        y -= 36
        title = self._create_label(
            "Cloud Transcription Setup",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 32),
            font_size=22,
            bold=True
        )
        self._content_view.addSubview_(title)

        # Provider selection
        y -= 30
        provider_label = self._create_label(
            "Choose your cloud provider:",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 24),
            font_size=14
        )
        self._content_view.addSubview_(provider_label)

        # Provider buttons
        y -= 44
        provider_specs = [
            ("gemini", "Gemini", "Free tier available"),
            ("openai", "OpenAI", "Batch upload transcription"),
            ("openai_realtime", "OpenAI Realtime", "Low-latency live dictation"),
        ]

        for provider_id, title_text, subtitle in provider_specs:
            button = self._create_provider_button(
                title_text,
                subtitle,
                NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 40),
                selected=self._selected_provider == provider_id,
                action=lambda pid=provider_id: self._select_provider(pid)
            )
            self._content_view.addSubview_(button)
            self._provider_buttons[provider_id] = button
            y -= 48

        # API key input
        y -= 8
        key_label = self._create_label(
            "Enter your API key:",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 24),
            font_size=14
        )
        self._content_view.addSubview_(key_label)

        y -= 30
        self._api_key_field = NSSecureTextField.alloc().initWithFrame_(
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 28)
        )
        self._api_key_field.setPlaceholderString_("Paste your API key here...")
        self._api_key_field.setFont_(NSFont.systemFontOfSize_(14))
        self._api_key_field.setStringValue_(self._api_key)
        self._api_key_field.setDelegate_(self)
        self._content_view.addSubview_(self._api_key_field)

        y -= 34
        self._api_key_spinner = NSProgressIndicator.alloc().initWithFrame_(
            NSMakeRect(self.PADDING, y, 16, 16)
        )
        self._api_key_spinner.setStyle_(NSProgressIndicatorSpinningStyle)
        self._api_key_spinner.setIndeterminate_(True)
        self._api_key_spinner.setDisplayedWhenStopped_(False)
        self._api_key_spinner.setHidden_(True)
        self._content_view.addSubview_(self._api_key_spinner)

        self._api_key_status_icon = self._create_label(
            "",
            NSMakeRect(self.PADDING + 20, y - 2, 18, 20),
            font_size=14,
            bold=True
        )
        self._content_view.addSubview_(self._api_key_status_icon)

        self._api_key_status_label = self._create_label(
            self._api_key_validation_message,
            NSMakeRect(self.PADDING + 44, y - 2, self.WIDTH - 2 * self.PADDING - 140, 20),
            font_size=12
        )
        self._content_view.addSubview_(self._api_key_status_label)

        self._skip_validation_button = self._create_button(
            "Skip Validation",
            NSMakeRect(self.WIDTH - self.PADDING - 116, y - 6, 116, 24),
            action=self._skip_api_key_validation
        )
        self._content_view.addSubview_(self._skip_validation_button)

        # Help text with links
        y -= 62
        help_text = self._create_label(
            "Get your API key:\n"
            "  Gemini: aistudio.google.com/apikey (free tier!)\n"
            "  OpenAI + OpenAI Realtime: platform.openai.com/api-keys",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 50),
            font_size=12,
            color=self._accent_text_color()
        )
        self._content_view.addSubview_(help_text)

        # Security note
        y -= 30
        from .keychain import get_storage_mode
        storage_mode = get_storage_mode()
        if storage_mode == "passphrase":
            security_text = "API keys use encrypted local storage (default)."
        elif storage_mode == "keychain":
            security_text = "API keys are saved in macOS Keychain."
        else:
            security_text = "Session-only mode: API keys clear on quit."
        security = self._create_label(
            security_text,
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 24),
            font_size=11,
            color=self._muted_text_color()
        )
        self._content_view.addSubview_(security)

        # Navigation
        self._add_navigation_buttons(
            back_title="Back",
            back_action=lambda: self._show_step(WizardStep.TRANSCRIPTION_MODE),
            next_title="Next",
            next_action=self._validate_and_continue_cloud,
            next_enabled=False
        )
        self._handle_api_key_input_changed()

    def _show_local_setup(self):
        """Show local transcription setup step."""
        y = self.HEIGHT - self.PADDING

        # Title
        y -= 36
        title = self._create_label(
            "Local Transcription Setup",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 32),
            font_size=22,
            bold=True
        )
        self._content_view.addSubview_(title)

        # Description
        y -= 50
        desc = self._create_label(
            "Choose a local transcription engine:\n"
            "All processing happens on your Mac - no data sent to cloud.",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 40),
            font_size=14
        )
        self._content_view.addSubview_(desc)

        # Check Apple Silicon
        is_apple_silicon = platform.machine() == "arm64"

        # Local provider options
        y -= 30
        providers = []

        # Apple Speech (always available on macOS 12+)
        providers.append({
            "id": "apple",
            "name": "Apple (Built-in)",
            "desc": "No download needed, uses macOS Speech",
            "size": "0MB",
            "available": True
        })

        # Whisper Local
        providers.append({
            "id": "whisper_local",
            "name": "Whisper Local",
            "desc": "Best accuracy, 99+ languages",
            "size": "~800MB download",
            "available": True
        })

        # Parakeet (Apple Silicon only)
        if is_apple_silicon:
            providers.append({
                "id": "parakeet",
                "name": "Parakeet (Fastest)",
                "desc": "30x faster on Apple Silicon",
                "size": "~600MB download",
                "available": True
            })

        # Create provider option buttons
        for prov in providers:
            y -= 55
            is_selected = self._selected_provider == prov["id"]
            btn = self._create_local_provider_option(
                prov["name"],
                f"{prov['desc']} ({prov['size']})",
                NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 50),
                selected=is_selected,
                action=lambda pid=prov["id"]: self._select_provider(pid)
            )
            self._content_view.addSubview_(btn)
            self._provider_buttons[prov["id"]] = btn

        # Note about downloads
        y -= 40
        note = self._create_label(
            "Apple Speech requires no download. Whisper and Parakeet will\n"
            "download their models when you first use them.",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 40),
            font_size=11,
            color=self._muted_text_color()
        )
        self._content_view.addSubview_(note)

        # Navigation
        self._add_navigation_buttons(
            back_title="Back",
            back_action=lambda: self._show_step(WizardStep.TRANSCRIPTION_MODE),
            next_title="Next",
            next_action=lambda: self._continue_from_local_setup()
        )

    def _show_translation(self):
        """Show translation setup step with full first-run configuration."""
        from .providers.translation.ollama import OllamaTranslateProvider
        from .keychain import get_storage_mode

        y = self.HEIGHT - self.PADDING

        # Title
        y -= 36
        title = self._create_label(
            "Translation Setup (Optional)",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 32),
            font_size=22,
            bold=True
        )
        self._content_view.addSubview_(title)

        # Description
        y -= 44
        desc = self._create_label(
            "Skip for the fastest first transcript, or enable now to auto-translate after each transcription.",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 34),
            font_size=13,
            align=NSLeftTextAlignment
        )
        self._content_view.addSubview_(desc)

        # Refresh local dependency status
        self._ollama_installed = OllamaTranslateProvider.is_ollama_installed()
        self._ollama_running = self._check_ollama_running() if self._ollama_installed else False

        y -= 44
        enable_label = self._create_label(
            "Translation mode:",
            NSMakeRect(self.PADDING, y, 180, 24),
            font_size=13
        )
        self._content_view.addSubview_(enable_label)

        self._translation_enable_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(self.PADDING + 160, y - 2, self.WIDTH - 2 * self.PADDING - 160, 26),
            False,
        )
        self._translation_enable_popup.addItemsWithTitles_([
            "Off (skip for now)",
            "On (translate after transcription)",
        ])
        self._translation_enable_popup.selectItemAtIndex_(1 if self._translation_enabled else 0)
        self._translation_enable_popup._wizard_action = self._on_translation_enable_changed
        self._translation_enable_popup.setTarget_(self)
        self._translation_enable_popup.setAction_("buttonClicked:")
        self._content_view.addSubview_(self._translation_enable_popup)

        provider_specs = self._get_translation_provider_specs()
        provider_ids = [spec["id"] for spec in provider_specs]
        if self._translation_provider not in provider_ids:
            self._translation_provider = "apple"

        y -= 40
        provider_label = self._create_label(
            "Provider:",
            NSMakeRect(self.PADDING, y, 180, 24),
            font_size=13
        )
        self._content_view.addSubview_(provider_label)

        self._translation_provider_choices = []
        provider_titles = []
        for spec in provider_specs:
            display = f"{spec['name']} — {spec['status']}"
            provider_titles.append(display)
            self._translation_provider_choices.append((spec["id"], display))

        self._translation_provider_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(self.PADDING + 160, y - 2, self.WIDTH - 2 * self.PADDING - 160, 26),
            False,
        )
        self._translation_provider_popup.addItemsWithTitles_(provider_titles)
        selected_provider_index = provider_ids.index(self._translation_provider)
        self._translation_provider_popup.selectItemAtIndex_(selected_provider_index)
        self._translation_provider_popup._wizard_action = self._on_translation_provider_changed
        self._translation_provider_popup.setTarget_(self)
        self._translation_provider_popup.setAction_("buttonClicked:")
        self._content_view.addSubview_(self._translation_provider_popup)

        model_choices = self._get_translation_model_choices(self._translation_provider)
        self._translation_model_choices = model_choices
        if self._translation_provider not in self._translation_models:
            self._translation_models[self._translation_provider] = model_choices[0][0]
        if self._translation_models[self._translation_provider] not in {mid for mid, _ in model_choices}:
            self._translation_models[self._translation_provider] = model_choices[0][0]

        y -= 40
        model_label = self._create_label(
            "Model:",
            NSMakeRect(self.PADDING, y, 180, 24),
            font_size=13
        )
        self._content_view.addSubview_(model_label)

        self._translation_model_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(self.PADDING + 160, y - 2, self.WIDTH - 2 * self.PADDING - 160, 26),
            False,
        )
        self._translation_model_popup.addItemsWithTitles_([name for _, name in model_choices])
        current_model = self._translation_models[self._translation_provider]
        for idx, (model_id, _) in enumerate(model_choices):
            if model_id == current_model:
                self._translation_model_popup.selectItemAtIndex_(idx)
                break
        self._translation_model_popup._wizard_action = self._on_translation_model_changed
        self._translation_model_popup.setTarget_(self)
        self._translation_model_popup.setAction_("buttonClicked:")
        self._content_view.addSubview_(self._translation_model_popup)

        language_map = self._get_translation_language_map(self._translation_provider)
        if self._translation_target_language not in language_map:
            if "en" in language_map:
                self._translation_target_language = "en"
            elif "zh" in language_map:
                self._translation_target_language = "zh"
            else:
                self._translation_target_language = sorted(language_map.keys())[0]
        if self._translation_source_language != "auto" and self._translation_source_language not in language_map:
            self._translation_source_language = "auto"

        y -= 40
        target_label = self._create_label(
            "Target language:",
            NSMakeRect(self.PADDING, y, 180, 24),
            font_size=13
        )
        self._content_view.addSubview_(target_label)

        self._translation_target_choices = self._ordered_language_codes(language_map, include_auto=False)
        self._translation_target_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(self.PADDING + 160, y - 2, self.WIDTH - 2 * self.PADDING - 160, 26),
            False,
        )
        self._translation_target_popup.addItemsWithTitles_(
            [f"{language_map[code]} ({code})" for code in self._translation_target_choices]
        )
        self._translation_target_popup.selectItemAtIndex_(
            self._translation_target_choices.index(self._translation_target_language)
        )
        self._translation_target_popup._wizard_action = self._on_translation_target_changed
        self._translation_target_popup.setTarget_(self)
        self._translation_target_popup.setAction_("buttonClicked:")
        self._content_view.addSubview_(self._translation_target_popup)

        y -= 40
        source_label = self._create_label(
            "Source language:",
            NSMakeRect(self.PADDING, y, 180, 24),
            font_size=13
        )
        self._content_view.addSubview_(source_label)

        self._translation_source_choices = ["auto"] + self._ordered_language_codes(language_map, include_auto=False)
        source_titles = ["Auto (detect)"] + [
            f"{language_map[code]} ({code})" for code in self._translation_source_choices if code != "auto"
        ]
        self._translation_source_popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(self.PADDING + 160, y - 2, self.WIDTH - 2 * self.PADDING - 160, 26),
            False,
        )
        self._translation_source_popup.addItemsWithTitles_(source_titles)
        self._translation_source_popup.selectItemAtIndex_(
            self._translation_source_choices.index(self._translation_source_language)
        )
        self._translation_source_popup._wizard_action = self._on_translation_source_changed
        self._translation_source_popup.setTarget_(self)
        self._translation_source_popup.setAction_("buttonClicked:")
        self._content_view.addSubview_(self._translation_source_popup)

        y -= 54
        storage_mode = get_storage_mode()
        storage_hint = {
            "passphrase": "API keys: encrypted local passphrase store",
            "keychain": "API keys: macOS Keychain",
            "none": "API keys: session-only (cleared on quit)",
        }.get(storage_mode, "API keys: encrypted local passphrase store")
        summary_lines = [storage_hint]
        if not self._translation_enabled:
            summary_lines.append("Translation is off for first run (you can enable anytime).")
        else:
            target_name = language_map.get(self._translation_target_language, self._translation_target_language)
            source_name = (
                "Auto detect"
                if self._translation_source_language == "auto"
                else language_map.get(self._translation_source_language, self._translation_source_language)
            )
            model_name = dict(model_choices).get(
                self._translation_models[self._translation_provider],
                self._translation_models[self._translation_provider],
            )
            provider_name = dict((spec["id"], spec["name"]) for spec in provider_specs).get(
                self._translation_provider,
                self._translation_provider,
            )
            summary_lines.append(
                f"Translation on: {provider_name} • {model_name} • {source_name} -> {target_name}"
            )
            if self._translation_provider == "ollama" and not self._ollama_running:
                summary_lines.append("Ollama is not running yet; start it now or later in app settings.")
            if self._translation_provider in {"openai", "gemini", "anthropic"}:
                summary_lines.append("Cloud translation needs a valid API key for that provider.")

        summary_label = self._create_label(
            "\n".join(summary_lines),
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 48),
            font_size=11,
            color=self._secondary_text_color(),
            align=NSLeftTextAlignment,
        )
        self._content_view.addSubview_(summary_label)

        y -= 36
        if self._translation_enabled and self._translation_provider == "ollama":
            if not self._ollama_installed:
                install_btn = self._create_button(
                    "Install Ollama",
                    NSMakeRect(self.PADDING, y, 150, 30),
                    action=self._install_ollama,
                )
                self._content_view.addSubview_(install_btn)
            elif not self._ollama_running:
                start_btn = self._create_button(
                    "Start Ollama",
                    NSMakeRect(self.PADDING, y, 150, 30),
                    action=self._start_ollama,
                )
                self._content_view.addSubview_(start_btn)

        # Progress indicator for install/start actions
        self._progress_indicator = NSProgressIndicator.alloc().initWithFrame_(
            NSMakeRect(self.PADDING + 170, y + 5, 20, 20)
        )
        self._progress_indicator.setStyle_(NSProgressIndicatorSpinningStyle)
        self._progress_indicator.setHidden_(True)
        self._content_view.addSubview_(self._progress_indicator)

        # Navigation
        self._add_navigation_buttons(
            back_title="Back",
            back_action=self._go_back_from_translation,
            extra_title="Skip Translation",
            extra_action=self._skip_translation_setup,
            next_title="Next",
            next_action=lambda: self._show_step(WizardStep.COMPLETE)
        )

    def _show_complete(self):
        """Show completion step."""
        y = self.HEIGHT - self.PADDING

        # Title
        y -= 40
        title = self._create_label(
            "Setup Complete!",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 36),
            font_size=24,
            bold=True
        )
        self._content_view.addSubview_(title)

        # Summary
        y -= 140
        mode_name = "Cloud" if self._transcription_mode == "cloud" else "Local"
        provider_names = {
            "gemini": "Google Gemini",
            "openai": "OpenAI",
            "openai_realtime": "OpenAI Realtime",
            "apple": "Apple Speech",
            "whisper_local": "Whisper Local",
            "parakeet": "Parakeet"
        }
        provider_name = provider_names.get(self._selected_provider, self._selected_provider)

        translation_provider_names = {
            "apple": "Apple (Local)",
            "ollama": "Ollama (Local)",
            "gemini": "Gemini (Cloud)",
            "openai": "OpenAI (Cloud)",
            "anthropic": "Anthropic (Cloud)",
        }
        if self._translation_enabled:
            t_provider = translation_provider_names.get(self._translation_provider, self._translation_provider)
            t_model = self._translation_models.get(self._translation_provider, "default")
            t_source = "Auto detect" if self._translation_source_language == "auto" else self._translation_source_language
            t_target = self._translation_target_language
            translation_line = (
                f"Translation: ON ({t_provider}, {t_model}, {t_source} -> {t_target})"
            )
        else:
            translation_line = "Translation: OFF (you can enable it anytime)"

        remaining_items = []
        if self._translation_enabled and self._translation_provider == "ollama" and not self._ollama_running:
            remaining_items.append("Start Ollama before using local translation.")
        if self._translation_enabled and self._translation_provider in {"openai", "gemini", "anthropic"}:
            remaining_items.append("Make sure that cloud provider API key is configured.")
        if self._selected_provider in {"whisper_local", "parakeet"}:
            remaining_items.append("First use downloads local model files.")
        remaining_text = (
            "Remaining optional steps:\n  - " + "\n  - ".join(remaining_items)
            if remaining_items
            else "Remaining optional steps: none"
        )

        summary = (
            f"You're all set to use WhisperHUD!\n\n"
            f"Mode: {mode_name}\n"
            f"Provider: {provider_name}\n"
            f"API Key: {'Configured' if self._transcription_mode == 'cloud' else 'Not required (local)'}\n"
            f"{translation_line}\n\n"
            f"{remaining_text}"
        )
        summary_label = self._create_label(
            summary,
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 140),
            font_size=13,
            align=NSLeftTextAlignment
        )
        self._content_view.addSubview_(summary_label)

        # Usage tips
        y -= 122
        tips = self._create_label(
            "Quick Start:\n"
            "  Hold Command+Shift+Space to record\n"
            "  Release to transcribe and paste\n"
            "  Toggle translation from the Translation menu\n"
            "  Click the menu bar icon for settings\n\n"
            "You can re-run this wizard from the menu anytime.",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 112),
            font_size=13,
            color=self._secondary_text_color(),
            align=NSLeftTextAlignment
        )
        self._content_view.addSubview_(tips)

        # Finish button
        self._add_navigation_buttons(
            back_title="Back",
            back_action=lambda: self._show_step(WizardStep.TRANSLATION),
            next_title="Finish",
            next_action=self._finish_wizard
        )

    # === UI Helper Methods ===

    def _refresh_appearance(self):
        """Apply colors from the current macOS appearance."""
        self._is_dark_mode = self._detect_dark_mode()

        if self._window:
            try:
                appearance_name = NSAppearanceNameDarkAqua if self._is_dark_mode else NSAppearanceNameAqua
                self._window.setAppearance_(NSAppearance.appearanceNamed_(appearance_name))
            except Exception:
                pass
            self._window.setBackgroundColor_(self._background_color())

    def _detect_dark_mode(self) -> bool:
        """Return whether the effective system appearance is dark."""
        appearance = None

        if self._window and hasattr(self._window, "effectiveAppearance"):
            try:
                appearance = self._window.effectiveAppearance()
            except Exception:
                appearance = None

        if appearance is None:
            try:
                appearance = NSApplication.sharedApplication().effectiveAppearance()
            except Exception:
                appearance = None

        if appearance is None:
            return False

        try:
            match = appearance.bestMatchFromAppearancesWithNames_([
                NSAppearanceNameAqua,
                NSAppearanceNameDarkAqua,
            ])
            return match == NSAppearanceNameDarkAqua
        except Exception:
            return "dark" in str(appearance).lower()

    def _background_color(self):
        """Return the wizard background color for the current appearance."""
        if self._is_dark_mode:
            return NSColor.colorWithCalibratedWhite_alpha_(0.12, 1.0)
        return NSColor.colorWithCalibratedWhite_alpha_(0.97, 1.0)

    def _primary_text_color(self):
        """Return the primary text color for the current appearance."""
        if self._is_dark_mode:
            return NSColor.whiteColor()
        return NSColor.colorWithCalibratedWhite_alpha_(0.1, 1.0)

    def _secondary_text_color(self):
        """Return the secondary text color for the current appearance."""
        if self._is_dark_mode:
            return NSColor.colorWithCalibratedWhite_alpha_(0.75, 1.0)
        return NSColor.colorWithCalibratedWhite_alpha_(0.35, 1.0)

    def _muted_text_color(self):
        """Return a muted text color for the current appearance."""
        if self._is_dark_mode:
            return NSColor.colorWithCalibratedWhite_alpha_(0.5, 1.0)
        return NSColor.colorWithCalibratedWhite_alpha_(0.45, 1.0)

    def _accent_text_color(self):
        """Return the accent/info text color for the current appearance."""
        if self._is_dark_mode:
            return NSColor.colorWithCalibratedRed_green_blue_alpha_(0.6, 0.8, 1.0, 1.0)
        return NSColor.colorWithCalibratedRed_green_blue_alpha_(0.16, 0.39, 0.78, 1.0)

    def _get_step_sequence(self) -> list[WizardStep]:
        """Return the visible step order for the current transcription mode."""
        setup_step = WizardStep.CLOUD_SETUP if self._transcription_mode == "cloud" else WizardStep.LOCAL_SETUP
        return [
            WizardStep.WELCOME,
            WizardStep.TRANSCRIPTION_MODE,
            setup_step,
            WizardStep.TRANSLATION,
            WizardStep.COMPLETE,
        ]

    def _get_step_progress(self, step: WizardStep) -> tuple[int, int]:
        """Return the 1-based step position and total visible steps."""
        steps = self._get_step_sequence()
        if step not in steps:
            step = steps[0]
        return steps.index(step) + 1, len(steps)

    def _add_step_progress(self, step: WizardStep):
        """Show the wizard progress header on every page."""
        current, total = self._get_step_progress(step)
        progress_label = self._create_label(
            f"Step {current} of {total}",
            NSMakeRect(self.PADDING, self.HEIGHT - 26, 140, 18),
            font_size=11,
            color=self._secondary_text_color(),
        )
        self._content_view.addSubview_(progress_label)

        dot_text = " ".join("●" if index < current else "○" for index in range(total))
        dot_label = self._create_label(
            dot_text,
            NSMakeRect(self.WIDTH - self.PADDING - 120, self.HEIGHT - 28, 120, 18),
            font_size=11,
            color=self._accent_text_color(),
        )
        self._content_view.addSubview_(dot_label)

    def _create_label(
        self,
        text: str,
        frame,
        font_size: float = 14,
        bold: bool = False,
        color=None,
        align=None
    ) -> NSTextField:
        """Create a label with common settings."""
        label = NSTextField.alloc().initWithFrame_(frame)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setStringValue_(text)

        if bold:
            label.setFont_(NSFont.boldSystemFontOfSize_(font_size))
        else:
            label.setFont_(NSFont.systemFontOfSize_(font_size))

        label.setTextColor_(color or self._primary_text_color())

        if align is not None:
            label.setAlignment_(align)

        return label

    def _create_button(self, title: str, frame, action: Callable) -> NSButton:
        """Create a button."""
        button = NSButton.alloc().initWithFrame_(frame)
        button.setTitle_(title)
        button.setBezelStyle_(1)  # Rounded
        button.setTarget_(self)

        button._wizard_action = action
        button.setAction_("buttonClicked:")

        return button

    def _estimate_wrapped_line_count(self, text: str, width: float, font_size: float) -> int:
        """Estimate the number of rendered lines for a wrapped button title."""
        usable_width = max(width - 28, font_size)
        approx_char_width = max(font_size * 0.56, 1)
        chars_per_line = max(int(usable_width / approx_char_width), 1)

        line_count = 0
        for raw_line in text.splitlines() or [""]:
            line = raw_line.strip()
            if not line:
                line_count += 1
                continue
            line_count += max((len(line) + chars_per_line - 1) // chars_per_line, 1)
        return max(line_count, 1)

    def _wrapped_button_height(self, text: str, width: float, font_size: float, minimum_height: float) -> float:
        """Return a button height that fits a wrapped title without clipping."""
        line_count = self._estimate_wrapped_line_count(text, width, font_size)
        line_height = max(font_size + 4, 16)
        content_height = 14 + (line_count * line_height)
        return max(minimum_height, content_height)

    def _apply_wrapped_button_title(
        self,
        button: NSButton,
        text: str,
        frame,
        font_size: float,
        align: int = NSLeftTextAlignment,
        minimum_height: float | None = None,
    ) -> NSButton:
        """Configure a button title for multiline wrapping and resize its frame if needed."""
        button.setTitle_(text)

        paragraph_style = None
        if HAS_APPKIT:
            try:
                paragraph_style = NSMutableParagraphStyle.alloc().init()
                paragraph_style.setAlignment_(align)
                if hasattr(paragraph_style, "setLineBreakMode_"):
                    paragraph_style.setLineBreakMode_(0)

                attributes = {
                    NSFontAttributeName: NSFont.systemFontOfSize_(font_size),
                    NSForegroundColorAttributeName: self._primary_text_color(),
                    NSParagraphStyleAttributeName: paragraph_style,
                }
                attributed_title = NSAttributedString.alloc().initWithString_attributes_(text, attributes)
                if hasattr(button, "setAttributedTitle_"):
                    button.setAttributedTitle_(attributed_title)
            except Exception:
                paragraph_style = None

        if hasattr(button, "cell"):
            try:
                cell = button.cell()
                if hasattr(cell, "setWraps_"):
                    cell.setWraps_(True)
                if hasattr(cell, "setUsesSingleLineMode_"):
                    cell.setUsesSingleLineMode_(False)
                if hasattr(cell, "setScrollable_"):
                    cell.setScrollable_(False)
                if hasattr(cell, "setLineBreakMode_"):
                    cell.setLineBreakMode_(0)
            except Exception:
                pass

        if minimum_height is not None:
            frame.size.height = self._wrapped_button_height(text, frame.size.width, font_size, minimum_height)
            button.setFrame_(frame)

        return button

    def _create_provider_button(
        self,
        title: str,
        subtitle: str,
        frame,
        selected: bool,
        action: Callable
    ) -> NSButton:
        """Create a provider selection button."""
        button = NSButton.alloc().initWithFrame_(frame)
        button.setBezelStyle_(1)
        self._apply_wrapped_button_title(
            button,
            f"{title}\n{subtitle}",
            frame,
            font_size=13,
            minimum_height=frame.size.height,
        )

        if selected:
            button.setState_(1)

        button._wizard_action = action
        button.setTarget_(self)
        button.setAction_("buttonClicked:")

        return button

    def _create_mode_card(
        self,
        title: str,
        subtitle: str,
        description: str,
        frame,
        selected: bool,
        action: Callable
    ) -> NSButton:
        """Create a mode selection card button."""
        button = NSButton.alloc().initWithFrame_(frame)
        button.setBezelStyle_(1)
        self._apply_wrapped_button_title(
            button,
            f"{title}\n{subtitle}\n\n{description}",
            frame,
            font_size=13,
            minimum_height=frame.size.height,
        )

        if selected:
            button.setState_(1)

        button._wizard_action = action
        button.setTarget_(self)
        button.setAction_("buttonClicked:")

        return button

    def _create_local_provider_option(
        self,
        title: str,
        description: str,
        frame,
        selected: bool,
        action: Callable
    ) -> NSButton:
        """Create a local provider option button."""
        button = NSButton.alloc().initWithFrame_(frame)
        prefix = "● " if selected else "○ "
        button.setTitle_(f"{prefix}{title} - {description}")
        button.setBezelStyle_(1)

        button._wizard_action = action
        button.setTarget_(self)
        button.setAction_("buttonClicked:")

        return button

    def buttonClicked_(self, sender):
        """Handle button click."""
        if hasattr(sender, '_wizard_action') and sender._wizard_action:
            sender._wizard_action()

    def _add_navigation_buttons(
        self,
        back_title: Optional[str] = None,
        back_action: Optional[Callable] = None,
        extra_title: Optional[str] = None,
        extra_action: Optional[Callable] = None,
        next_title: str = "Next",
        next_action: Optional[Callable] = None,
        next_enabled: bool = True
    ):
        """Add navigation buttons at bottom."""
        y = self.PADDING

        # Cancel button (always shown)
        cancel_btn = self._create_button(
            "Cancel",
            NSMakeRect(self.PADDING, y, 80, 32),
            action=self._cancel_wizard
        )
        self._content_view.addSubview_(cancel_btn)

        # Back button
        if back_title and back_action:
            back_btn = self._create_button(
                back_title,
                NSMakeRect(self.WIDTH - 2 * self.PADDING - 180, y, 80, 32),
                action=back_action
            )
            self._content_view.addSubview_(back_btn)

        if extra_title and extra_action:
            extra_btn = self._create_button(
                extra_title,
                NSMakeRect(self.WIDTH - 2 * self.PADDING - 310, y, 120, 32),
                action=extra_action,
            )
            self._content_view.addSubview_(extra_btn)

        # Next button
        if next_action:
            self._next_button = self._create_button(
                next_title,
                NSMakeRect(self.WIDTH - self.PADDING - 90, y, 90, 32),
                action=next_action
            )
            self._next_button.setEnabled_(next_enabled)
            self._content_view.addSubview_(self._next_button)

    def controlTextDidChange_(self, notification):
        """Handle AppKit text change notifications."""
        if self._current_step == WizardStep.CLOUD_SETUP:
            self._handle_api_key_input_changed()

    def _dispatch_to_main_thread(self, callback: Callable[[], None]):
        """Dispatch a callback onto the AppKit main thread when available."""
        if HAS_APPKIT:
            AppHelper.callAfter(callback)
            return
        callback()

    def _cancel_api_key_validation_timer(self):
        """Cancel any pending debounced validation timer."""
        if self._api_key_validation_timer:
            self._api_key_validation_timer.cancel()
            self._api_key_validation_timer = None

    def _next_api_key_validation_request_id(self) -> int:
        """Return a new request id and invalidate older validation work."""
        with self._api_key_validation_lock:
            self._api_key_validation_request_id += 1
            return self._api_key_validation_request_id

    def _current_api_key_validation_request_id(self) -> int:
        """Return the latest validation request id."""
        with self._api_key_validation_lock:
            return self._api_key_validation_request_id

    def _normalized_validation_provider(self, provider: str) -> str:
        """Map UI provider ids to validate_api_key provider ids."""
        if provider == "openai_realtime":
            return "openai"
        return provider

    def _set_api_key_validation_state(
        self,
        status: str,
        message: str,
        *,
        validated_key: str = "",
        validated_provider: str = "",
        acknowledged: Optional[bool] = None
    ):
        """Update inline validation state and refresh the cloud UI."""
        self._api_key_validation_status = status
        self._api_key_validation_message = message
        self._api_key_validation_key = validated_key
        self._api_key_validation_provider = validated_provider
        if acknowledged is not None:
            self._api_key_validation_acknowledged = acknowledged
        self._refresh_api_key_validation_ui()

    def _handle_api_key_input_changed(self):
        """Debounce inline API key validation after user input changes."""
        if self._current_step != WizardStep.CLOUD_SETUP:
            return

        current_key = ""
        if self._api_key_field:
            current_key = self._api_key_field.stringValue().strip()

        provider = self._normalized_validation_provider(self._selected_provider)
        changed = current_key != self._api_key_validation_key or provider != self._api_key_validation_provider

        self._api_key = current_key
        if changed:
            self._api_key_validation_acknowledged = False

        self._cancel_api_key_validation_timer()
        self._next_api_key_validation_request_id()

        if not current_key:
            self._set_api_key_validation_state(
                "idle",
                "Enter an API key to continue",
                validated_key="",
                validated_provider="",
                acknowledged=False,
            )
            return

        self._set_api_key_validation_state(
            "pending",
            "Waiting to validate API key...",
            validated_key="",
            validated_provider="",
            acknowledged=False,
        )

        request_id = self._current_api_key_validation_request_id()
        self._api_key_validation_timer = threading.Timer(
            0.5,
            lambda: self._begin_api_key_validation(request_id, provider, current_key),
        )
        self._api_key_validation_timer.daemon = True
        self._api_key_validation_timer.start()

    def _begin_api_key_validation(self, request_id: int, provider: str, api_key: str):
        """Start API key validation on a background thread."""
        def mark_validating():
            if not self._should_apply_api_key_validation_result(request_id, provider, api_key):
                return
            self._set_api_key_validation_state(
                "validating",
                "Validating API key...",
                validated_key="",
                validated_provider="",
            )

        self._dispatch_to_main_thread(mark_validating)

        def do_validate():
            from .keychain import validate_api_key

            is_valid, error = validate_api_key(provider, api_key)

            def apply_result():
                if not self._should_apply_api_key_validation_result(request_id, provider, api_key):
                    return
                if is_valid:
                    self._set_api_key_validation_state(
                        "valid",
                        "API key validated",
                        validated_key=api_key,
                        validated_provider=provider,
                        acknowledged=False,
                    )
                else:
                    self._set_api_key_validation_state(
                        "invalid",
                        error or "API key validation failed",
                        validated_key=api_key,
                        validated_provider=provider,
                        acknowledged=False,
                    )

            self._dispatch_to_main_thread(apply_result)

        threading.Thread(target=do_validate, daemon=True).start()

    def _should_apply_api_key_validation_result(self, request_id: int, provider: str, api_key: str) -> bool:
        """Return whether a validation result still matches the current UI state."""
        if request_id != self._current_api_key_validation_request_id():
            return False
        if self._current_step != WizardStep.CLOUD_SETUP:
            return False
        if self._normalized_validation_provider(self._selected_provider) != provider:
            return False
        return self._api_key.strip() == api_key

    def _refresh_api_key_validation_ui(self):
        """Update the inline cloud validation widgets."""
        spinner = self._api_key_spinner
        if spinner:
            if self._api_key_validation_status == "validating":
                spinner.setHidden_(False)
                spinner.startAnimation_(None)
            else:
                spinner.stopAnimation_(None)
                spinner.setHidden_(True)

        icon = self._api_key_status_icon
        label = self._api_key_status_label
        status = self._api_key_validation_status

        icon_text = ""
        color = NSColor.colorWithCalibratedWhite_alpha_(0.7, 1.0) if HAS_APPKIT else None

        if status == "valid":
            icon_text = "✓"
        elif status == "invalid":
            icon_text = "✗"
        elif status == "skipped":
            icon_text = "!"

        if HAS_APPKIT:
            if status == "valid":
                color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.35, 0.85, 0.45, 1.0)
            elif status == "invalid":
                color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.95, 0.35, 0.35, 1.0)
            elif status == "skipped":
                color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.95, 0.75, 0.3, 1.0)
            elif status in {"pending", "validating"}:
                color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.6, 0.8, 1.0, 1.0)

        if icon:
            icon.setStringValue_(icon_text)
            if color is not None:
                icon.setTextColor_(color)

        if label:
            label.setStringValue_(self._api_key_validation_message)
            if color is not None:
                label.setTextColor_(color)

        if self._skip_validation_button:
            can_skip = bool(self._api_key) and status != "validating"
            self._skip_validation_button.setEnabled_(can_skip)

        if self._next_button:
            next_enabled = self._can_continue_cloud_setup() and status != "validating"
            self._next_button.setEnabled_(next_enabled)

    def _can_continue_cloud_setup(self) -> bool:
        """Return whether the cloud step can advance."""
        if not self._api_key:
            return False
        return self._api_key_validation_status == "valid" or self._api_key_validation_acknowledged

    def _skip_api_key_validation(self):
        """Allow the user to continue after explicitly acknowledging validation was skipped."""
        if not self._api_key:
            return

        self._cancel_api_key_validation_timer()
        self._next_api_key_validation_request_id()
        self._set_api_key_validation_state(
            "skipped",
            "Validation skipped. The key may still fail when used.",
            validated_key=self._api_key,
            validated_provider=self._normalized_validation_provider(self._selected_provider),
            acknowledged=True,
        )

    def _prompt_secure_input(self, title: str, message: str) -> Optional[str]:
        """Prompt for hidden input using AppleScript."""
        import subprocess

        message_escaped = message.replace('"', '\\"').replace('\n', '\\n')
        title_escaped = title.replace('"', '\\"')
        script = f'''
        tell application "System Events"
            activate
            set userInput to display dialog "{message_escaped}" default answer "" with title "{title_escaped}" with hidden answer buttons {{"Cancel", "Save"}} default button "Save"
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
            logger.error(f"Secure input dialog error: {e}")

        return None

    def _get_translation_provider_specs(self) -> list[dict]:
        """Return provider options shown in the translation step."""
        return [
            {
                "id": "apple",
                "name": "Apple (Local)",
                "status": "ready now",
            },
            {
                "id": "ollama",
                "name": "Ollama (Local)",
                "status": (
                    "running"
                    if self._ollama_running
                    else ("installed, start needed" if self._ollama_installed else "install needed")
                ),
            },
            {
                "id": "gemini",
                "name": "Gemini (Cloud)",
                "status": "API key required",
            },
            {
                "id": "openai",
                "name": "OpenAI (Cloud)",
                "status": "API key required",
            },
            {
                "id": "anthropic",
                "name": "Anthropic (Cloud)",
                "status": "API key required",
            },
        ]

    def _get_translation_model_choices(self, provider_id: str) -> list[tuple[str, str]]:
        """Return (model_id, display_name) choices for a translation provider."""
        if provider_id == "apple":
            return [("system", "System default")]

        try:
            if provider_id == "ollama":
                from .providers.translation.ollama import OllamaTranslateProvider as ProviderClass
            elif provider_id == "gemini":
                from .providers.translation.gemini_translate import GeminiTranslateProvider as ProviderClass
            elif provider_id == "openai":
                from .providers.translation.openai_translate import OpenAITranslateProvider as ProviderClass
            elif provider_id == "anthropic":
                from .providers.translation.anthropic_translate import AnthropicTranslateProvider as ProviderClass
            else:
                return [("system", "System default")]

            provider = ProviderClass()
            models = provider.get_models()
            if not models:
                return [("system", "System default")]

            choices = []
            for model in models:
                model_id = str(model.get("id", ""))
                name = str(model.get("name", model_id))
                suffix = " ★" if model.get("recommended") else ""
                choices.append((model_id, f"{name}{suffix}"))
            return choices
        except Exception:
            logger.debug(f"Could not load translation models for provider {provider_id}")
            return [("system", "System default")]

    def _get_translation_language_map(self, provider_id: str) -> dict[str, str]:
        """Return language map for selected translation provider."""
        try:
            if provider_id == "ollama":
                from .providers.translation.ollama import OllamaTranslateProvider as ProviderClass
            elif provider_id == "gemini":
                from .providers.translation.gemini_translate import GeminiTranslateProvider as ProviderClass
            elif provider_id == "openai":
                from .providers.translation.openai_translate import OpenAITranslateProvider as ProviderClass
            elif provider_id == "anthropic":
                from .providers.translation.anthropic_translate import AnthropicTranslateProvider as ProviderClass
            else:
                from .providers.translation.apple_translate import AppleTranslateProvider as ProviderClass

            return ProviderClass.get_supported_languages()
        except Exception:
            # Keep setup usable even if one provider metadata call fails.
            return {
                "en": "English",
                "zh": "Chinese (Simplified)",
                "es": "Spanish",
                "fr": "French",
                "de": "German",
                "ja": "Japanese",
            }

    def _ordered_language_codes(self, languages: dict[str, str], include_auto: bool = False) -> list[str]:
        """Return language codes with common languages first."""
        common = ["en", "zh", "zh-TW", "es", "fr", "de", "it", "pt", "ja", "ko", "ar", "ru"]
        ordered = [code for code in common if code in languages]
        ordered.extend(
            sorted(
                [code for code in languages.keys() if code not in ordered],
                key=lambda c: languages[c],
            )
        )
        if include_auto:
            return ["auto"] + ordered
        return ordered

    def _on_translation_enable_changed(self):
        """Handle translation enable popup selection."""
        self._translation_enabled = self._translation_enable_popup.indexOfSelectedItem() == 1
        self._show_step(WizardStep.TRANSLATION)

    def _on_translation_provider_changed(self):
        """Handle translation provider popup selection."""
        idx = self._translation_provider_popup.indexOfSelectedItem()
        if 0 <= idx < len(self._translation_provider_choices):
            provider_id = self._translation_provider_choices[idx][0]
            self._translation_provider = provider_id
            model_choices = self._get_translation_model_choices(provider_id)
            if provider_id not in self._translation_models:
                self._translation_models[provider_id] = model_choices[0][0]
            if self._translation_models[provider_id] not in {mid for mid, _ in model_choices}:
                self._translation_models[provider_id] = model_choices[0][0]
        self._show_step(WizardStep.TRANSLATION)

    def _on_translation_model_changed(self):
        """Handle translation model popup selection."""
        idx = self._translation_model_popup.indexOfSelectedItem()
        if 0 <= idx < len(self._translation_model_choices):
            model_id = self._translation_model_choices[idx][0]
            self._translation_models[self._translation_provider] = model_id
        self._show_step(WizardStep.TRANSLATION)

    def _on_translation_target_changed(self):
        """Handle translation target language popup selection."""
        idx = self._translation_target_popup.indexOfSelectedItem()
        if 0 <= idx < len(self._translation_target_choices):
            self._translation_target_language = self._translation_target_choices[idx]
        self._show_step(WizardStep.TRANSLATION)

    def _on_translation_source_changed(self):
        """Handle translation source language popup selection."""
        idx = self._translation_source_popup.indexOfSelectedItem()
        if 0 <= idx < len(self._translation_source_choices):
            self._translation_source_language = self._translation_source_choices[idx]
        self._show_step(WizardStep.TRANSLATION)

    # === Action Handlers ===

    def _select_mode(self, mode: str):
        """Handle mode selection."""
        self._transcription_mode = mode

        # Set default provider based on mode
        if mode == "cloud":
            self._selected_provider = "gemini"
        else:
            self._selected_provider = "apple"  # Easiest local option

        self._show_step(WizardStep.TRANSCRIPTION_MODE)

    def _select_provider(self, provider: str):
        """Handle provider selection."""
        provider_changed = self._selected_provider != provider
        self._selected_provider = provider
        if provider_changed:
            self._cancel_api_key_validation_timer()
            self._next_api_key_validation_request_id()
            self._api_key_validation_acknowledged = False
            self._api_key_validation_status = "idle"
            self._api_key_validation_message = "Enter an API key to continue"
            self._api_key_validation_key = ""
            self._api_key_validation_provider = ""

        # Refresh current step
        if self._current_step == WizardStep.CLOUD_SETUP:
            self._show_step(WizardStep.CLOUD_SETUP)
        elif self._current_step == WizardStep.LOCAL_SETUP:
            self._show_step(WizardStep.LOCAL_SETUP)

    def _continue_from_mode_selection(self):
        """Continue from mode selection to appropriate setup."""
        if self._transcription_mode == "cloud":
            self._show_step(WizardStep.CLOUD_SETUP)
        else:
            self._show_step(WizardStep.LOCAL_SETUP)

    def _validate_and_continue_cloud(self):
        """Validate cloud setup and continue."""
        from .keychain import (
            set_api_key,
            get_storage_mode,
            has_passphrase_store,
            is_passphrase_unlocked,
            unlock_passphrase_store,
        )

        if self._api_key_field:
            self._api_key = self._api_key_field.stringValue()

        if not self._api_key:
            self._show_error("Please enter an API key")
            return

        if not self._can_continue_cloud_setup():
            if self._api_key_validation_status == "validating":
                self._show_error("Wait for API key validation to finish")
            else:
                self._show_error("Validate the API key or choose Skip Validation")
            return

        if get_storage_mode() == "passphrase" and not is_passphrase_unlocked():
            if has_passphrase_store():
                passphrase = self._prompt_secure_input(
                    "Unlock API Key Store",
                    "Enter your API key storage passphrase."
                )
                if not passphrase:
                    self._show_error("Passphrase required to save API key")
                    return
            else:
                passphrase = self._prompt_secure_input(
                    "Create API Key Passphrase",
                    "Create a passphrase to encrypt API keys."
                )
                if not passphrase or len(passphrase) < 8:
                    self._show_error("Passphrase must be at least 8 characters")
                    return
                confirm = self._prompt_secure_input(
                    "Confirm Passphrase",
                    "Re-enter your passphrase."
                )
                if passphrase != confirm:
                    self._show_error("Passphrases do not match")
                    return

            ok, message = unlock_passphrase_store(passphrase)
            if not ok:
                self._show_error(message or "Failed to unlock API key storage")
                return

        # Save the API key
        key_provider = "openai" if self._selected_provider == "openai_realtime" else self._selected_provider
        if not set_api_key(key_provider, self._api_key):
            self._show_error("Could not store API key. Check credential storage settings.")
            return

        # Clear in-memory key after storing
        self._api_key = ""
        if self._api_key_field:
            try:
                self._api_key_field.setStringValue_("")
            except Exception:
                pass

        # Continue to translation step
        self._show_step(WizardStep.TRANSLATION)

    def _continue_from_local_setup(self):
        """Continue from local setup to translation."""
        # Just continue - model download will happen when user first uses it
        self._show_step(WizardStep.TRANSLATION)

    def _skip_translation_setup(self):
        """Skip translation setup and continue to completion."""
        self._translation_enabled = False
        self._show_step(WizardStep.COMPLETE)

    def _go_back_from_translation(self):
        """Go back from translation to appropriate setup step."""
        if self._transcription_mode == "cloud":
            self._show_step(WizardStep.CLOUD_SETUP)
        else:
            self._show_step(WizardStep.LOCAL_SETUP)

    def _check_ollama_running(self) -> bool:
        """Check if Ollama server is running."""
        try:
            import requests
            response = requests.get("http://localhost:11434/api/tags", timeout=2)
            return response.status_code == 200
        except Exception:
            return False

    def _install_ollama(self):
        """Install Ollama via Homebrew."""
        from .translate import TranslationManager

        if not TranslationManager.is_homebrew_installed():
            self._show_error("Homebrew is required. Install from brew.sh")
            return

        # Show progress
        if self._progress_indicator:
            self._progress_indicator.setHidden_(False)
            self._progress_indicator.startAnimation_(None)

        def do_install():
            success = TranslationManager.install_ollama(
                progress_callback=lambda msg: logger.debug(f"Ollama install: {msg}")
            )

            def update_ui():
                if self._progress_indicator:
                    self._progress_indicator.stopAnimation_(None)
                    self._progress_indicator.setHidden_(True)

                if success:
                    self._ollama_installed = True
                    self._show_step(WizardStep.TRANSLATION)
                else:
                    self._show_error("Installation failed. Try: brew install ollama")

            AppHelper.callAfter(update_ui)

        threading.Thread(target=do_install, daemon=True).start()

    def _start_ollama(self):
        """Start Ollama server."""
        from .translate import TranslationManager

        if self._progress_indicator:
            self._progress_indicator.setHidden_(False)
            self._progress_indicator.startAnimation_(None)

        def do_start():
            success, pid = TranslationManager.start_ollama_server()

            def update_ui():
                if self._progress_indicator:
                    self._progress_indicator.stopAnimation_(None)
                    self._progress_indicator.setHidden_(True)

                if success:
                    self._ollama_running = True
                    self._show_step(WizardStep.TRANSLATION)
                else:
                    self._show_error("Failed to start Ollama. Try: ollama serve")

            AppHelper.callAfter(update_ui)

        threading.Thread(target=do_start, daemon=True).start()

    def _show_error(self, message: str):
        """Show an error alert."""
        import rumps
        rumps.alert(title="Error", message=message)

    def _cancel_wizard(self):
        """Cancel and close wizard."""
        if self._window:
            self._window.close()
        if self._on_cancel:
            self._on_cancel()

    def _finish_wizard(self):
        """Finish wizard and save settings."""
        from .config import Config

        config = Config.load()
        config.default_provider = self._selected_provider
        config.setup_completed = True

        # Translation setup choices
        config.translation_enabled = bool(self._translation_enabled)
        config.translation_provider = self._translation_provider
        config.source_language = self._translation_source_language
        config.target_language = self._translation_target_language

        # Persist provider-specific translation model selections.
        config.translation_model = self._translation_models.get("ollama", config.translation_model)
        config.gemini_translate_model = self._translation_models.get(
            "gemini",
            config.gemini_translate_model,
        )
        config.openai_translate_model = self._translation_models.get(
            "openai",
            config.openai_translate_model,
        )
        config.anthropic_translate_model = self._translation_models.get(
            "anthropic",
            config.anthropic_translate_model,
        )

        if self._translation_enabled and self._translation_provider == "ollama" and self._ollama_running:
            config.ollama_auto_start = True

        config.save()

        if self._window:
            self._window.close()

        if self._on_complete:
            self._on_complete({
                "mode": self._transcription_mode,
                "provider": self._selected_provider,
                "api_key_set": self._transcription_mode == "cloud",
                "translation_enabled": self._translation_enabled,
                "translation_provider": self._translation_provider,
                "translation_model": self._translation_models.get(self._translation_provider, "default"),
                "translation_ready": (
                    (self._translation_provider != "ollama")
                    or self._ollama_running
                    or not self._translation_enabled
                ),
            })

    def _console_wizard(self):
        """Fallback console-based wizard."""
        print("\n=== WhisperHUD Setup ===\n")
        print("This wizard helps you configure WhisperHUD.")
        print("Please run the app with a GUI to complete setup.")
        print("\nFor manual setup:")
        print("1. Click the menu bar icon")
        print("2. Go to Provider to select Cloud or Local")
        print("3. For cloud: Go to API Keys and enter your key")
        print("4. For local: Select a local provider (Apple, Whisper, Parakeet)")


def show_setup_wizard(
    on_complete: Optional[Callable[[dict], None]] = None,
    on_cancel: Optional[Callable[[], None]] = None
) -> SetupWizard:
    """
    Show the setup wizard.

    Args:
        on_complete: Callback when wizard finishes
        on_cancel: Callback when wizard is cancelled

    Returns:
        SetupWizard instance
    """
    wizard = SetupWizard(on_complete, on_cancel)
    wizard.show()
    return wizard
