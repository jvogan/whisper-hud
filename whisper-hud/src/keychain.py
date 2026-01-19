"""
Secure API key storage using macOS Keychain.

Keys are stored with service name "whisper-hud" and account names like:
- whisper-hud.openai
- whisper-hud.gemini
"""

import keyring
from typing import Optional

SERVICE_NAME = "whisper-hud"


def get_api_key(provider: str) -> Optional[str]:
    """
    Retrieve API key for a provider from Keychain.

    Args:
        provider: "openai" or "gemini"

    Returns:
        API key string or None if not set
    """
    try:
        return keyring.get_password(SERVICE_NAME, f"{SERVICE_NAME}.{provider}")
    except Exception:
        return None


def set_api_key(provider: str, api_key: str) -> bool:
    """
    Store API key for a provider in Keychain.

    Args:
        provider: "openai" or "gemini"
        api_key: The API key to store

    Returns:
        True if successful
    """
    try:
        keyring.set_password(SERVICE_NAME, f"{SERVICE_NAME}.{provider}", api_key)
        return True
    except Exception as e:
        print(f"Failed to store API key: {e}")
        return False


def delete_api_key(provider: str) -> bool:
    """
    Remove API key for a provider from Keychain.

    Args:
        provider: "openai" or "gemini"

    Returns:
        True if successful or key didn't exist
    """
    try:
        keyring.delete_password(SERVICE_NAME, f"{SERVICE_NAME}.{provider}")
        return True
    except keyring.errors.PasswordDeleteError:
        return True  # Key didn't exist, that's fine
    except Exception as e:
        print(f"Failed to delete API key: {e}")
        return False


def get_configured_providers() -> list[str]:
    """
    Return list of providers that have API keys configured.

    Returns:
        List of provider names, e.g., ["openai", "gemini"]
    """
    providers = []
    for provider in ["openai", "gemini"]:
        if get_api_key(provider):
            providers.append(provider)
    return providers


def mask_api_key(api_key: str) -> str:
    """Return a masked version of the API key for display."""
    if not api_key or len(api_key) < 12:
        return "****"
    return f"{api_key[:8]}...{api_key[-4:]}"
