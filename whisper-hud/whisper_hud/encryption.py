"""
Encryption utilities for sensitive data.

History encryption keys are passphrase-backed and unlocked for the current app
session, matching the app's passphrase storage lifecycle and avoiding Keychain
prompts for history encryption.

Also includes secure file deletion for temp audio files.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from .logging_config import get_logger

logger = get_logger("encryption")

HISTORY_KEY_FILE = "history_encryption.key"
SCRYPT_PARAMS = {"n": 2**17, "r": 8, "p": 1, "length": 32}
_session_history_key: Optional[bytes] = None


def _history_key_file() -> Path:
    from .config import CONFIG_DIR

    return CONFIG_DIR / HISTORY_KEY_FILE


def _ensure_history_key_permissions(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
    except Exception:
        pass
    if path.exists():
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass


def _read_history_key_payload() -> Optional[dict]:
    path = _history_key_file()
    if not path.exists():
        return None
    _ensure_history_key_permissions(path)
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


def _write_history_key_payload(payload: dict) -> bool:
    path = _history_key_file()
    _ensure_history_key_permissions(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=".history_key.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(payload, temp_file)
            temp_file.flush()
            os.fsync(temp_file.fileno())

        try:
            os.chmod(temp_path, 0o600)
        except Exception:
            pass

        os.replace(temp_path, path)
        _ensure_history_key_permissions(path)
        return True
    except Exception as e:
        logger.error(f"Failed to write history encryption key payload: {e}")
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        return False


def _derive_wrap_key(passphrase: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    kdf = Scrypt(salt=salt, **SCRYPT_PARAMS)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def _unwrap_history_key(passphrase: str, salt: bytes, wrapped_key: str) -> bytes:
    from cryptography.fernet import Fernet

    wrap_fernet = Fernet(_derive_wrap_key(passphrase, salt))
    raw = wrap_fernet.decrypt(wrapped_key.encode("utf-8"))
    # Validate shape by instantiating Fernet with it.
    Fernet(raw)
    return raw


def _wrap_history_key(passphrase: str, salt: bytes, history_key: bytes) -> str:
    from cryptography.fernet import Fernet

    wrap_fernet = Fernet(_derive_wrap_key(passphrase, salt))
    return wrap_fernet.encrypt(history_key).decode("utf-8")


def _get_unlocked_passphrase() -> Optional[str]:
    try:
        from .keychain import get_unlocked_passphrase

        return get_unlocked_passphrase()
    except Exception:
        return None


def is_history_encryption_unlocked() -> bool:
    """Return True when the history encryption key is unlocked for this session."""
    return _session_history_key is not None


def lock_history_encryption() -> None:
    """Clear in-memory history encryption material for this app session."""
    global _session_history_key
    _session_history_key = None


def unlock_history_encryption(passphrase: str, create_if_missing: bool = True) -> tuple[bool, str]:
    """
    Unlock history encryption using the app passphrase.

    Args:
        passphrase: Current unlocked app passphrase.
        create_if_missing: Create history key metadata when missing.
    """
    global _session_history_key

    if not passphrase:
        return False, "Passphrase is required to unlock history encryption"
    if not is_cryptography_installed():
        return False, "cryptography package is required for history encryption"

    payload = _read_history_key_payload()

    # First-time setup: generate a random data key and wrap it with passphrase.
    if payload is None:
        if not create_if_missing:
            return False, "History encryption key is not set up yet"
        try:
            from cryptography.fernet import Fernet

            salt = os.urandom(32)
            history_key = Fernet.generate_key()
            wrapped_key = _wrap_history_key(passphrase, salt, history_key)
            payload = {
                "version": 1,
                "kdf": "scrypt",
                "salt": base64.b64encode(salt).decode("utf-8"),
                "wrapped_key": wrapped_key,
            }
            if not _write_history_key_payload(payload):
                return False, "Failed to create history encryption key"
            _session_history_key = history_key
            return True, "History encryption key created and unlocked"
        except Exception as e:
            _session_history_key = None
            return False, f"Failed to initialize history encryption: {str(e)[:120]}"

    try:
        salt_b64 = payload.get("salt")
        wrapped_key = payload.get("wrapped_key")
        if not isinstance(salt_b64, str) or not isinstance(wrapped_key, str):
            return False, "History encryption key payload is invalid"

        salt = base64.b64decode(salt_b64.encode("utf-8"))
        _session_history_key = _unwrap_history_key(passphrase, salt, wrapped_key)
        return True, "History encryption unlocked"
    except Exception:
        _session_history_key = None
        return False, "Could not unlock history encryption key with current passphrase"


def ensure_history_encryption_unlocked(create_if_missing: bool = False) -> tuple[bool, str]:
    """
    Unlock history encryption using the currently unlocked app passphrase.

    This avoids additional prompts and keeps history encryption aligned with
    passphrase-session lifecycle.
    """
    if is_history_encryption_unlocked():
        return True, "History encryption already unlocked"

    passphrase = _get_unlocked_passphrase()
    if not passphrase:
        return False, "Unlock API key passphrase first in Privacy & Security"

    return unlock_history_encryption(passphrase, create_if_missing=create_if_missing)


def get_or_create_key() -> bytes:
    """
    Get history encryption key for this app session, creating it if needed.

    Requires an unlocked passphrase session.
    """
    ok, message = ensure_history_encryption_unlocked(create_if_missing=True)
    if not ok or _session_history_key is None:
        raise RuntimeError(message or "History encryption key is locked")
    return _session_history_key


def delete_key() -> bool:
    """
    Delete history encryption key metadata and lock in-memory key.

    Existing encrypted history entries will no longer be decryptable afterward.
    """
    lock_history_encryption()
    path = _history_key_file()
    if not path.exists():
        return True
    try:
        path.unlink()
        return True
    except Exception as e:
        logger.error(f"Failed to delete history encryption key metadata: {e}")
        return False


def has_encryption_key() -> bool:
    """Return True when a history encryption key payload exists on disk."""
    payload = _read_history_key_payload()
    if not payload:
        return False
    return isinstance(payload.get("salt"), str) and isinstance(payload.get("wrapped_key"), str)


def rewrap_history_key(current_passphrase: str, new_passphrase: str) -> tuple[bool, str]:
    """
    Re-encrypt the history data key under a new passphrase.

    Called during passphrase change so encrypted history remains readable.
    """
    if not has_encryption_key():
        return True, "No history encryption key to update"
    if not current_passphrase or not new_passphrase:
        return False, "Current and new passphrase are required"
    if not is_cryptography_installed():
        return False, "cryptography package is required for history encryption"

    payload = _read_history_key_payload()
    if not payload:
        return False, "History encryption key payload is missing"

    try:
        salt_b64 = payload.get("salt")
        wrapped_key = payload.get("wrapped_key")
        if not isinstance(salt_b64, str) or not isinstance(wrapped_key, str):
            return False, "History encryption key payload is invalid"

        current_salt = base64.b64decode(salt_b64.encode("utf-8"))
        history_key = _unwrap_history_key(current_passphrase, current_salt, wrapped_key)

        new_salt = os.urandom(32)
        new_wrapped_key = _wrap_history_key(new_passphrase, new_salt, history_key)
        new_payload = {
            "version": 1,
            "kdf": "scrypt",
            "salt": base64.b64encode(new_salt).decode("utf-8"),
            "wrapped_key": new_wrapped_key,
        }
        if not _write_history_key_payload(new_payload):
            return False, "Failed to persist updated history encryption key"
        return True, "History encryption passphrase updated"
    except Exception:
        return False, "Could not re-encrypt history key with the new passphrase"


def encrypt_text(text: str) -> Optional[str]:
    """
    Encrypt text using Fernet (AES-256).

    Returns:
        Base64-encoded encrypted string, or None if encryption fails.
    """
    if not text:
        return None

    try:
        from cryptography.fernet import Fernet

        ok, _ = ensure_history_encryption_unlocked(create_if_missing=True)
        if not ok or _session_history_key is None:
            logger.warning("History encryption key is locked; cannot encrypt history")
            return None
        f = Fernet(_session_history_key)
        encrypted = f.encrypt(text.encode("utf-8"))
        return encrypted.decode("utf-8")
    except ImportError:
        logger.warning("cryptography not installed, cannot encrypt")
        return None
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        return None


def decrypt_text(encrypted: str) -> Optional[str]:
    """
    Decrypt base64-encoded encrypted string back to plain text.

    Returns:
        Decrypted plain text, or None if decryption fails.
    """
    if not encrypted:
        return None

    try:
        from cryptography.fernet import Fernet

        ok, _ = ensure_history_encryption_unlocked(create_if_missing=False)
        if not ok or _session_history_key is None:
            return None
        f = Fernet(_session_history_key)
        decrypted = f.decrypt(encrypted.encode("utf-8"))
        return decrypted.decode("utf-8")
    except ImportError:
        logger.warning("cryptography not installed, cannot decrypt")
        return None
    except Exception as e:
        logger.debug(f"Decryption failed: {e}")
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
            return False
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
    import glob

    if temp_dir is None:
        temp_dir = tempfile.gettempdir()

    # Find matching temp files
    pattern = os.path.join(temp_dir, f"{prefix}*.wav")
    orphaned_files = glob.glob(pattern)

    cleaned = 0
    for filepath in orphaned_files:
        try:
            if os.path.islink(filepath):
                continue
            # Check if file is old (more than 5 minutes)
            mtime = os.path.getmtime(filepath)
            import time

            age_seconds = time.time() - mtime
            if age_seconds > 300:  # 5 minutes
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
