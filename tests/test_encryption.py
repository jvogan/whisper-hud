"""Tests for encryption and privacy features."""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch


class TestSecureDelete:
    """Tests for secure file deletion."""

    def test_secure_delete_file(self):
        """Test that secure_delete overwrites file before deleting."""
        from whisper_hud.encryption import secure_delete

        # Create a temp file with content
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("sensitive data")
            temp_path = f.name

        assert os.path.exists(temp_path)

        # Secure delete
        result = secure_delete(temp_path)

        assert result is True
        assert not os.path.exists(temp_path)

    def test_secure_delete_nonexistent_file(self):
        """Test that secure_delete handles nonexistent files gracefully."""
        from whisper_hud.encryption import secure_delete

        result = secure_delete("/tmp/nonexistent_file_12345.txt")
        assert result is True

    def test_secure_delete_empty_path(self):
        """Test that secure_delete handles empty path."""
        from whisper_hud.encryption import secure_delete

        result = secure_delete("")
        assert result is True

        result = secure_delete(None)
        assert result is True


class TestEncryption:
    """Tests for encryption/decryption functions."""

    @pytest.fixture(autouse=True)
    def _passphrase_session(self, temp_config_dir):
        """Use passphrase-backed session unlock for history encryption tests."""
        config_file = temp_config_dir / "config.json"
        with patch("whisper_hud.config.CONFIG_DIR", temp_config_dir):
            with patch("whisper_hud.config.CONFIG_FILE", config_file):
                from whisper_hud.keychain import lock_passphrase_store, unlock_passphrase_store
                from whisper_hud.encryption import lock_history_encryption, delete_key

                lock_passphrase_store()
                lock_history_encryption()
                delete_key()

                ok, message = unlock_passphrase_store("test-passphrase-123")
                assert ok, message

                yield

                lock_history_encryption()
                lock_passphrase_store()
                delete_key()

    def test_encrypt_decrypt_roundtrip(self):
        """Test that encryption and decryption work correctly."""
        pytest.importorskip("cryptography")
        from whisper_hud.encryption import encrypt_text, decrypt_text

        original = "Hello, this is sensitive transcription data!"

        encrypted = encrypt_text(original)
        assert encrypted is not None
        assert encrypted != original  # Should be different

        decrypted = decrypt_text(encrypted)
        assert decrypted == original

    def test_encrypt_empty_text(self):
        """Test that encrypting empty text returns None."""
        pytest.importorskip("cryptography")
        from whisper_hud.encryption import encrypt_text

        assert encrypt_text("") is None
        assert encrypt_text(None) is None

    def test_decrypt_empty_text(self):
        """Test that decrypting empty text returns None."""
        pytest.importorskip("cryptography")
        from whisper_hud.encryption import decrypt_text

        assert decrypt_text("") is None
        assert decrypt_text(None) is None

    def test_get_or_create_key(self):
        """Test that key is created if not exists."""
        pytest.importorskip("cryptography")
        from whisper_hud.encryption import get_or_create_key

        # First call should create key
        key1 = get_or_create_key()
        assert key1 is not None
        assert len(key1) > 0

        # Second call should return same key
        key2 = get_or_create_key()
        assert key1 == key2

    def test_delete_key(self):
        """Test deleting encryption key."""
        pytest.importorskip("cryptography")
        from whisper_hud.encryption import get_or_create_key, delete_key, has_encryption_key

        # Create a key
        get_or_create_key()
        assert has_encryption_key()

        # Delete it
        result = delete_key()
        assert result is True
        assert not has_encryption_key()

    def test_has_encryption_key(self):
        """Test checking for encryption key."""
        from whisper_hud.encryption import has_encryption_key

        # Initially no key
        assert not has_encryption_key()

    def test_history_encryption_does_not_use_keychain(self):
        """History encryption should not call keyring APIs."""
        pytest.importorskip("cryptography")
        from whisper_hud.encryption import encrypt_text

        with patch("keyring.get_password") as mock_get:
            with patch("keyring.set_password") as mock_set:
                with patch("keyring.delete_password") as mock_delete:
                    encrypted = encrypt_text("hello")

        assert encrypted is not None
        mock_get.assert_not_called()
        mock_set.assert_not_called()
        mock_delete.assert_not_called()


class TestCryptographyCheck:
    """Test cryptography package detection."""

    def test_is_cryptography_installed(self):
        """Test that we can detect cryptography package."""
        from whisper_hud.encryption import is_cryptography_installed

        # Should return True if cryptography is installed
        try:
            import cryptography  # noqa: F401
            assert is_cryptography_installed() is True
        except ImportError:
            assert is_cryptography_installed() is False


