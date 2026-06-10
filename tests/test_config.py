"""Tests for configuration management."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch


class TestConfig:
    """Tests for Config class."""

    def test_config_defaults(self):
        """Test that default config values are set correctly."""
        # Import here to avoid module-level import issues
        with patch("whisper_hud.config.CONFIG_FILE", Path("/tmp/test_config.json")):
            from whisper_hud.config import Config

            config = Config()

            assert config.default_provider == "apple"
            assert config.openai_model == "gpt-4o-mini-transcribe"
            assert config.openai_realtime_model == "gpt-realtime-whisper"
            assert config.gemini_model == "gemini-3.1-flash-lite"
            assert config.hotkey_mode == "push_to_talk"
            assert config.auto_paste is True
            assert config.show_hud is True
            assert config.translation_enabled is False
            assert config.gemini_translate_model == "gemini-3.1-flash-lite"
            assert config.openai_translate_model == "gpt-5.4-mini"
            assert config.anthropic_translate_model == "claude-sonnet-4-6"
            assert config.source_language == "auto"
            assert config.target_language == "en"
            assert config.setup_completed is False

    def test_config_save_load(self):
        """Test saving and loading config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.json"

            with patch("whisper_hud.config.CONFIG_FILE", config_file):
                with patch("whisper_hud.config.CONFIG_DIR", Path(tmpdir)):
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

    def test_load_valid_json(self):
        """Valid config JSON should load normally."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_file = config_dir / "config.json"
            config_file.write_text(
                json.dumps({"default_provider": "gemini", "translation_enabled": True}),
                encoding="utf-8",
            )

            with patch("whisper_hud.config.CONFIG_DIR", config_dir):
                with patch("whisper_hud.config.CONFIG_FILE", config_file):
                    from whisper_hud.config import Config

                    loaded = Config.load()

            assert loaded.default_provider == "gemini"
            assert loaded.translation_enabled is True

    def test_load_missing_file_returns_defaults(self):
        """Missing config file should fall back to defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_file = config_dir / "config.json"

            with patch("whisper_hud.config.CONFIG_DIR", config_dir):
                with patch("whisper_hud.config.CONFIG_FILE", config_file):
                    from whisper_hud.config import Config

                    loaded = Config.load()

            assert loaded.default_provider == "apple"
            assert config_file.exists() is False

    def test_load_empty_file_resets_to_defaults_and_backs_up_file(self):
        """Empty config file should be backed up and replaced with defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_file = config_dir / "config.json"
            config_file.write_text("", encoding="utf-8")

            with patch("whisper_hud.config.CONFIG_DIR", config_dir):
                with patch("whisper_hud.config.CONFIG_FILE", config_file):
                    from whisper_hud.config import Config

                    loaded = Config.load()

            backups = sorted(config_dir.glob("config.json.bak.*"))
            assert loaded.default_provider == "apple"
            assert config_file.exists() is False
            assert len(backups) == 1
            assert backups[0].read_text(encoding="utf-8") == ""

    def test_load_corrupted_json_resets_to_defaults_and_preserves_existing_backup(self):
        """Corrupted config JSON should be backed up without overwriting an existing backup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_file = config_dir / "config.json"
            config_file.write_text('{"default_provider":', encoding="utf-8")

            existing_backup = config_dir / "config.json.bak.20260315010101"
            existing_backup.write_text("existing-backup", encoding="utf-8")

            with patch("whisper_hud.config.CONFIG_DIR", config_dir):
                with patch("whisper_hud.config.CONFIG_FILE", config_file):
                    with patch("whisper_hud.config.datetime") as mock_datetime:
                        from whisper_hud.config import Config

                        mock_datetime.now.return_value.strftime.return_value = "20260315010101"
                        loaded = Config.load()

            backups = sorted(config_dir.glob("config.json.bak.*"))
            assert loaded.default_provider == "apple"
            assert config_file.exists() is False
            assert existing_backup.read_text(encoding="utf-8") == "existing-backup"
            assert len(backups) == 2
            assert any(
                backup.name == "config.json.bak.20260315010101.1"
                and backup.read_text(encoding="utf-8") == '{"default_provider":'
                for backup in backups
            )

    def test_history_management(self):
        """Test transcription history functions."""
        with patch("whisper_hud.config.CONFIG_FILE", Path("/tmp/test_config.json")):
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

    def test_add_to_history_rolls_back_when_save_fails(self):
        """History writes should not remain in memory if persistence fails."""
        with patch("whisper_hud.config.CONFIG_FILE", Path("/tmp/test_config.json")):
            from whisper_hud.config import Config

            config = Config()
            config.history_enabled = True
            config.history = [{"text": "saved", "timestamp": 1, "provider": "openai", "translated": False}]
            original_history = [item.copy() for item in config.history]

            with patch.object(Config, "save", return_value=False):
                assert config.add_to_history("new item", provider="gemini") is False

            assert config.history == original_history

    def test_clear_history_rolls_back_when_save_fails(self):
        """Clearing history should fail closed when the config cannot be written."""
        with patch("whisper_hud.config.CONFIG_FILE", Path("/tmp/test_config.json")):
            from whisper_hud.config import Config

            config = Config()
            config.history = [{"text": "saved", "timestamp": 1, "provider": "openai", "translated": False}]
            original_history = [item.copy() for item in config.history]

            with patch.object(Config, "save", return_value=False):
                assert config.clear_history() is False

            assert config.history == original_history

    def test_history_max_items_default_is_fifty(self):
        """The default retention cap should be 50 entries."""
        with patch("whisper_hud.config.CONFIG_FILE", Path("/tmp/test_config.json")):
            from whisper_hud.config import Config

            assert Config().history_max_items == 50

    def test_add_to_history_stores_new_metadata_tags(self):
        """New kwargs (source/model/duration/mode) should be persisted on the entry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.json"
            with patch("whisper_hud.config.CONFIG_FILE", config_file):
                with patch("whisper_hud.config.CONFIG_DIR", Path(tmpdir)):
                    from whisper_hud.config import Config

                    config = Config()
                    config.history = []
                    config.history_enabled = True

                    assert config.add_to_history(
                        "Hello from a file",
                        provider="apple",
                        source="file",
                        model="en-US",
                        duration_seconds=12.5,
                        mode="email",
                    )
                    entry = config.history[0]
                    assert entry["text"] == "Hello from a file"
                    assert entry["source"] == "file"
                    assert entry["model"] == "en-US"
                    assert entry["duration_seconds"] == 12.5
                    assert entry["mode"] == "email"

    def test_add_to_history_defaults_source_to_mic(self):
        """Omitting source should default to a 'mic' tag (back-compat default)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.json"
            with patch("whisper_hud.config.CONFIG_FILE", config_file):
                with patch("whisper_hud.config.CONFIG_DIR", Path(tmpdir)):
                    from whisper_hud.config import Config

                    config = Config()
                    config.history = []
                    config.history_enabled = True
                    config.add_to_history("spoken text", provider="openai")
                    entry = config.history[0]
                    assert entry["source"] == "mic"
                    # Optional tags omitted when not supplied.
                    assert "model" not in entry
                    assert "duration_seconds" not in entry
                    assert "mode" not in entry

    def test_get_history_preserves_old_entries_without_new_keys(self):
        """Old entries lacking the new metadata keys must keep working on read."""
        with patch("whisper_hud.config.CONFIG_FILE", Path("/tmp/test_config.json")):
            from whisper_hud.config import Config

            config = Config()
            # Legacy entry shape (pre-upgrade): no source/model/duration/mode.
            config.history = [{"text": "legacy", "timestamp": 1, "provider": "openai", "translated": False}]
            items = config.get_history(limit=10)
            assert items[0]["text"] == "legacy"
            assert items[0].get("source") is None  # tolerated via .get()

    def test_get_all_history_returns_every_entry(self):
        """get_all_history should return the full retained list."""
        with patch("whisper_hud.config.CONFIG_FILE", Path("/tmp/test_config.json")):
            from whisper_hud.config import Config

            config = Config()
            config.history = [{"text": f"item {i}", "timestamp": i} for i in range(5)]
            assert len(config.get_all_history()) == 5

    def test_set_history_max_items_trims_and_persists(self):
        """Lowering the cap should trim stored history and persist immediately."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.json"
            with patch("whisper_hud.config.CONFIG_FILE", config_file):
                with patch("whisper_hud.config.CONFIG_DIR", Path(tmpdir)):
                    from whisper_hud.config import Config

                    config = Config()
                    config.history = [{"text": f"item {i}", "timestamp": i} for i in range(10)]
                    assert config.set_history_max_items(3) is True
                    assert config.history_max_items == 3
                    assert len(config.history) == 3

                    reloaded = Config.load()
                    assert reloaded.history_max_items == 3

    def test_set_history_max_items_rejects_invalid(self):
        """Non-positive or non-numeric sizes should be rejected without changes."""
        with patch("whisper_hud.config.CONFIG_FILE", Path("/tmp/test_config.json")):
            from whisper_hud.config import Config

            config = Config()
            original = config.history_max_items
            assert config.set_history_max_items(0) is False
            assert config.set_history_max_items("nope") is False
            assert config.history_max_items == original

    def test_set_history_max_items_rolls_back_when_save_fails(self):
        """A failed save should leave the cap and history unchanged."""
        with patch("whisper_hud.config.CONFIG_FILE", Path("/tmp/test_config.json")):
            from whisper_hud.config import Config

            config = Config()
            config.history_max_items = 50
            config.history = [{"text": f"item {i}", "timestamp": i} for i in range(10)]
            original_history = [item.copy() for item in config.history]

            with patch.object(Config, "save", return_value=False):
                assert config.set_history_max_items(2) is False

            assert config.history_max_items == 50
            assert config.history == original_history

    def test_private_mode_resets_history_and_stats(self):
        """Enabling private mode should clear retained history and stats."""
        with patch("whisper_hud.config.CONFIG_FILE", Path("/tmp/test_config.json")):
            from whisper_hud.config import Config

            config = Config()
            config.history_enabled = True
            config.history = [{"text": "saved", "timestamp": 1}]
            config.total_transcriptions = 12
            config.total_cost = 4.5

            assert config.enable_private_mode() is True

            assert config.private_mode is True
            assert config.history_enabled is False
            assert config.history == []
            assert config.total_transcriptions == 0
            assert config.total_cost == 0.0

    def test_enable_private_mode_rolls_back_when_save_fails(self):
        """Private mode should not partially clear retained data when save fails."""
        with patch("whisper_hud.config.CONFIG_FILE", Path("/tmp/test_config.json")):
            from whisper_hud.config import Config

            config = Config()
            config.private_mode = False
            config.history_enabled = True
            config.history = [{"text": "saved", "timestamp": 1}]
            config.total_transcriptions = 12
            config.total_cost = 4.5

            with patch.object(Config, "save", return_value=False):
                assert config.enable_private_mode() is False

            assert config.private_mode is False
            assert config.history_enabled is True
            assert config.history == [{"text": "saved", "timestamp": 1}]
            assert config.total_transcriptions == 12
            assert config.total_cost == 4.5

    def test_disable_private_mode_rolls_back_when_save_fails(self):
        """Failed private-mode exits should keep the privacy boundary active."""
        with patch("whisper_hud.config.CONFIG_FILE", Path("/tmp/test_config.json")):
            from whisper_hud.config import Config

            config = Config()
            config.private_mode = True

            with patch.object(Config, "save", return_value=False):
                assert config.disable_private_mode() is False

            assert config.private_mode is True

    def test_add_transcription_stats_skips_private_mode(self):
        """Private mode should not retain new transcription activity stats."""
        with patch("whisper_hud.config.CONFIG_FILE", Path("/tmp/test_config.json")):
            from whisper_hud.config import Config

            config = Config()
            config.private_mode = True
            config.total_transcriptions = 5
            config.total_cost = 1.5

            assert config.add_transcription_stats(0.25) is False

            assert config.total_transcriptions == 5
            assert config.total_cost == 1.5

    def test_provider_model_mapping(self):
        """Test provider to model mapping."""
        with patch("whisper_hud.config.CONFIG_FILE", Path("/tmp/test_config.json")):
            from whisper_hud.config import Config

            config = Config()

            assert config.get_provider_model("openai") == "gpt-4o-mini-transcribe"
            assert config.get_provider_model("openai_realtime") == "gpt-realtime-whisper"
            assert config.get_provider_model("gemini") == "gemini-3.1-flash-lite"
            assert config.get_provider_model("apple") == "en-US"
            assert config.get_provider_model("unknown") == ""

    def test_load_migrates_stale_model_ids(self):
        """Known removed or outdated model IDs should normalize during config load."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_file = config_dir / "config.json"
            config_file.write_text(
                json.dumps(
                    {
                        "openai_translate_model": "gpt-5-mini",
                        "openai_realtime_model": "gpt-4o-transcribe-latest",
                        "anthropic_translate_model": "claude-sonnet-4-5",
                        "gemini_model": "gemini-3.1-flash-lite-preview",
                        "gemini_translate_model": "gemini-3.1-flash-lite-preview",
                    }
                ),
                encoding="utf-8",
            )

            with patch("whisper_hud.config.CONFIG_DIR", config_dir):
                with patch("whisper_hud.config.CONFIG_FILE", config_file):
                    from whisper_hud.config import Config

                    loaded = Config.load()

            assert loaded.openai_translate_model == "gpt-5.4-mini"
            assert loaded.openai_realtime_model == "gpt-realtime-whisper"
            assert loaded.anthropic_translate_model == "claude-sonnet-4-6"
            assert loaded.gemini_model == "gemini-3.1-flash-lite"
            assert loaded.gemini_translate_model == "gemini-3.1-flash-lite"

    def test_load_migrates_shutdown_gemini_pro_and_preserves_new_audio_model(self):
        """Shut-down Gemini IDs should normalize; verified current IDs must be preserved verbatim."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_file = config_dir / "config.json"
            config_file.write_text(
                json.dumps(
                    {
                        # "Gemini 3 Pro Preview" is marked shut down in the docs; alias -> 3.1 Pro Preview.
                        "gemini_model": "gemini-3-pro-preview",
                        # Realtime latest-only alias should resolve to the streaming STT default.
                        "openai_realtime_model": "gpt-4o-transcribe-latest",
                    }
                ),
                encoding="utf-8",
            )

            with patch("whisper_hud.config.CONFIG_DIR", config_dir):
                with patch("whisper_hud.config.CONFIG_FILE", config_file):
                    from whisper_hud.config import Config

                    loaded = Config.load()

            assert loaded.gemini_model == "gemini-3.1-pro-preview"
            assert loaded.openai_realtime_model == "gpt-realtime-whisper"

    def test_load_preserves_current_gemini_3_5_flash_model_id(self):
        """A config already on a verified current ID must not be migrated away."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_file = config_dir / "config.json"
            config_file.write_text(
                json.dumps({"gemini_model": "gemini-3.5-flash"}),
                encoding="utf-8",
            )

            with patch("whisper_hud.config.CONFIG_DIR", config_dir):
                with patch("whisper_hud.config.CONFIG_FILE", config_file):
                    from whisper_hud.config import Config

                    loaded = Config.load()

            assert loaded.gemini_model == "gemini-3.5-flash"

    def test_set_provider_model_supports_openai_realtime(self):
        """Realtime provider model selection should persist like other providers."""
        with patch("whisper_hud.config.CONFIG_FILE", Path("/tmp/test_config.json")):
            from whisper_hud.config import Config

            config = Config()
            config.set_provider_model("openai_realtime", "gpt-4o-transcribe")

            assert config.openai_realtime_model == "gpt-4o-transcribe"

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

    def test_enable_history_encryption_migrates_existing_entries(self):
        """Enabling history encryption should re-encrypt existing plaintext entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_file = config_dir / "config.json"

            with patch("whisper_hud.config.CONFIG_DIR", config_dir):
                with patch("whisper_hud.config.CONFIG_FILE", config_file):
                    from whisper_hud.config import Config

                    config = Config()
                    config.history_enabled = True
                    config.history = [
                        {
                            "text": "plain",
                            "original_text": "source",
                            "timestamp": 1,
                            "provider": "openai",
                            "translated": True,
                        },
                        {
                            "text": "ENC:already",
                            "timestamp": 2,
                            "provider": "gemini",
                            "translated": False,
                            "encrypted": True,
                        },
                    ]

                    with patch("whisper_hud.encryption.is_cryptography_installed", return_value=True):
                        with patch("whisper_hud.encryption.get_or_create_key", return_value=b"key"):
                            with patch(
                                "whisper_hud.encryption.encrypt_text",
                                side_effect=lambda value: f"ENC:{value}" if value else None,
                            ):
                                assert config.enable_history_encryption() is True

                    assert config.history_encrypted is True
                    assert config.history[0]["text"] == "ENC:plain"
                    assert config.history[0]["original_text"] == "ENC:source"
                    assert config.history[0]["encrypted"] is True
                    assert config.history[1]["text"] == "ENC:already"
                    assert config.history[1]["encrypted"] is True

    def test_enable_history_encryption_leaves_history_unchanged_on_failure(self):
        """Failed encryption migration should not partially rewrite saved history."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_file = config_dir / "config.json"

            with patch("whisper_hud.config.CONFIG_DIR", config_dir):
                with patch("whisper_hud.config.CONFIG_FILE", config_file):
                    from whisper_hud.config import Config

                    config = Config()
                    config.history_enabled = True
                    config.history = [
                        {
                            "text": "plain",
                            "timestamp": 1,
                            "provider": "openai",
                            "translated": False,
                        }
                    ]
                    original_history = [item.copy() for item in config.history]

                    with patch("whisper_hud.encryption.is_cryptography_installed", return_value=True):
                        with patch("whisper_hud.encryption.get_or_create_key", return_value=b"key"):
                            with patch("whisper_hud.encryption.encrypt_text", return_value=None):
                                assert config.enable_history_encryption() is False

                    assert config.history_encrypted is False
                    assert config.history == original_history

    def test_enable_history_encryption_rolls_back_when_save_fails(self):
        """Config writes must not fail open after history has been migrated in memory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_file = config_dir / "config.json"

            with patch("whisper_hud.config.CONFIG_DIR", config_dir):
                with patch("whisper_hud.config.CONFIG_FILE", config_file):
                    from whisper_hud.config import Config

                    config = Config()
                    config.history_enabled = True
                    config.history = [
                        {
                            "text": "plain",
                            "timestamp": 1,
                            "provider": "openai",
                            "translated": False,
                        }
                    ]
                    original_history = [item.copy() for item in config.history]

                    with patch("whisper_hud.encryption.is_cryptography_installed", return_value=True):
                        with patch("whisper_hud.encryption.get_or_create_key", return_value=b"key"):
                            with patch("whisper_hud.encryption.encrypt_text", side_effect=lambda value: f"ENC:{value}"):
                                with patch.object(Config, "save", return_value=False):
                                    assert config.enable_history_encryption() is False

                    assert config.history_encrypted is False
                    assert config.history == original_history

    def test_merge_imported_config_clears_history_for_private_mode(self):
        """Importing private mode should clear existing saved history."""
        with patch("whisper_hud.config.CONFIG_FILE", Path("/tmp/test_config.json")):
            from whisper_hud.config import Config

            current = Config()
            current.history = [{"text": "saved", "timestamp": 1}]
            current.total_transcriptions = 12
            current.total_cost = 4.5

            imported = Config(private_mode=True, history_enabled=True)
            merged = current.merge_imported_config(imported)

            assert merged.private_mode is True
            assert merged.history == []
            assert merged.history_enabled is False
            assert merged.total_transcriptions == 12
            assert merged.total_cost == 4.5

    def test_merge_imported_config_preserves_history_when_not_private(self):
        """Importing regular settings should preserve existing history and stats."""
        with patch("whisper_hud.config.CONFIG_FILE", Path("/tmp/test_config.json")):
            from whisper_hud.config import Config

            current = Config()
            current.history = [{"text": "saved", "timestamp": 1}]
            current.total_transcriptions = 7
            current.total_cost = 1.25

            imported = Config(private_mode=False, history_enabled=True)
            merged = current.merge_imported_config(imported)

            assert merged.history == current.history
            assert merged.history_enabled is True
            assert merged.total_transcriptions == 7
            assert merged.total_cost == 1.25


class TestDictationIntelligenceConfig:
    """Tests for the dictation-intelligence config fields."""

    def test_defaults(self):
        """New dictation fields should default to safe off/empty values."""
        with patch("whisper_hud.config.CONFIG_FILE", Path("/tmp/test_config.json")):
            from whisper_hud.config import Config

            config = Config()

            assert config.custom_vocabulary == []
            assert config.text_replacements == []
            assert config.voice_commands_enabled is False
            assert config.custom_voice_commands == []
            assert config.dictation_modes_enabled is False
            assert config.dictation_modes == []
            assert config.llm_cleanup_enabled is False
            assert config.llm_cleanup_model == ""
            assert config.llm_cleanup_timeout_seconds == 10.0

    def test_defaults_are_independent_instances(self):
        """Mutable list defaults must not be shared across Config instances."""
        with patch("whisper_hud.config.CONFIG_FILE", Path("/tmp/test_config.json")):
            from whisper_hud.config import Config

            a = Config()
            b = Config()
            a.custom_vocabulary.append("alpha")
            a.text_replacements.append({"pattern": "x", "replacement": "y"})

            assert b.custom_vocabulary == []
            assert b.text_replacements == []

    def test_persistence_round_trip(self):
        """Dictation fields should survive a save/load cycle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.json"
            with patch("whisper_hud.config.CONFIG_FILE", config_file):
                with patch("whisper_hud.config.CONFIG_DIR", Path(tmpdir)):
                    from whisper_hud.config import Config

                    config = Config()
                    config.custom_vocabulary = ["Kubernetes", "Anthropic"]
                    config.text_replacements = [{"pattern": "teh", "replacement": "the"}]
                    config.voice_commands_enabled = True
                    config.custom_voice_commands = [
                        {"id": "smiley", "action": "insert", "phrases": ["smiley face"], "payload": ":)"}
                    ]
                    config.dictation_modes_enabled = True
                    config.dictation_modes = [{"id": "term", "app_patterns": ["*term*"]}]
                    config.llm_cleanup_enabled = True
                    config.llm_cleanup_model = "qwen3:1.7b"
                    config.llm_cleanup_timeout_seconds = 7.5
                    config.save()

                    loaded = Config.load()
                    assert loaded.custom_vocabulary == ["Kubernetes", "Anthropic"]
                    assert loaded.text_replacements == [{"pattern": "teh", "replacement": "the"}]
                    assert loaded.voice_commands_enabled is True
                    assert loaded.custom_voice_commands[0]["payload"] == ":)"
                    assert loaded.dictation_modes_enabled is True
                    assert loaded.dictation_modes[0]["id"] == "term"
                    assert loaded.llm_cleanup_enabled is True
                    assert loaded.llm_cleanup_model == "qwen3:1.7b"
                    assert loaded.llm_cleanup_timeout_seconds == 7.5


