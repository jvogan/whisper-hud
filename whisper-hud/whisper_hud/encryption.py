"""
Encryption utilities for sensitive data.

Provides AES-256 encryption via Fernet for securing transcription history,
with keys stored securely in macOS Keychain.

Also includes secure file deletion for temp audio files.
"""

import os
from typing import Optional

import keyring

from .logging_config import get_logger

logger = get_logger("encryption")

SERVICE_NAME = "whisper-hud"
ENCRYPTION_KEY_NAME = f"{SERVICE_NAME}.encryption_key"


def get_or_create_key() -> bytes:
    """
    Get encryption key from Keychain, or create one if it doesn't exist.

    Returns:
        bytes: The encryption key
    """
    key = keyring.get_password(SERVICE_NAME, ENCRYPTION_KEY_NAME)
    if key is None:
        # Import here to avoid loading cryptography unless needed
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        keyring.set_password(SERVICE_NAME, ENCRYPTION_KEY_NAME, key)
        logger.info("Created new encryption key in Keychain")
    return key.encode()


def delete_key() -> bool:
    """
    Delete encryption key from Keychain.

    Returns:
        True if successful or key didn't exist
    """
    try:
        keyring.delete_password(SERVICE_NAME, ENCRYPTION_KEY_NAME)
        logger.info("Deleted encryption key from Keychain")
        return True
    except keyring.errors.PasswordDeleteError:
        return True  # Key didn't exist, that's fine
    except Exception as e:
        logger.error(f"Failed to delete encryption key: {e}")
        return False


def has_encryption_key() -> bool:
    """
    Check if an encryption key exists in Keychain.

    Returns:
        True if key exists
    """
    try:
        key = keyring.get_password(SERVICE_NAME, ENCRYPTION_KEY_NAME)
        return key is not None
    except Exception:
        return False


def encrypt_text(text: str) -> Optional[str]:
    """
    Encrypt text using Fernet (AES-256).

    Args:
        text: Plain text to encrypt

    Returns:
        Base64-encoded encrypted string, or None if encryption fails
    """
    if not text:
        return None

    try:
        from cryptography.fernet import Fernet

        key = get_or_create_key()
        f = Fernet(key)
        encrypted = f.encrypt(text.encode())
        return encrypted.decode()
    except ImportError:
        logger.warning("cryptography not installed, cannot encrypt")
        return None
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        return None


def decrypt_text(encrypted: str) -> Optional[str]:
    """
    Decrypt base64-encoded encrypted string back to plain text.

    Args:
        encrypted: Base64-encoded encrypted string

    Returns:
        Decrypted plain text, or None if decryption fails
    """
    if not encrypted:
        return None

    try:
        from cryptography.fernet import Fernet

        key = get_or_create_key()
        f = Fernet(key)
        decrypted = f.decrypt(encrypted.encode())
        return decrypted.decode()
    except ImportError:
        logger.warning("cryptography not installed, cannot decrypt")
        return None
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        return None


def secure_delete(filepath: str) -> bool:
    """
    Securely delete a file by overwriting with zeros before unlinking.

    This makes it harder to recover the file contents from disk.

    Args:
        filepath: Path to file to securely delete

    Returns:
        True if successful, False otherwise
    """
    if not filepath or not os.path.exists(filepath):
        return True  # Nothing to delete

    try:
        # Get file size
        size = os.path.getsize(filepath)

        # Overwrite with zeros
        with open(filepath, "wb") as f:
            f.write(b"\x00" * size)
            f.flush()
            os.fsync(f.fileno())

        # Now unlink
        os.unlink(filepath)
        return True
    except Exception as e:
        # If secure delete fails, try regular delete
        logger.debug(f"Secure delete failed, attempting regular delete: {e}")
        try:
            os.unlink(filepath)
            return True
        except Exception as e2:
            logger.error(f"Failed to delete file {filepath}: {e2}")
            return False


def cleanup_orphaned_temp_files(prefix: str = "whisper_hud", temp_dir: Optional[str] = None) -> int:
    """
    Clean up any orphaned temp files from crashed sessions.

    Args:
        prefix: File name prefix to match
        temp_dir: Directory to scan (defaults to system temp)

    Returns:
        Number of files cleaned up
    """
    import tempfile
    import glob

    if temp_dir is None:
        temp_dir = tempfile.gettempdir()

    # Find matching temp files
    pattern = os.path.join(temp_dir, f"{prefix}*.wav")
    orphaned_files = glob.glob(pattern)

    cleaned = 0
    for filepath in orphaned_files:
        try:
            # Check if file is old (more than 1 hour)
            mtime = os.path.getmtime(filepath)
            import time

            age_seconds = time.time() - mtime
            if age_seconds > 3600:  # 1 hour
                if secure_delete(filepath):
                    cleaned += 1
                    logger.debug(f"Cleaned up orphaned temp file: {filepath}")
        except Exception as e:
            logger.debug(f"Failed to check/clean temp file {filepath}: {e}")

    if cleaned > 0:
        logger.info(f"Cleaned up {cleaned} orphaned temp file(s)")

    return cleaned


def is_cryptography_installed() -> bool:
    """
    Check if the cryptography package is installed.

    Returns:
        True if cryptography is available
    """
    try:
        import cryptography  # noqa: F401

        return True
    except ImportError:
        return False
