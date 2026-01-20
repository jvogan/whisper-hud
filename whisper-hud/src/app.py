"""
Main menu bar application using rumps.

This is the heart of the app - coordinates all components:
- Menu bar icon with status indication
- Recording via hotkey
- Transcription via API
- Text insertion via paste
- Settings management
"""

import rumps
import threading
import time
from typing import Optional

from .recorder import AudioRecorder
from .transcribe import TranscriptionManager
from .hotkey import HotkeyListener, HotkeyCapture, format_hotkey_display, string_to_key
from .hud import create_hud, HUD
from .paste import insert_text, check_accessibility_permission
from .config import Config
from .keychain import set_api_key, get_api_key, get_configured_providers, mask_api_key
from .floating_widget import create_floating_widget, FloatingWidget


class WhisperHUDApp(rumps.App):
    """Menu bar application for voice-to-text transcription."""

    # Menu bar emoji states
    ICON_IDLE = "🎙️"
    ICON_RECORDING = "🔴"
    ICON_PROCESSING = "⏳"
    ICON_SUCCESS = "✅"
    ICON_ERROR = "❌"

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
        self.hud = create_hud()
        self.hud.set_enabled(self.config.show_hud)

        # Floating widget for click-to-record
        self.widget = create_floating_widget(
            on_record_start=self._widget_start_recording,
            on_record_stop=self._widget_stop_recording,
            size=self.config.widget_size
        )

        # State
        self._is_recording = False
        self._lock = threading.Lock()
        self._hotkey_capture: Optional[HotkeyCapture] = None
        self._is_capturing_hotkey = False

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

        # Show welcome notification on first run
        configured = get_configured_providers()
        if not configured:
            self._show_setup_reminder()

    def _build_menu(self):
        """Build the menu bar menu."""
        self.menu.clear()

        # Status header
        configured = get_configured_providers()
        if configured:
            status = f"Ready • {self.config.default_provider.title()}"
        else:
            status = "⚠️ No API key configured"

        self.menu.add(rumps.MenuItem(status, callback=None))
        self.menu.add(rumps.separator)

        # === Provider Selection ===
        provider_menu = rumps.MenuItem("Provider")
        providers = self.transcriber.get_available_providers()

        for p in providers:
            is_configured = p["configured"]
            is_default = p["id"] == self.config.default_provider
            status_icon = "✓" if is_configured else "○"
            prefix = "● " if is_default else "   "

            item = rumps.MenuItem(
                f"{prefix}{p['name']} {status_icon}",
                callback=lambda sender, pid=p["id"]: self._select_provider(pid)
            )
            provider_menu.add(item)

        self.menu.add(provider_menu)

        # === Model Selection ===
        model_menu = rumps.MenuItem("Model")
        current_provider = self.transcriber.get_provider(self.config.default_provider)
        if current_provider:
            current_model = current_provider.get_current_model()
            for model in current_provider.get_models():
                is_selected = model["id"] == current_model
                prefix = "● " if is_selected else "   "
                cost = f"${model['cost_per_minute']:.3f}/min"

                item = rumps.MenuItem(
                    f"{prefix}{model['name']} ({cost})",
                    callback=lambda sender, mid=model["id"]: self._select_model(mid)
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

        self.menu.add(settings_menu)

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

        # === Quit ===
        self.menu.add(rumps.MenuItem("Quit WhisperHUD", callback=self._quit))

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
                result = self.transcriber.transcribe(audio_bytes)

                if result.text:
                    # Show success
                    word_count = len(result.text.split())
                    self.title = self.ICON_SUCCESS

                    if self.config.show_hud:
                        self.hud.show_success(f"✓ {word_count} words")

                    # Auto-paste if enabled
                    if self.config.auto_paste:
                        time.sleep(0.1)  # Brief delay
                        insert_text(
                            result.text,
                            restore_clipboard=self.config.restore_clipboard
                        )
                else:
                    self.title = self.ICON_ERROR
                    if self.config.show_hud:
                        self.hud.show_error("No speech detected")

            except ValueError as e:
                # Configuration error (no API key)
                self.title = self.ICON_ERROR
                if self.config.show_hud:
                    self.hud.show_error(str(e)[:30])

            except Exception as e:
                print(f"Transcription error: {e}")
                self.title = self.ICON_ERROR
                if self.config.show_hud:
                    self.hud.show_error("API error")

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
        if self.widget:
            self.widget.hide()
        rumps.quit_application()


def run():
    """Entry point for the application."""
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
