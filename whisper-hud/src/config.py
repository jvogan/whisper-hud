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
    default_provider: str = "openai"

    # Default model for each provider
    openai_model: str = "gpt-4o-transcribe"
    gemini_model: str = "gemini-2.0-flash-exp"

    # Hotkey (stored as key names)
    hotkey: List[str] = field(default_factory=lambda: ["cmd", "shift", "space"])

    # Behavior
    auto_paste: bool = True       # Automatically paste after transcription
    show_hud: bool = True         # Show floating HUD
    show_widget: bool = False     # Show floating widget button
    widget_size: str = "medium"   # Widget size: small, medium, large, xlarge
    auto_stop: bool = True        # Auto-stop recording after silence
    silence_duration: float = 1.5 # Seconds of silence before auto-stop
    play_sound: bool = False      # Play sound on completion
    restore_clipboard: bool = True  # Restore clipboard after paste

    # Stats
    total_transcriptions: int = 0
    total_cost: float = 0.0

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
        if provider == "openai":
            return self.openai_model
        elif provider == "gemini":
            return self.gemini_model
        return ""

    def set_provider_model(self, provider: str, model: str) -> None:
        """Set the model for a provider."""
        if provider == "openai":
            self.openai_model = model
        elif provider == "gemini":
            self.gemini_model = model
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
