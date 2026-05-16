"""Tests for credential storage and API key management."""

import builtins
from unittest.mock import Mock, call, patch

import pytest


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
            result = set_api_key("openai", "sk-" + ("a" * 40))

        assert result is True
        mock_keychain["set"].assert_called_once_with(
            "whisper-hud",
            "whisper-hud.openai",
            "sk-" + ("a" * 40),
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

    def test_clear_api_keys_reports_keychain_cleanup_failures(self, mock_keychain):
        """clear_api_keys should surface backend delete failures in keychain mode."""
        from whisper_hud.keychain import clear_api_keys

        mock_keychain["delete"].side_effect = [None, RuntimeError("denied"), None]

        with patch("whisper_hud.keychain.get_storage_mode", return_value="keychain"):
            ok, message = clear_api_keys()

        assert not ok
        assert "gemini" in message

    def test_set_api_key_format_validation_strips_openai_whitespace(self, mock_keychain):
        """Leading and trailing whitespace should be removed before storing."""
        from whisper_hud.keychain import set_api_key

        raw_key = f"  {'sk-' + ('a' * 40)}  "

        with patch("whisper_hud.keychain.get_storage_mode", return_value="keychain"):
            result = set_api_key("openai", raw_key)

        assert result is True
        mock_keychain["set"].assert_called_once_with(
            "whisper-hud",
            "whisper-hud.openai",
            "sk-" + ("a" * 40),
        )

    def test_set_api_key_format_validation_rejects_openai_prefix(self, mock_keychain):
        """OpenAI keys should require the sk- prefix."""
        from whisper_hud.keychain import set_api_key

        with patch("whisper_hud.keychain.get_storage_mode", return_value="keychain"):
            try:
                set_api_key("openai", "pk-" + ("a" * 40))
                assert False, "Expected ValueError"
            except ValueError as exc:
                assert str(exc) == "OpenAI API keys must start with 'sk-'"

        mock_keychain["set"].assert_not_called()

    def test_set_api_key_format_validation_rejects_openai_short_key(self, mock_keychain):
        """OpenAI keys should meet the minimum length requirement."""
        from whisper_hud.keychain import set_api_key

        with patch("whisper_hud.keychain.get_storage_mode", return_value="keychain"):
            try:
                set_api_key("openai", "sk-short-key")
                assert False, "Expected ValueError"
            except ValueError as exc:
                assert str(exc) == "OpenAI API keys must be at least 40 characters"

        mock_keychain["set"].assert_not_called()

    def test_set_api_key_format_validation_rejects_embedded_whitespace(self, mock_keychain):
        """Internal whitespace should be rejected after trimming."""
        from whisper_hud.keychain import set_api_key

        with patch("whisper_hud.keychain.get_storage_mode", return_value="keychain"):
            try:
                set_api_key("openai", "sk-valid-key has-space-and-length-padding-1234567890")
                assert False, "Expected ValueError"
            except ValueError as exc:
                assert str(exc) == "OpenAI API key must not contain whitespace"

        mock_keychain["set"].assert_not_called()

    def test_set_api_key_format_validation_rejects_short_gemini_key(self, mock_keychain):
        """Gemini keys should meet the minimum length requirement."""
        from whisper_hud.keychain import set_api_key

        with patch("whisper_hud.keychain.get_storage_mode", return_value="keychain"):
            try:
                set_api_key("gemini", "short-gemini-key")
                assert False, "Expected ValueError"
            except ValueError as exc:
                assert str(exc) == "Gemini API keys must be at least 20 characters"

        mock_keychain["set"].assert_not_called()

    def test_set_api_key_format_validation_rejects_empty_after_trimming(self, mock_keychain):
        """Whitespace-only values should not be stored."""
        from whisper_hud.keychain import set_api_key

        with patch("whisper_hud.keychain.get_storage_mode", return_value="keychain"):
            try:
                set_api_key("gemini", "   ")
                assert False, "Expected ValueError"
            except ValueError as exc:
                assert str(exc) == "Gemini API key cannot be empty"

        mock_keychain["set"].assert_not_called()


class TestSessionOnlyMode:
    """Tests for in-memory session-only mode."""

    def test_none_mode_roundtrip(self):
        """Session-only mode should persist keys only in memory."""
        from whisper_hud.keychain import set_api_key, get_api_key, delete_api_key, clear_api_keys

        with patch("whisper_hud.keychain.get_storage_mode", return_value="none"):
            clear_api_keys(mode="none")
            valid_openai_key = "sk-" + ("b" * 40)
            assert set_api_key("openai", valid_openai_key)
            assert get_api_key("openai") == valid_openai_key
            assert delete_api_key("openai")
            assert get_api_key("openai") is None

    def test_import_api_keys_replace_does_not_clear_existing_keys_before_validation(self):
        """Replacement imports should validate first so bad input cannot wipe working keys."""
        from whisper_hud.keychain import clear_api_keys, get_api_key, import_api_keys, set_api_key

        with patch("whisper_hud.keychain.get_storage_mode", return_value="none"):
            clear_api_keys(mode="none")
            existing_key = "sk-" + ("z" * 40)
            assert set_api_key("openai", existing_key)

            with pytest.raises(ValueError, match="OpenAI API keys must start with 'sk-'"):
                import_api_keys({"openai": "bad-key"}, mode="none", replace=True)

            assert get_api_key("openai") == existing_key


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

                    valid_openai_key = "sk-" + ("c" * 40)
                    assert set_api_key("openai", valid_openai_key)
                    assert get_api_key("openai") == valid_openai_key

                    lock_passphrase_store()
                    assert get_api_key("openai") is None

                    ok, _ = unlock_passphrase_store("correct horse battery staple")
                    assert ok
                    assert get_api_key("openai") == valid_openai_key

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
                    valid_gemini_key = "g" * 20
                    assert set_api_key("gemini", valid_gemini_key)

                    ok, _ = change_passphrase("old-passphrase-123", "new-passphrase-456")
                    assert ok

                    lock_passphrase_store()
                    ok, _ = unlock_passphrase_store("new-passphrase-456")
                    assert ok
                    assert get_api_key("gemini") == valid_gemini_key

    def test_change_passphrase_rolls_back_history_rewrap_when_credential_write_fails(self, temp_config_dir):
        """History key rewrap should not be left ahead of credentials after a partial failure."""
        from whisper_hud.keychain import (
            unlock_passphrase_store,
            lock_passphrase_store,
            set_api_key,
            change_passphrase,
        )

        with patch("whisper_hud.config.CONFIG_DIR", temp_config_dir):
            with patch("whisper_hud.config.CONFIG_FILE", temp_config_dir / "config.json"):
                with patch("whisper_hud.keychain.get_storage_mode", return_value="passphrase"):
                    lock_passphrase_store()
                    ok, _ = unlock_passphrase_store("old-passphrase-123")
                    assert ok
                    assert set_api_key("gemini", "g" * 20)

                    with patch("whisper_hud.encryption.has_encryption_key", return_value=True):
                        with patch("whisper_hud.encryption.rewrap_history_key", return_value=(True, "")) as mock_rewrap:
                            with patch("whisper_hud.keychain._write_passphrase_store", return_value=False):
                                ok, message = change_passphrase("old-passphrase-123", "new-passphrase-456")

        assert ok is False
        assert message == "Failed to update passphrase"
        assert mock_rewrap.call_args_list == [
            call("old-passphrase-123", "new-passphrase-456"),
            call("new-passphrase-456", "old-passphrase-123"),
        ]

    def test_failed_passphrase_change_keeps_history_readable_with_old_passphrase(self, temp_config_dir):
        """A failed credential rewrite should restore the history key to the old passphrase."""
        from whisper_hud.encryption import (
            decrypt_text,
            encrypt_text,
            lock_history_encryption,
            unlock_history_encryption,
        )
        from whisper_hud.keychain import change_passphrase, lock_passphrase_store, set_api_key, unlock_passphrase_store

        with patch("whisper_hud.config.CONFIG_DIR", temp_config_dir):
            with patch("whisper_hud.config.CONFIG_FILE", temp_config_dir / "config.json"):
                with patch("whisper_hud.keychain.get_storage_mode", return_value="passphrase"):
                    lock_passphrase_store()
                    lock_history_encryption()
                    ok, _ = unlock_passphrase_store("old-passphrase-123")
                    assert ok
                    assert set_api_key("gemini", "g" * 20)

                    ok, _ = unlock_history_encryption("old-passphrase-123", create_if_missing=True)
                    assert ok
                    encrypted_text = encrypt_text("private history item")
                    assert encrypted_text

                    with patch("whisper_hud.keychain._write_passphrase_store", return_value=False):
                        ok, message = change_passphrase("old-passphrase-123", "new-passphrase-456")

                    assert ok is False
                    assert message == "Failed to update passphrase"

                    lock_history_encryption()
                    ok, _ = unlock_history_encryption("old-passphrase-123", create_if_missing=False)
                    assert ok
                    assert decrypt_text(encrypted_text) == "private history item"

                    lock_history_encryption()
                    ok, _ = unlock_history_encryption("new-passphrase-456", create_if_missing=False)
                    assert not ok


class TestUtilityFunctions:
    """Tests for small key utility helpers."""

    def test_mask_api_key(self):
        """mask_api_key should redact middle characters."""
        from whisper_hud.keychain import mask_api_key

        assert mask_api_key("sk-1234567890abcdefghij") == "sk-12345...ghij"
        assert mask_api_key("short") == "****"
        assert mask_api_key("") == "****"
        assert mask_api_key(None) == "****"


class TestValidateApiKey:
    """Tests for API key validation."""

    def test_validate_api_key_returns_true_for_valid_openai_key(self):
        """A 200 response should mark the key as valid."""
        from whisper_hud.keychain import validate_api_key

        response = Mock(status_code=200)
        valid_key = "sk-valid-key-padded-to-pass-format-check-1234"

        with patch("whisper_hud.keychain._validation_get", return_value=response) as mock_get:
            is_valid, error = validate_api_key("openai", valid_key)

        assert is_valid is True
        assert error == ""
        mock_get.assert_called_once_with(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {valid_key}"},
            timeout=10,
            allow_redirects=False,
        )

    def test_validate_api_key_returns_false_for_invalid_openai_key(self):
        """A 401 response should mark the key as invalid."""
        from whisper_hud.keychain import validate_api_key

        response = Mock(status_code=401)
        invalid_key = "sk-invalid-key-padded-to-pass-format-1234567"

        with patch("whisper_hud.keychain._validation_get", return_value=response) as mock_get:
            is_valid, error = validate_api_key("openai", invalid_key)

        assert is_valid is False
        assert error == "Invalid API key"
        mock_get.assert_called_once()

    def test_validate_api_key_returns_false_for_timeout(self):
        """Timeouts should not be treated as valid keys."""
        from whisper_hud.keychain import validate_api_key
        from requests.exceptions import Timeout

        timeout_key = "sk-timeout-key-padded-to-pass-format-123456789"

        with patch("whisper_hud.keychain._validation_get", side_effect=Timeout) as mock_get:
            is_valid, error = validate_api_key("openai", timeout_key)

        assert is_valid is False
        assert error == "Connection timed out"
        mock_get.assert_called_once()

    def test_validate_api_key_returns_false_when_requests_not_installed(self):
        """Missing requests should not bypass validation."""
        from whisper_hud.keychain import REQUESTS_MISSING_WARNING, validate_api_key

        original_import = builtins.__import__

        def import_without_requests(name, *args, **kwargs):
            if name == "requests":
                raise ImportError("No module named 'requests'")
            return original_import(name, *args, **kwargs)

        no_requests_key = "sk-no-requests-padded-to-pass-format-12345678"

        with patch("builtins.__import__", side_effect=import_without_requests):
            is_valid, error = validate_api_key("openai", no_requests_key)

        assert is_valid is False
        assert error == REQUESTS_MISSING_WARNING

    def test_validate_api_key_returns_false_for_empty_key(self):
        """An empty key should fail format check before any network call."""
        from whisper_hud.keychain import validate_api_key

        with patch("whisper_hud.keychain._validation_get") as mock_get:
            is_valid, error = validate_api_key("openai", "")

        assert is_valid is False
        assert error == "Invalid API key format"
        mock_get.assert_not_called()

    def test_validate_api_key_disables_redirects_for_gemini(self):
        """Validation requests should not follow redirects with API-key headers attached."""
        from whisper_hud.keychain import validate_api_key

        response = Mock(status_code=200)
        valid_key = "g" * 24

        with patch("whisper_hud.keychain._validation_get", return_value=response) as mock_get:
            is_valid, error = validate_api_key("gemini", valid_key)

        assert is_valid is True
        assert error == ""
        mock_get.assert_called_once_with(
            "https://generativelanguage.googleapis.com/v1/models",
            headers={"x-goog-api-key": valid_key},
            timeout=10,
            allow_redirects=False,
        )

    def test_validate_api_key_disables_redirects_for_anthropic(self):
        """Anthropic validation should use the same no-redirect API-key handling."""
        from whisper_hud.keychain import validate_api_key

        response = Mock(status_code=200)
        valid_key = "sk-ant-" + "a" * 24

        with patch("whisper_hud.keychain._validation_get", return_value=response) as mock_get:
            is_valid, error = validate_api_key("anthropic", valid_key)

        assert is_valid is True
        assert error == ""
        mock_get.assert_called_once_with(
            "https://api.anthropic.com/v1/models",
            headers={"x-api-key": valid_key, "anthropic-version": "2023-06-01"},
            timeout=10,
            allow_redirects=False,
        )

    def test_validation_get_ignores_ambient_proxy_environment(self):
        """Validation requests should not send API-key headers through env-configured proxies."""
        from whisper_hud.keychain import _validation_get

        class FakeSession:
            def __init__(self):
                self.trust_env = True
                self.get = Mock(return_value=Mock(status_code=200))

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        fake_session = FakeSession()

        with patch("requests.Session", return_value=fake_session):
            response = _validation_get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": "Bearer sk-test"},
                timeout=10,
                allow_redirects=False,
            )

        assert response.status_code == 200
        assert fake_session.trust_env is False
        fake_session.get.assert_called_once_with(
            "https://api.openai.com/v1/models",
            headers={"Authorization": "Bearer sk-test"},
            timeout=10,
            allow_redirects=False,
        )
