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

from .recorder import AudioRecorder
from .transcribe import TranscriptionManager
from .translate import TranslationManager
from .hotkey import HotkeyListener, HotkeyCapture, format_hotkey_display, string_to_key
from .hud import create_hud, HUD
from .paste import insert_text, check_accessibility_permission
from .config import Config
from .keychain import set_api_key, get_api_key, get_configured_providers, mask_api_key
from .floating_widget import create_floating_widget, FloatingWidget
from .streaming_panel import create_streaming_panel, StreamingPanel
from .setup_wizard import show_setup_wizard


class WhisperHUDApp(rumps.App):
    """Menu bar application for voice-to-text transcription."""

    # Menu bar emoji states
    ICON_IDLE = "🎙️"
    ICON_RECORDING = "🔴"
    ICON_PROCESSING = "⏳"
    ICON_SUCCESS = "✅"
    ICON_ERROR = "❌"
    ICON_DOWNLOADING = "⬇️"

    def __init__(self):
        super().__init__(
            "WhisperHUD",
            icon=None,
            title=self.ICON_IDLE,
            quit_button=None  # We'll add our own quit
        )

        # Components
        self.config = Config.load()
        self.recorder = AudioRecorder()
        self.transcriber = TranscriptionManager()
        self.translator = TranslationManager()
        self.hud = create_hud()
        self.hud.set_enabled(self.config.show_hud)

        # Streaming panel for live display
        self.streaming_panel = create_streaming_panel()
        self.streaming_panel.set_enabled(self.config.streaming_enabled)

        # Floating widget for click-to-record
        self.widget = create_floating_widget(
            on_record_start=self._widget_start_recording,
            on_record_stop=self._widget_stop_recording,
            size=self.config.widget_size
        )

        # State
        self._is_recording = False
        self._is_downloading = False
        self._lock = threading.Lock()
        self._hotkey_capture: Optional[HotkeyCapture] = None
        self._is_capturing_hotkey = False
        self._setup_wizard = None

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
        self.menu.clear()

        # Status header
        configured = get_configured_providers()
        provider_name = self._get_provider_display_name(self.config.default_provider)

        if self._is_downloading:
            status = "⬇️ Downloading model..."
        elif self.transcriber.get_provider(self.config.default_provider) and \
             self.transcriber.get_provider(self.config.default_provider).is_configured():
            status = f"Ready • {provider_name}"
        elif configured:
            status = f"Ready • {provider_name}"
        else:
            status = "⚠️ No provider configured"

        self.menu.add(rumps.MenuItem(status, callback=None))
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
            status_icon = "✓" if is_configured else "○"
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

            # Different status indicators for local providers
            if p.get("requires_download", False):
                if is_configured:
                    status_icon = "✓"
                else:
                    status_icon = "○"  # Needs download
            else:
                status_icon = "✓" if is_configured else "○"

            prefix = "● " if is_default else "   "

            # Add download hint for local providers that need it
            name = p["name"]
            if p.get("requires_download", False) and not is_configured:
                name = f"{name} [click to download]"

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

        settings_menu.add(rumps.separator)

        settings_menu.add(rumps.MenuItem(
            f"{'✓ ' if self.config.streaming_enabled else '   '}Live streaming display",
            callback=self._toggle_streaming
        ))

        self.menu.add(settings_menu)

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
        other_langs = sorted([k for k in languages.keys() if k not in common_langs],
                            key=lambda x: languages[x])

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

        # === Setup Wizard ===
        self.menu.add(rumps.MenuItem("Run Setup Wizard...", callback=self._run_setup_wizard))

        self.menu.add(rumps.separator)

        # === Quit ===
        self.menu.add(rumps.MenuItem("Quit WhisperHUD", callback=self._quit))

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
        self.title = self.ICON_DOWNLOADING
        self._build_menu()

        rumps.notification(
            "WhisperHUD",
            "Downloading Model",
            "This will run in the background. You'll be notified when complete."
        )

        def do_download():
            def progress_callback(msg, pct):
                print(f"[Download] {msg} ({pct:.0f}%)")

            success = self.transcriber.download_model(provider_id, progress_callback)

            self._is_downloading = False
            self.title = self.ICON_IDLE

            if success:
                rumps.notification(
                    "WhisperHUD",
                    "Download Complete",
                    f"Model is ready! Switching to {self._get_provider_display_name(provider_id)}."
                )
                self._select_provider(provider_id)
            else:
                rumps.notification(
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
        with self._lock:
            if self._is_recording:
                return
            self._is_recording = True

        self.title = self.ICON_RECORDING

        if self.config.show_hud:
            self.hud.show_recording()

        if self.widget:
            self.widget.set_recording()

        # Configure silence detection
        if self.config.auto_stop:
            self.recorder.set_silence_settings(
                enabled=True,
                silence_duration=self.config.silence_duration
            )
            self.recorder.start(on_silence=self._on_silence_detected)
        else:
            self.recorder.start()

    def _on_silence_detected(self):
        """Called when silence is detected after speech."""
        # Auto-stop recording
        self._stop_recording()

    def _stop_recording(self):
        """Called when hotkey is released."""
        with self._lock:
            if not self._is_recording:
                return
            self._is_recording = False

        self.title = self.ICON_PROCESSING

        if self.config.show_hud:
            self.hud.show_processing()

        if self.widget:
            self.widget.set_processing()

        # Get audio data
        audio_bytes = self.recorder.stop()

        if not audio_bytes or len(audio_bytes) < 1000:  # Too short
            self.hud.hide()
            self.title = self.ICON_IDLE
            if self.widget:
                self.widget.set_idle()
            return

        # Transcribe in background thread
        def do_transcribe():
            try:
                # Check if streaming is enabled and provider supports it
                provider = self.transcriber.get_provider(self.config.default_provider)
                use_streaming = (
                    self.config.streaming_enabled and
                    provider and
                    provider.supports_streaming()
                )

                if use_streaming:
                    # Show streaming panel
                    self.streaming_panel.show_transcribing(
                        show_translation=self.config.translation_enabled
                    )

                    # Transcribe with streaming
                    result = provider.transcribe_streaming(
                        audio_bytes,
                        on_chunk=self.streaming_panel.update_transcription
                    )
                    # Update stats manually since we bypassed TranscriptionManager
                    self.config.add_transcription_stats(result.cost_estimate)
                else:
                    # Regular non-streaming transcription
                    result = self.transcriber.transcribe(audio_bytes)

                if result.text:
                    final_text = result.text

                    # Translate if enabled
                    if self.config.translation_enabled:
                        try:
                            if self.config.show_hud:
                                self.hud.show_processing("Translating...")

                            if use_streaming:
                                self.streaming_panel.show_translating()

                            # Check if translation provider supports streaming
                            use_translation_streaming = (
                                use_streaming and
                                self.translator.supports_streaming()
                            )

                            if use_translation_streaming:
                                translation = self.translator.translate_streaming(
                                    text=result.text,
                                    on_chunk=self.streaming_panel.update_translation,
                                    source_lang=result.language or "en",
                                    target_lang=self.config.target_language
                                )
                            else:
                                translation = self.translator.translate(
                                    text=result.text,
                                    source_lang=result.language or "en",
                                    target_lang=self.config.target_language
                                )
                                if use_streaming:
                                    self.streaming_panel.update_translation(translation.text)

                            final_text = translation.text

                            # Get target language name for display
                            lang_name = self.translator.get_supported_languages().get(
                                self.config.target_language,
                                self.config.target_language
                            )
                            word_count = len(final_text.split())
                            self.title = self.ICON_SUCCESS

                            if self.config.show_hud:
                                self.hud.show_success(f"✓ {word_count} words → {lang_name}")

                        except Exception as e:
                            # Translation failed, use original text
                            print(f"Translation failed: {e}")
                            final_text = result.text
                            word_count = len(final_text.split())
                            self.title = self.ICON_SUCCESS
                            if self.config.show_hud:
                                self.hud.show_success(f"✓ {word_count} words (translation failed)")
                    else:
                        # No translation, just show word count
                        word_count = len(final_text.split())
                        self.title = self.ICON_SUCCESS
                        if self.config.show_hud:
                            self.hud.show_success(f"✓ {word_count} words")

                    # Show completion on streaming panel
                    if use_streaming:
                        self.streaming_panel.show_complete()

                    # Auto-paste if enabled
                    if self.config.auto_paste:
                        time.sleep(0.1)  # Brief delay
                        insert_text(
                            final_text,
                            restore_clipboard=self.config.restore_clipboard
                        )
                else:
                    self.title = self.ICON_ERROR
                    if self.config.show_hud:
                        self.hud.show_error("No speech detected")
                    if use_streaming:
                        self.streaming_panel.hide()

            except ValueError as e:
                # Configuration error (no API key)
                self.title = self.ICON_ERROR
                if self.config.show_hud:
                    self.hud.show_error(str(e)[:30])
                if self.config.streaming_enabled:
                    self.streaming_panel.hide()

            except Exception as e:
                print(f"Transcription error: {e}")
                self.title = self.ICON_ERROR
                if self.config.show_hud:
                    self.hud.show_error("API error")
                if self.config.streaming_enabled:
                    self.streaming_panel.hide()

            finally:
                # Reset icon after a brief delay
                time.sleep(1.5)
                self.title = self.ICON_IDLE
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
            if key.startswith("sk-"):
                set_api_key("openai", key)
                self._build_menu()
                rumps.notification(
                    "WhisperHUD",
                    "API Key Saved",
                    "OpenAI key has been saved securely."
                )
            else:
                rumps.alert(
                    title="Invalid Key",
                    message="OpenAI API keys should start with 'sk-'"
                )

    def _set_gemini_key(self, _):
        """Prompt for Gemini API key using AppleScript for proper paste support."""
        current = get_api_key("gemini") or ""
        key = self._applescript_input_dialog(
            "Gemini API Key",
            "Enter your Google AI API key.\n\nGet your key at: aistudio.google.com/apikey",
            current
        )

        if key:
            set_api_key("gemini", key)
            self._build_menu()
            rumps.notification(
                "WhisperHUD",
                "API Key Saved",
                "Gemini key has been saved securely."
            )

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
            print(f"Dialog error: {e}")

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
        rumps.notification(
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
                rumps.notification(
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
            rumps.notification(
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

        rumps.notification(
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
        rumps.notification(
            "WhisperHUD",
            "Mode Changed",
            f"Recording mode: {mode_name}"
        )

        self._build_menu()

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
        rumps.notification(
            "WhisperHUD",
            "Downloading Translation Model",
            "This will run in the background. You'll be notified when complete."
        )

        # Download in background thread
        def do_download():
            def progress_callback(msg):
                print(f"Download: {msg}")

            success = self.translator.download_model(progress_callback)

            if success:
                rumps.notification(
                    "WhisperHUD",
                    "Download Complete",
                    "Translation model is ready to use!"
                )
            else:
                rumps.notification(
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

        rumps.notification(
            "WhisperHUD",
            "Installing Ollama",
            "This will run in the background..."
        )

        def do_install():
            success = self.translator.install_ollama(
                progress_callback=lambda msg: print(f"[Ollama Install] {msg}")
            )

            if success:
                rumps.notification(
                    "WhisperHUD",
                    "Installation Complete",
                    "Ollama is now installed. Starting server..."
                )
                # Auto-start the server
                self._auto_start_ollama()
            else:
                rumps.notification(
                    "WhisperHUD",
                    "Installation Failed",
                    "Try running: brew install ollama"
                )

            self._build_menu()

        threading.Thread(target=do_install, daemon=True).start()

    def _start_ollama(self, sender):
        """Start the Ollama server."""
        rumps.notification(
            "WhisperHUD",
            "Starting Ollama",
            "Starting Ollama server..."
        )

        def do_start():
            success, pid = self.translator.start_ollama_server()

            if success:
                rumps.notification(
                    "WhisperHUD",
                    "Ollama Started",
                    "Ollama server is now running."
                )
            else:
                rumps.notification(
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
                    print("Ollama auto-started successfully")
                    self._build_menu()

            threading.Thread(target=do_start, daemon=True).start()

    def _show_setup_wizard(self):
        """Show the setup wizard for first-time setup."""
        def on_complete(result):
            print(f"Setup wizard completed: {result}")
            self._build_menu()
            rumps.notification(
                "WhisperHUD",
                "Setup Complete",
                "You're ready to start transcribing! Hold ⌘⇧Space to record."
            )

        def on_cancel():
            print("Setup wizard cancelled")

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

    def _show_setup_reminder(self):
        """Show reminder to set up API keys."""
        rumps.notification(
            "WhisperHUD",
            "Welcome!",
            "Click the menu bar icon to add your API key and start transcribing."
        )

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
        rumps.alert(
            title="Accessibility Permission Required",
            message=(
                "WhisperHUD needs Accessibility access to:\n"
                "• Detect global hotkeys\n"
                "• Paste transcribed text\n\n"
                "Please grant access in:\n"
                "System Settings → Privacy & Security → Accessibility\n\n"
                "Then restart WhisperHUD."
            )
        )

    app = WhisperHUDApp()
    app.run()
