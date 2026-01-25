"""Tests for keychain API key management."""

import pytest
from unittest.mock import patch, MagicMock


class TestKeychain:
    """Tests for keychain functions."""

    def test_get_api_key_returns_none_when_not_set(self, mock_keychain):
        """Test that get_api_key returns None for missing keys."""
        from whisper_hud.keychain import get_api_key

        result = get_api_key("openai")
        assert result is None

    def test_set_api_key_stores_correctly(self, mock_keychain):
        """Test that set_api_key calls keyring correctly."""
        from whisper_hud.keychain import set_api_key

        result = set_api_key("openai", "sk-test-key-123")

        assert result is True
        mock_keychain['set'].assert_called_once_with(
            "whisper-hud",
            "whisper-hud.openai",
            "sk-test-key-123"
        )

    def test_delete_api_key(self, mock_keychain):
        """Test that delete_api_key calls keyring correctly."""
        from whisper_hud.keychain import delete_api_key

        result = delete_api_key("gemini")

        assert result is True
        mock_keychain['delete'].assert_called_once()

    def test_mask_api_key(self):
        """Test API key masking for display."""
        from whisper_hud.keychain import mask_api_key

        # Normal key
        assert mask_api_key("sk-1234567890abcdefghij") == "sk-12345...ghij"

        # Short key
        assert mask_api_key("short") == "****"

        # Empty key
        assert mask_api_key("") == "****"
        assert mask_api_key(None) == "****"

    def test_get_configured_providers(self, mock_keychain):
        """Test listing configured providers."""
        from whisper_hud.keychain import get_configured_providers

        # No keys configured
        mock_keychain['get'].return_value = None
        result = get_configured_providers()
        assert result == []

        # OpenAI configured
        mock_keychain['get'].side_effect = lambda s, a: "key" if "openai" in a else None
        result = get_configured_providers()
        assert "openai" in result