class TestRealtimeFeatureConfig:
    """Tests for the live-translation and voice-assistant config fields."""

    def test_defaults(self):
        """New realtime fields should default to safe values."""
        with patch("whisper_hud.config.CONFIG_FILE", Path("/tmp/test_config.json")):
            from whisper_hud.config import Config

            config = Config()

            assert config.live_translation_enabled is False
            assert config.assistant_model == "gpt-realtime-2"
            assert config.assistant_voice == "marin"
            assert config.assistant_reasoning_effort == "low"
            assert config.assistant_paste_tool_enabled is True

    def test_persistence_round_trip(self):
        """Realtime fields should survive a save/load cycle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.json"
            with patch("whisper_hud.config.CONFIG_FILE", config_file):
                with patch("whisper_hud.config.CONFIG_DIR", Path(tmpdir)):
                    from whisper_hud.config import Config

                    config = Config()
                    config.live_translation_enabled = True
                    config.assistant_model = "gpt-realtime-2"
                    config.assistant_voice = "cedar"
                    config.assistant_reasoning_effort = "high"
                    config.assistant_paste_tool_enabled = False
                    config.save()

                    loaded = Config.load()
                    assert loaded.live_translation_enabled is True
                    assert loaded.assistant_voice == "cedar"
                    assert loaded.assistant_reasoning_effort == "high"
                    assert loaded.assistant_paste_tool_enabled is False
