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
import subprocess
import platform
from typing import Callable, Optional
from enum import Enum

try:
    from AppKit import (
        NSWindow, NSView, NSColor, NSFont, NSBezierPath,
        NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
        NSBackingStoreBuffered, NSScreen, NSTextField,
        NSMakeRect, NSButton, NSApplication,
        NSSecureTextField, NSProgressIndicator,
        NSProgressIndicatorSpinningStyle,
        NSTextFieldCell, NSCenterTextAlignment,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSLeftTextAlignment
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
        self._transcription_mode = "cloud"  # "cloud" or "local"
        self._selected_provider = "gemini"  # Cloud: gemini/openai, Local: apple/whisper_local/parakeet
        self._api_key = ""
        self._setup_translation = False
        self._ollama_installed = False
        self._ollama_running = False
        self._model_downloaded = False

        # UI elements to track
        self._provider_buttons = {}
        self._mode_buttons = {}
        self._api_key_field = None
        self._progress_indicator = None
        self._status_label = None

    def show(self):
        """Show the setup wizard."""
        if not HAS_APPKIT:
            print("[SetupWizard] AppKit not available, using console mode")
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
        self._window.setBackgroundColor_(
            NSColor.colorWithCalibratedWhite_alpha_(0.12, 1.0)
        )

        self._content_view = self._window.contentView()

    def _clear_content(self):
        """Clear all subviews from content view."""
        if self._content_view:
            for subview in list(self._content_view.subviews()):
                subview.removeFromSuperview()

    def _show_step(self, step: WizardStep):
        """Show a specific wizard step."""
        self._current_step = step
        self._clear_content()

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
            "Both cloud and local options are available!",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 120),
            font_size=14,
            align=NSLeftTextAlignment
        )
        self._content_view.addSubview_(desc)

        # Quick info
        y -= 80
        info = self._create_label(
            "Cloud: Fast, accurate, requires API key and internet\n"
            "Local: Private, works offline, downloads a model (~800MB)",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 60),
            font_size=12,
            color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.6, 0.8, 1.0, 1.0)
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
            "How would you like to transcribe your speech?",
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
            "Private & Offline",
            "Runs on your Mac\nNo data leaves device\nOne-time model download",
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
            color=NSColor.colorWithCalibratedWhite_alpha_(0.6, 1.0)
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
        y -= 45
        btn_width = (self.WIDTH - 2 * self.PADDING - 20) / 2

        gemini_btn = self._create_provider_button(
            "Gemini",
            "Free tier available!",
            NSMakeRect(self.PADDING, y, btn_width, 40),
            selected=self._selected_provider == "gemini",
            action=lambda: self._select_provider("gemini")
        )
        self._content_view.addSubview_(gemini_btn)
        self._provider_buttons["gemini"] = gemini_btn

        openai_btn = self._create_provider_button(
            "OpenAI",
            "Pay per use",
            NSMakeRect(self.PADDING + btn_width + 20, y, btn_width, 40),
            selected=self._selected_provider == "openai",
            action=lambda: self._select_provider("openai")
        )
        self._content_view.addSubview_(openai_btn)
        self._provider_buttons["openai"] = openai_btn

        # API key input
        y -= 40
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
        self._content_view.addSubview_(self._api_key_field)

        # Help text with links
        y -= 60
        help_text = self._create_label(
            "Get your API key:\n"
            "  Gemini: aistudio.google.com/apikey (free tier!)\n"
            "  OpenAI: platform.openai.com/api-keys",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 50),
            font_size=12,
            color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.6, 0.8, 1.0, 1.0)
        )
        self._content_view.addSubview_(help_text)

        # Security note
        y -= 30
        security = self._create_label(
            "Your API key is stored securely in macOS Keychain.",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 24),
            font_size=11,
            color=NSColor.colorWithCalibratedWhite_alpha_(0.5, 1.0)
        )
        self._content_view.addSubview_(security)

        # Navigation
        self._add_navigation_buttons(
            back_title="Back",
            back_action=lambda: self._show_step(WizardStep.TRANSCRIPTION_MODE),
            next_title="Next",
            next_action=self._validate_and_continue_cloud
        )

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
            color=NSColor.colorWithCalibratedWhite_alpha_(0.5, 1.0)
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
        """Show translation setup step."""
        from .providers.translation.ollama import OllamaTranslateProvider

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
        y -= 60
        desc = self._create_label(
            "WhisperHUD can translate your transcriptions.\n"
            "This is optional - you can skip and set it up later.",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 50),
            font_size=14
        )
        self._content_view.addSubview_(desc)

        # Translation options
        y -= 50

        # If user has cloud API keys, suggest cloud translation
        from .keychain import get_api_key
        has_gemini = bool(get_api_key("gemini"))
        has_openai = bool(get_api_key("openai"))

        if has_gemini or has_openai:
            info = self._create_label(
                "Cloud translation is available with your existing API key!\n"
                "You can also use Ollama for local translation.",
                NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 40),
                font_size=13,
                color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.4, 0.9, 0.5, 1.0)
            )
        else:
            info = self._create_label(
                "Local translation requires Ollama.\n"
                "Cloud translation works with your transcription API key.",
                NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 40),
                font_size=13
            )
        self._content_view.addSubview_(info)

        # Check Ollama status
        y -= 40
        self._ollama_installed = OllamaTranslateProvider.is_ollama_installed()

        status_text = "Ollama: "
        if not self._ollama_installed:
            status_text += "Not installed"
            status_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.6, 0.4, 1.0)
        else:
            self._ollama_running = self._check_ollama_running()
            if self._ollama_running:
                status_text += "Running"
                status_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.4, 0.9, 0.5, 1.0)
            else:
                status_text += "Installed, not running"
                status_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.8, 0.4, 1.0)

        self._status_label = self._create_label(
            status_text,
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 24),
            font_size=14,
            color=status_color
        )
        self._content_view.addSubview_(self._status_label)

        # Action buttons for Ollama
        y -= 50
        if not self._ollama_installed:
            install_btn = self._create_button(
                "Install Ollama",
                NSMakeRect(self.PADDING, y, 150, 32),
                action=self._install_ollama
            )
            self._content_view.addSubview_(install_btn)
        elif not self._ollama_running:
            start_btn = self._create_button(
                "Start Ollama",
                NSMakeRect(self.PADDING, y, 150, 32),
                action=self._start_ollama
            )
            self._content_view.addSubview_(start_btn)

        # Progress indicator
        self._progress_indicator = NSProgressIndicator.alloc().initWithFrame_(
            NSMakeRect(self.PADDING + 170, y + 6, 20, 20)
        )
        self._progress_indicator.setStyle_(NSProgressIndicatorSpinningStyle)
        self._progress_indicator.setHidden_(True)
        self._content_view.addSubview_(self._progress_indicator)

        # Navigation
        self._add_navigation_buttons(
            back_title="Back",
            back_action=self._go_back_from_translation,
            next_title="Skip" if not (has_gemini or has_openai or self._ollama_running) else "Next",
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
        y -= 100
        mode_name = "Cloud" if self._transcription_mode == "cloud" else "Local"
        provider_names = {
            "gemini": "Google Gemini",
            "openai": "OpenAI",
            "apple": "Apple Speech",
            "whisper_local": "Whisper Local",
            "parakeet": "Parakeet"
        }
        provider_name = provider_names.get(self._selected_provider, self._selected_provider)

        summary = (
            f"You're all set to use WhisperHUD!\n\n"
            f"Mode: {mode_name}\n"
            f"Provider: {provider_name}\n"
            f"API Key: {'Configured' if self._api_key else 'N/A (local)'}"
        )
        summary_label = self._create_label(
            summary,
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 100),
            font_size=14,
            align=NSLeftTextAlignment
        )
        self._content_view.addSubview_(summary_label)

        # Usage tips
        y -= 110
        tips = self._create_label(
            "Quick Start:\n"
            "  Hold Command+Shift+Space to record\n"
            "  Release to transcribe and paste\n"
            "  Click the menu bar icon for settings\n\n"
            "You can re-run this wizard from the menu anytime.",
            NSMakeRect(self.PADDING, y, self.WIDTH - 2 * self.PADDING, 110),
            font_size=13,
            color=NSColor.colorWithCalibratedWhite_alpha_(0.8, 1.0),
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

        label.setTextColor_(color or NSColor.whiteColor())

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
        button.setTitle_(f"{title}\n{subtitle}")
        button.setBezelStyle_(1)

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
        button.setTitle_(f"{title}\n{subtitle}\n\n{description}")
        button.setBezelStyle_(1)

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
        next_title: str = "Next",
        next_action: Optional[Callable] = None
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

        # Next button
        if next_action:
            next_btn = self._create_button(
                next_title,
                NSMakeRect(self.WIDTH - self.PADDING - 90, y, 90, 32),
                action=next_action
            )
            self._content_view.addSubview_(next_btn)

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
        self._selected_provider = provider

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
        from .keychain import set_api_key

        if self._api_key_field:
            self._api_key = self._api_key_field.stringValue()

        if not self._api_key:
            self._show_error("Please enter an API key")
            return

        # Basic validation
        if self._selected_provider == "openai" and not self._api_key.startswith("sk-"):
            self._show_error("OpenAI keys should start with 'sk-'")
            return

        # Save the API key
        set_api_key(self._selected_provider, self._api_key)

        # Continue to translation step
        self._show_step(WizardStep.TRANSLATION)

    def _continue_from_local_setup(self):
        """Continue from local setup to translation."""
        # Just continue - model download will happen when user first uses it
        self._show_step(WizardStep.TRANSLATION)

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
                progress_callback=lambda msg: print(f"[Install] {msg}")
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

        if self._ollama_running:
            config.ollama_auto_start = True

        config.save()

        if self._window:
            self._window.close()

        if self._on_complete:
            self._on_complete({
                "mode": self._transcription_mode,
                "provider": self._selected_provider,
                "api_key_set": bool(self._api_key),
                "translation_ready": self._ollama_running
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
