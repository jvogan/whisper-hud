"""
Configuration management.

Stores user preferences in a JSON file.
API keys are stored separately in Keychain (see keychain.py).
"""

import json
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional, List

CONFIG_DIR = Path.home() / ".config" / "whisper-hud"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class Config:
    """Application configuration."""

    # Default transcription provider
    # Options: openai, gemini, apple, whisper_local, parakeet
    default_provider: str = "openai"

    # Default model for each transcription provider
    openai_model: str = "gpt-4o-transcribe"
    gemini_model: str = "gemini-2.0-flash-exp"
    apple_model: str = "en-US"
    whisper_local_model: str = "large-v3-turbo"
    parakeet_model: str = "parakeet-tdt-0.6b-v3"

    # Hotkey (stored as key names)
    hotkey: List[str] = field(default_factory=lambda: ["cmd", "shift", "space"])
    hotkey_mode: str = "push_to_talk"  # "push_to_talk" (hold) or "toggle" (press to start/stop)

    # Behavior
    auto_paste: bool = True       # Automatically paste after transcription
    show_hud: bool = True         # Show floating HUD
    show_widget: bool = False     # Show floating widget button
    widget_size: str = "medium"   # Widget size: small, medium, large, xlarge
    auto_stop: bool = True        # Auto-stop recording after silence
    silence_duration: float = 1.5 # Seconds of silence before auto-stop
    play_sound: bool = False      # Play sound on completion
    restore_clipboard: bool = True  # Restore clipboard after paste

    # Translation settings
    translation_enabled: bool = False
    translation_provider: str = "ollama"  # ollama, gemini, openai
    translation_model: str = "translategemma-4b"  # Ollama model: 4b, 12b, 27b
    gemini_translate_model: str = "gemini-2.5-flash"  # Gemini translation model
    openai_translate_model: str = "gpt-5-mini"  # OpenAI translation model
    target_language: str = "es"  # Default: Spanish
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

    @classmethod
    def load(cls) -> "Config":
        """Load config from disk or return defaults."""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    data = json.load(f)
                # Handle missing fields gracefully
                return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            except Exception as e:
                print(f"Failed to load config: {e}")
        return cls()

    def save(self) -> bool:
        """Save config to disk."""
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, "w") as f:
                json.dump(asdict(self), f, indent=2)
            return True
        except Exception as e:
            print(f"Failed to save config: {e}")
            return False

    def get_provider_model(self, provider: str) -> str:
        """Get the configured model for a provider."""
        model_map = {
            "openai": self.openai_model,
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
        elif provider == "gemini":
            self.gemini_model = model
        elif provider == "apple":
            self.apple_model = model
        elif provider == "whisper_local":
            self.whisper_local_model = model
        elif provider == "parakeet":
            self.parakeet_model = model
        self.save()

    def add_transcription_stats(self, cost: float) -> None:
        """Update transcription statistics."""
        self.total_transcriptions += 1
        self.total_cost += cost
        self.save()

    def reset_stats(self) -> None:
        """Reset transcription statistics."""
        self.total_transcriptions = 0
        self.total_cost = 0.0
        self.save()
