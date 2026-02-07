"""Tests for configuration management."""

import tempfile
from pathlib import Path
from unittest.mock import patch


class TestConfig:
    """Tests for Config class."""

    def test_config_defaults(self):
        """Test that default config values are set correctly."""
        # Import here to avoid module-level import issues
        with patch('whisper_hud.config.CONFIG_FILE', Path('/tmp/test_config.json')):
            from whisper_hud.config import Config
            config = Config()

            assert config.default_provider == "apple"
            assert config.hotkey_mode == "push_to_talk"
            assert config.auto_paste is True
            assert config.show_hud is True
            assert config.translation_enabled is False
            assert config.source_language == "auto"
            assert config.target_language == "en"
            assert config.setup_completed is False

    def test_config_save_load(self):
        """Test saving and loading config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.json"

            with patch('whisper_hud.config.CONFIG_FILE', config_file):
                with patch('whisper_hud.config.CONFIG_DIR', Path(tmpdir)):
                    from whisper_hud.config import Config

                    # Create and modify config
                    config = Config()
                    config.default_provider = "gemini"
                    config.translation_enabled = True
                    config.save()

                    # Load and verify
                    loaded = Config.load()
                    assert loaded.default_provider == "gemini"
                    assert loaded.translation_enabled is True

    def test_history_management(self):
        """Test transcription history functions."""
        with patch('whisper_hud.config.CONFIG_FILE', Path('/tmp/test_config.json')):
            from whisper_hud.config import Config
            config = Config()
            config.history = []
            config.history_enabled = True

            # Add to history
            config.add_to_history("Hello world", provider="openai")
            assert len(config.history) == 1
            assert config.history[0]["text"] == "Hello world"
            assert config.history[0]["provider"] == "openai"

            # Clear history
            config.clear_history()
            assert len(config.history) == 0

    def test_provider_model_mapping(self):
        """Test provider to model mapping."""
        with patch('whisper_hud.config.CONFIG_FILE', Path('/tmp/test_config.json')):
            from whisper_hud.config import Config
            config = Config()

            assert config.get_provider_model("openai") == "gpt-4o-transcribe"
            assert config.get_provider_model("gemini") == "gemini-3-flash-preview"
            assert config.get_provider_model("apple") == "en-US"
            assert config.get_provider_model("unknown") == ""

    def test_load_preserves_existing_keychain_users_without_mode(self):
        """Existing config without storage mode should stay on keychain."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_file = config_dir / "config.json"
            config_file.write_text(
                '{"default_provider":"apple","translation_enabled":false}',
                encoding="utf-8",
            )

            with patch("whisper_hud.config.CONFIG_DIR", config_dir):
                with patch("whisper_hud.config.CONFIG_FILE", config_file):
                    from whisper_hud.config import Config
                    loaded = Config.load()

            assert loaded.credential_storage_mode == "keychain"

    def test_load_keeps_explicit_storage_mode(self):
        """Explicit storage mode should not be overwritten during migration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_file = config_dir / "config.json"
            config_file.write_text(
                '{"credential_storage_mode":"passphrase","source_language":"auto"}',
                encoding="utf-8",
            )

            with patch("whisper_hud.config.CONFIG_DIR", config_dir):
                with patch("whisper_hud.config.CONFIG_FILE", config_file):
                    from whisper_hud.config import Config
                    loaded = Config.load()

            assert loaded.credential_storage_mode == "passphrase"
