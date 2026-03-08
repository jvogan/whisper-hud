"""
Credential storage and API key validation helpers.

Supported storage modes:
- passphrase: encrypted local file unlocked for the current app session
- keychain: macOS Keychain via keyring
- none: in-memory only (lost when app quits)
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

import keyring

from .logging_config import get_logger

logger = get_logger("keychain")

SERVICE_NAME = "whisper-hud"
PROVIDERS = ("openai", "gemini", "anthropic")
STORAGE_MODES = ("passphrase", "keychain", "none")
DEFAULT_STORAGE_MODE = "passphrase"
PASSFILE_NAME = "credentials.enc"

_session_passphrase: Optional[str] = None
_session_passphrase_cache: dict[str, str] = {}
_session_none_cache: dict[str, str] = {}


def _normalize_mode(mode: Optional[str]) -> str:
    if mode in STORAGE_MODES:
        return str(mode)
    return DEFAULT_STORAGE_MODE


def _account_name(provider: str) -> str:
    return f"{SERVICE_NAME}.{provider}"


def _validate_provider(provider: str) -> bool:
    return provider in PROVIDERS


def _keychain_get_api_key(provider: str) -> Optional[str]:
    try:
        return keyring.get_password(SERVICE_NAME, _account_name(provider))
    except Exception:
        return None


def _keychain_set_api_key(provider: str, api_key: str) -> bool:
    try:
        keyring.set_password(SERVICE_NAME, _account_name(provider), api_key)
        return True
    except Exception as e:
        logger.error(f"Failed to store API key in keychain: {e}")
        return False


def _keychain_delete_api_key(provider: str) -> bool:
    try:
        keyring.delete_password(SERVICE_NAME, _account_name(provider))
        return True
    except keyring.errors.PasswordDeleteError:
        return True
    except Exception as e:
        logger.error(f"Failed to delete API key from keychain: {e}")
        return False


def _credentials_file() -> Path:
    from .config import CONFIG_DIR
    return CONFIG_DIR / PASSFILE_NAME


def _ensure_credentials_file_permissions(path: Path) -> None:
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


def _derive_fernet_key(passphrase: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    kdf = Scrypt(
        salt=salt,
        length=32,
        n=2**14,
        r=8,
        p=1,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def _encrypt_keys(keys: dict[str, str], passphrase: str, salt: bytes) -> str:
    from cryptography.fernet import Fernet

    payload = json.dumps(keys, sort_keys=True).encode("utf-8")
    fernet = Fernet(_derive_fernet_key(passphrase, salt))
    return fernet.encrypt(payload).decode("utf-8")


def _decrypt_keys(ciphertext: str, passphrase: str, salt: bytes) -> dict[str, str]:
    from cryptography.fernet import Fernet

    fernet = Fernet(_derive_fernet_key(passphrase, salt))
    decoded = fernet.decrypt(ciphertext.encode("utf-8"))
    data = json.loads(decoded.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Credential store format is invalid")
    return {
        provider: str(value)
        for provider, value in data.items()
        if provider in PROVIDERS and isinstance(value, str) and value
    }


def _read_passphrase_store() -> Optional[dict]:
    path = _credentials_file()
    if not path.exists():
        return None
    _ensure_credentials_file_permissions(path)
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None


def _write_passphrase_store(keys: dict[str, str], passphrase: str, rotate_salt: bool = False) -> bool:
    path = _credentials_file()
    _ensure_credentials_file_permissions(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = _read_passphrase_store()
    if existing and not rotate_salt:
        salt_b64 = existing.get("salt")
    else:
        salt_b64 = None

    if not salt_b64:
        salt_b64 = base64.b64encode(os.urandom(16)).decode("utf-8")

    salt = base64.b64decode(salt_b64.encode("utf-8"))
    ciphertext = _encrypt_keys(keys, passphrase, salt)
    payload = {
        "version": 1,
        "kdf": "scrypt",
        "salt": salt_b64,
        "ciphertext": ciphertext,
    }

    temp_path: Optional[Path] = None
    try:
        # Write to a temp file first, then atomically replace.
        # This avoids partial writes and keeps file permissions restrictive.
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=".credentials.",
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
        _ensure_credentials_file_permissions(path)
        return True
    except Exception as e:
        logger.error(f"Failed to write encrypted credential store: {e}")
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        return False


def _load_passphrase_store(passphrase: str) -> dict[str, str]:
    payload = _read_passphrase_store()
    if payload is None:
        return {}

    salt_b64 = payload.get("salt")
    ciphertext = payload.get("ciphertext")
    if not isinstance(salt_b64, str) or not isinstance(ciphertext, str):
        raise ValueError("Credential store is corrupted")

    salt = base64.b64decode(salt_b64.encode("utf-8"))
    return _decrypt_keys(ciphertext, passphrase, salt)


def _persist_passphrase_cache() -> bool:
    if _session_passphrase is None:
        return False
    return _write_passphrase_store(_session_passphrase_cache, _session_passphrase)


def is_passphrase_supported() -> bool:
    try:
        import cryptography  # noqa: F401
        return True
    except Exception:
        return False


def has_passphrase_store() -> bool:
    return _credentials_file().exists()


def is_passphrase_unlocked() -> bool:
    return _session_passphrase is not None


def get_unlocked_passphrase() -> Optional[str]:
    """
    Return the active passphrase for the current app session, if unlocked.

    This is used by other local encryption helpers that share the passphrase
    unlock lifecycle without re-prompting the user.
    """
    return _session_passphrase


def unlock_passphrase_store(passphrase: str) -> tuple[bool, str]:
    """
    Unlock the passphrase store for the current app session.

    If the encrypted store does not exist, this creates it.
    """
    global _session_passphrase, _session_passphrase_cache

    if not passphrase:
        return False, "Passphrase cannot be empty"
    if not is_passphrase_supported():
        return False, "cryptography package is required for passphrase mode"

    try:
        if has_passphrase_store():
            keys = _load_passphrase_store(passphrase)
            _session_passphrase = passphrase
            _session_passphrase_cache = keys
            return True, "Credential store unlocked"

        # New store
        _session_passphrase = passphrase
        _session_passphrase_cache = {}
        if _persist_passphrase_cache():
            return True, "Credential store created and unlocked"

        _session_passphrase = None
        _session_passphrase_cache = {}
        return False, "Failed to create encrypted credential store"
    except Exception as e:
        _session_passphrase = None
        _session_passphrase_cache = {}
        return False, f"Unlock failed: {str(e)[:120]}"


def lock_passphrase_store() -> None:
    """Lock passphrase credentials for this app session."""
    global _session_passphrase, _session_passphrase_cache
    _session_passphrase = None
    _session_passphrase_cache = {}


def change_passphrase(current_passphrase: str, new_passphrase: str) -> tuple[bool, str]:
    """Change passphrase for encrypted credentials."""
    global _session_passphrase

    if not new_passphrase:
        return False, "New passphrase cannot be empty"
    if not has_passphrase_store():
        ok, message = unlock_passphrase_store(new_passphrase)
        return ok, "Credential store created" if ok else message

    ok, message = unlock_passphrase_store(current_passphrase)
    if not ok:
        return False, message

    # Re-wrap history encryption key first so encrypted history remains readable
    # after the credential passphrase changes.
    try:
        from .encryption import has_encryption_key, rewrap_history_key

        if has_encryption_key():
            ok, history_msg = rewrap_history_key(current_passphrase, new_passphrase)
            if not ok:
                return False, history_msg or "Failed to update history encryption passphrase"
    except Exception as e:
        return False, f"Failed to update history encryption passphrase: {str(e)[:80]}"

    if not _write_passphrase_store(_session_passphrase_cache, new_passphrase, rotate_salt=True):
        return False, "Failed to update passphrase"

    _session_passphrase = new_passphrase
    return True, "Passphrase updated"


def get_storage_mode(config=None) -> str:
    """
    Get active credential storage mode.

    Reads from provided config instance or loads config from disk.
    """
    if config is None:
        try:
            from .config import Config
            config = Config.load()
        except Exception:
            return DEFAULT_STORAGE_MODE
    return _normalize_mode(getattr(config, "credential_storage_mode", DEFAULT_STORAGE_MODE))


def get_storage_mode_label(mode: Optional[str] = None) -> str:
    mode = _normalize_mode(mode or get_storage_mode())
    labels = {
        "passphrase": "Passphrase (Encrypted Local)",
        "keychain": "macOS Keychain",
        "none": "Session Only (No Persistence)",
    }
    return labels.get(mode, "Passphrase (Encrypted Local)")


def is_storage_unlocked(mode: Optional[str] = None) -> bool:
    mode = _normalize_mode(mode or get_storage_mode())
    if mode == "passphrase":
        return is_passphrase_unlocked()
    return True


def _get_api_key_for_mode(provider: str, mode: str) -> Optional[str]:
    if mode == "keychain":
        return _keychain_get_api_key(provider)
    if mode == "none":
        return _session_none_cache.get(provider)
    # passphrase
    if not is_passphrase_unlocked():
        return None
    return _session_passphrase_cache.get(provider)


def _set_api_key_for_mode(provider: str, api_key: str, mode: str) -> bool:
    if mode == "keychain":
        return _keychain_set_api_key(provider, api_key)
    if mode == "none":
        _session_none_cache[provider] = api_key
        return True

    # passphrase
    if not is_passphrase_unlocked():
        logger.warning("Cannot store API key: passphrase store is locked")
        return False
    _session_passphrase_cache[provider] = api_key
    return _persist_passphrase_cache()


def _delete_api_key_for_mode(provider: str, mode: str) -> bool:
    if mode == "keychain":
        return _keychain_delete_api_key(provider)
    if mode == "none":
        _session_none_cache.pop(provider, None)
        return True

    # passphrase
    if not is_passphrase_unlocked():
        logger.warning("Cannot delete API key: passphrase store is locked")
        return False
    _session_passphrase_cache.pop(provider, None)
    return _persist_passphrase_cache()


def export_api_keys(mode: Optional[str] = None) -> tuple[bool, dict[str, str], str]:
    """
    Export all configured API keys for the given mode.

    Returns:
        (success, keys, message)
    """
    target_mode = _normalize_mode(mode or get_storage_mode())

    if target_mode == "passphrase" and has_passphrase_store() and not is_passphrase_unlocked():
        return False, {}, "Passphrase store is locked"

    keys: dict[str, str] = {}
    for provider in PROVIDERS:
        key = _get_api_key_for_mode(provider, target_mode)
        if key:
            keys[provider] = key

    return True, keys, ""


def clear_api_keys(mode: Optional[str] = None) -> tuple[bool, str]:
    """Clear API keys for the given mode."""
    target_mode = _normalize_mode(mode or get_storage_mode())

    if target_mode == "passphrase":
        if has_passphrase_store() and not is_passphrase_unlocked():
            return False, "Passphrase store is locked"
        _session_passphrase_cache.clear()
        if is_passphrase_unlocked():
            if _persist_passphrase_cache():
                return True, ""
            return False, "Failed to update encrypted store"
        return True, ""

    if target_mode == "none":
        _session_none_cache.clear()
        return True, ""

    # keychain
    failed_providers: list[str] = []
    for provider in PROVIDERS:
        if not _keychain_delete_api_key(provider):
            failed_providers.append(provider)
    if failed_providers:
        providers = ", ".join(sorted(failed_providers))
        return False, f"Failed to remove keychain entries for: {providers}"
    return True, ""


def import_api_keys(
    keys: dict[str, str],
    mode: Optional[str] = None,
    replace: bool = False,
) -> tuple[bool, str]:
    """
    Import API keys into the given mode.

    Args:
        keys: Mapping provider -> key
        mode: Storage mode (defaults to current)
        replace: Remove existing keys in target mode before import
    """
    target_mode = _normalize_mode(mode or get_storage_mode())

    if replace:
        ok, msg = clear_api_keys(target_mode)
        if not ok:
            return False, msg

    if target_mode == "passphrase" and not is_passphrase_unlocked():
        return False, "Passphrase store is locked"

    for provider, key in keys.items():
        if provider not in PROVIDERS or not key:
            continue
        if not _set_api_key_for_mode(provider, key, target_mode):
            return False, f"Failed to store key for {provider}"

    return True, ""


def get_api_key(provider: str) -> Optional[str]:
    """
    Retrieve API key for a provider from active storage mode.
    """
    if not _validate_provider(provider):
        return None
    mode = get_storage_mode()
    return _get_api_key_for_mode(provider, mode)


def set_api_key(provider: str, api_key: str) -> bool:
    """
    Store API key in active storage mode.
    """
    if not _validate_provider(provider) or not api_key:
        return False
    mode = get_storage_mode()
    return _set_api_key_for_mode(provider, api_key, mode)


def delete_api_key(provider: str) -> bool:
    """
    Delete API key from active storage mode.
    """
    if not _validate_provider(provider):
        return False
    mode = get_storage_mode()
    return _delete_api_key_for_mode(provider, mode)


def get_configured_providers() -> list[str]:
    """
    Return providers with keys configured in active storage mode.
    """
    providers = []
    for provider in PROVIDERS:
        if get_api_key(provider):
            providers.append(provider)
    return providers


def mask_api_key(api_key: str) -> str:
    """Return a masked version of the API key for display."""
    if not api_key or len(api_key) < 12:
        return "****"
    return f"{api_key[:8]}...{api_key[-4:]}"


def validate_api_key(provider: str, api_key: str) -> tuple[bool, str]:
    """
    Validate an API key by making a test API call.

    Args:
        provider: "openai", "gemini", or "anthropic"
        api_key: The API key to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if provider == "openai":
        return _validate_openai_key(api_key)
    elif provider == "gemini":
        return _validate_gemini_key(api_key)
    elif provider == "anthropic":
        return _validate_anthropic_key(api_key)
    else:
        return False, f"Unknown provider: {provider}"


