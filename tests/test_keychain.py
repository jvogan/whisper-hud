"""Tests for credential storage and API key management."""

from unittest.mock import patch


class TestKeychainMode:
    """Tests for keychain storage mode."""

    def test_get_api_key_returns_none_when_not_set(self, mock_keychain):
        """get_api_key should return None for missing keys in keychain mode."""
        from whisper_hud.keychain import get_api_key

        with patch("whisper_hud.keychain.get_storage_mode", return_value="keychain"):
            result = get_api_key("openai")

        assert result is None

    def test_set_api_key_stores_correctly(self, mock_keychain):
        """set_api_key should call keyring backend in keychain mode."""
        from whisper_hud.keychain import set_api_key

        with patch("whisper_hud.keychain.get_storage_mode", return_value="keychain"):
            result = set_api_key("openai", "sk-test-key-123")

        assert result is True
        mock_keychain["set"].assert_called_once_with(
            "whisper-hud",
            "whisper-hud.openai",
            "sk-test-key-123",
        )

    def test_delete_api_key(self, mock_keychain):
        """delete_api_key should call keyring backend in keychain mode."""
        from whisper_hud.keychain import delete_api_key

        with patch("whisper_hud.keychain.get_storage_mode", return_value="keychain"):
            result = delete_api_key("gemini")

        assert result is True
        mock_keychain["delete"].assert_called_once()

    def test_get_configured_providers(self, mock_keychain):
        """Configured provider list should reflect keychain backend values."""
        from whisper_hud.keychain import get_configured_providers

        with patch("whisper_hud.keychain.get_storage_mode", return_value="keychain"):
            mock_keychain["get"].return_value = None
            assert get_configured_providers() == []

            mock_keychain["get"].side_effect = lambda s, a: "key" if "openai" in a else None
            result = get_configured_providers()
            assert "openai" in result


class TestSessionOnlyMode:
    """Tests for in-memory session-only mode."""

    def test_none_mode_roundtrip(self):
        """Session-only mode should persist keys only in memory."""
        from whisper_hud.keychain import set_api_key, get_api_key, delete_api_key, clear_api_keys

        with patch("whisper_hud.keychain.get_storage_mode", return_value="none"):
            clear_api_keys(mode="none")
            assert set_api_key("openai", "sk-openai-session")
            assert get_api_key("openai") == "sk-openai-session"
            assert delete_api_key("openai")
            assert get_api_key("openai") is None


class TestPassphraseMode:
    """Tests for passphrase-encrypted local storage mode."""

    def test_passphrase_unlock_store_lock_roundtrip(self, temp_config_dir):
        """Passphrase mode should encrypt keys at rest and require unlock."""
        from whisper_hud.keychain import (
            unlock_passphrase_store,
            lock_passphrase_store,
            set_api_key,
            get_api_key,
            has_passphrase_store,
        )

        with patch("whisper_hud.config.CONFIG_DIR", temp_config_dir):
            with patch("whisper_hud.config.CONFIG_FILE", temp_config_dir / "config.json"):
                with patch("whisper_hud.keychain.get_storage_mode", return_value="passphrase"):
                    lock_passphrase_store()
                    ok, _ = unlock_passphrase_store("correct horse battery staple")
                    assert ok
                    assert has_passphrase_store()

                    assert set_api_key("openai", "sk-passphrase-123")
                    assert get_api_key("openai") == "sk-passphrase-123"

                    lock_passphrase_store()
                    assert get_api_key("openai") is None

                    ok, _ = unlock_passphrase_store("correct horse battery staple")
                    assert ok
                    assert get_api_key("openai") == "sk-passphrase-123"

    def test_passphrase_store_rejects_wrong_passphrase(self, temp_config_dir):
        """Unlock should fail with wrong passphrase once store exists."""
        from whisper_hud.keychain import unlock_passphrase_store, lock_passphrase_store

        with patch("whisper_hud.config.CONFIG_DIR", temp_config_dir):
            with patch("whisper_hud.config.CONFIG_FILE", temp_config_dir / "config.json"):
                lock_passphrase_store()
                ok, _ = unlock_passphrase_store("right-passphrase")
                assert ok
                lock_passphrase_store()

                ok, _ = unlock_passphrase_store("wrong-passphrase")
                assert not ok

    def test_change_passphrase(self, temp_config_dir):
        """Changing passphrase should preserve stored keys."""
        from whisper_hud.keychain import (
            unlock_passphrase_store,
            lock_passphrase_store,
            set_api_key,
            get_api_key,
            change_passphrase,
        )

        with patch("whisper_hud.config.CONFIG_DIR", temp_config_dir):
            with patch("whisper_hud.config.CONFIG_FILE", temp_config_dir / "config.json"):
                with patch("whisper_hud.keychain.get_storage_mode", return_value="passphrase"):
                    lock_passphrase_store()
                    ok, _ = unlock_passphrase_store("old-passphrase-123")
                    assert ok
                    assert set_api_key("gemini", "gm-key")

                    ok, _ = change_passphrase("old-passphrase-123", "new-passphrase-456")
                    assert ok

                    lock_passphrase_store()
                    ok, _ = unlock_passphrase_store("new-passphrase-456")
                    assert ok
                    assert get_api_key("gemini") == "gm-key"


class TestUtilityFunctions:
    """Tests for small key utility helpers."""

    def test_mask_api_key(self):
        """mask_api_key should redact middle characters."""
        from whisper_hud.keychain import mask_api_key

        assert mask_api_key("sk-1234567890abcdefghij") == "sk-12345...ghij"
        assert mask_api_key("short") == "****"
        assert mask_api_key("") == "****"
        assert mask_api_key(None) == "****"