class TestOrphanedTempCleanup:
    """Tests for orphaned temp file cleanup."""

    def test_cleanup_old_temp_files(self):
        """Test cleanup of old temp files."""
        from whisper_hud.encryption import cleanup_orphaned_temp_files
        import time

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create an "old" file (we'll mock the time check)
            temp_file = os.path.join(tmpdir, "whisper_hud_test.wav")
            with open(temp_file, 'w') as f:
                f.write("test audio data")

            # Make file appear old by setting mtime to 2 hours ago
            old_time = time.time() - 7200  # 2 hours ago
            os.utime(temp_file, (old_time, old_time))

            # Run cleanup
            cleaned = cleanup_orphaned_temp_files(prefix="whisper_hud", temp_dir=tmpdir)

            # Should have cleaned up the file
            assert cleaned == 1
            assert not os.path.exists(temp_file)

    def test_cleanup_skips_recent_files(self):
        """Test that recent files are not cleaned up."""
        from whisper_hud.encryption import cleanup_orphaned_temp_files

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a recent file
            temp_file = os.path.join(tmpdir, "whisper_hud_recent.wav")
            with open(temp_file, 'w') as f:
                f.write("test audio data")

            # Run cleanup (file is recent, should be skipped)
            cleaned = cleanup_orphaned_temp_files(prefix="whisper_hud", temp_dir=tmpdir)

            assert cleaned == 0
            assert os.path.exists(temp_file)


class TestPrivacyConfig:
    """Tests for privacy configuration."""

    def test_private_mode_defaults(self):
        """Test that private mode is off by default."""
        with patch('whisper_hud.config.CONFIG_FILE', Path('/tmp/test_config.json')):
            from whisper_hud.config import Config
            config = Config()

            assert config.private_mode is False
            assert config.history_encrypted is False

    def test_enable_private_mode_clears_history(self):
        """Test that enabling private mode clears history."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.json"

            with patch('whisper_hud.config.CONFIG_FILE', config_file):
                with patch('whisper_hud.config.CONFIG_DIR', Path(tmpdir)):
                    from whisper_hud.config import Config

                    config = Config()
                    config.history_enabled = True
                    config.history = [{"text": "test", "timestamp": 0}]

                    config.enable_private_mode()

                    assert config.private_mode is True
                    assert config.history_enabled is False
                    assert len(config.history) == 0

    def test_private_mode_prevents_history_storage(self):
        """Test that private mode prevents storing transcriptions."""
        with patch('whisper_hud.config.CONFIG_FILE', Path('/tmp/test_config.json')):
            from whisper_hud.config import Config
            config = Config()
            config.private_mode = True
            config.history = []

            # Try to add to history
            config.add_to_history("This should not be saved", provider="test")

            # Should not have been saved
            assert len(config.history) == 0

    def test_disable_private_mode(self):
        """Test disabling private mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.json"

            with patch('whisper_hud.config.CONFIG_FILE', config_file):
                with patch('whisper_hud.config.CONFIG_DIR', Path(tmpdir)):
                    from whisper_hud.config import Config

                    config = Config()
                    config.enable_private_mode()
                    assert config.private_mode is True

                    config.disable_private_mode()
                    assert config.private_mode is False


class TestEncryptedHistory:
    """Tests for encrypted history storage."""

    @pytest.fixture
    def mock_encryption(self):
        """Mock encryption functions."""
        with patch('whisper_hud.config.encrypt_text') as mock_enc:
            with patch('whisper_hud.config.decrypt_text') as mock_dec:
                mock_enc.side_effect = lambda x: f"ENCRYPTED:{x}" if x else None
                mock_dec.side_effect = lambda x: x.replace("ENCRYPTED:", "") if x and x.startswith("ENCRYPTED:") else None
                yield {'encrypt': mock_enc, 'decrypt': mock_dec}

    def test_history_encrypted_flag(self):
        """Test that encrypted flag is set on history entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.json"

            with patch('whisper_hud.config.CONFIG_FILE', config_file):
                with patch('whisper_hud.config.CONFIG_DIR', Path(tmpdir)):
                    from whisper_hud.config import Config

                    config = Config()
                    config.history_enabled = True
                    config.history_encrypted = True
                    config.history = []

                    # Mock the encryption
                    with patch('whisper_hud.encryption.encrypt_text') as mock_enc:
                        mock_enc.side_effect = lambda x: f"ENC:{x}" if x else None

                        config.add_to_history("test message", provider="test")

                        assert len(config.history) == 1
                        assert config.history[0]["encrypted"] is True

    def test_history_not_encrypted_when_disabled(self):
        """Test that history is not encrypted when encryption is disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.json"

            with patch('whisper_hud.config.CONFIG_FILE', config_file):
                with patch('whisper_hud.config.CONFIG_DIR', Path(tmpdir)):
                    from whisper_hud.config import Config

                    config = Config()
                    config.history_enabled = True
                    config.history_encrypted = False
                    config.history = []

                    config.add_to_history("test message", provider="test")

                    assert len(config.history) == 1
                    assert config.history[0].get("encrypted", False) is False
                    assert config.history[0]["text"] == "test message"