def _validate_openai_key(api_key: str) -> tuple[bool, str]:
    """Validate OpenAI API key by listing models."""
    try:
        import requests
        response = requests.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10
        )
        if response.status_code == 200:
            return True, ""
        elif response.status_code == 401:
            return False, "Invalid API key"
        elif response.status_code == 403:
            return False, "API key lacks permissions"
        elif response.status_code == 429:
            # Rate limited but key is valid
            return True, ""
        else:
            return False, f"API error: {response.status_code}"
    except requests.exceptions.Timeout:
        return False, "Connection timed out"
    except requests.exceptions.ConnectionError:
        return False, "Could not connect to OpenAI"
    except ImportError:
        # requests not installed, skip validation
        return True, ""
    except Exception as e:
        return False, f"Validation error: {str(e)[:50]}"


def _validate_gemini_key(api_key: str) -> tuple[bool, str]:
    """Validate Gemini API key by listing models."""
    try:
        import requests
        response = requests.get(
            "https://generativelanguage.googleapis.com/v1/models",
            headers={"x-goog-api-key": api_key},
            timeout=10
        )
        if response.status_code == 200:
            return True, ""
        elif response.status_code == 400:
            data = response.json()
            error_msg = data.get("error", {}).get("message", "Invalid request")
            if "api key" in error_msg.lower():
                return False, "Invalid API key"
            return False, error_msg[:50]
        elif response.status_code == 403:
            return False, "API key not authorized"
        elif response.status_code == 429:
            # Rate limited but key is valid
            return True, ""
        else:
            return False, f"API error: {response.status_code}"
    except requests.exceptions.Timeout:
        return False, "Connection timed out"
    except requests.exceptions.ConnectionError:
        return False, "Could not connect to Google AI"
    except ImportError:
        # requests not installed, skip validation
        return True, ""
    except Exception as e:
        return False, f"Validation error: {str(e)[:50]}"


def _validate_anthropic_key(api_key: str) -> tuple[bool, str]:
    """Validate Anthropic API key by making a test request."""
    try:
        import requests
        response = requests.get(
            "https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01"
            },
            timeout=10
        )
        if response.status_code == 200:
            return True, ""
        elif response.status_code == 401:
            return False, "Invalid API key"
        elif response.status_code == 403:
            return False, "API key lacks permissions"
        elif response.status_code == 429:
            # Rate limited but key is valid
            return True, ""
        else:
            return False, f"API error: {response.status_code}"
    except requests.exceptions.Timeout:
        return False, "Connection timed out"
    except requests.exceptions.ConnectionError:
        return False, "Could not connect to Anthropic"
    except ImportError:
        # requests not installed, skip validation
        return True, ""
    except Exception as e:
        return False, f"Validation error: {str(e)[:50]}"
