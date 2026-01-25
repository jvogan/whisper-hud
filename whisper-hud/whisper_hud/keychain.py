"""
Secure API key storage using macOS Keychain.

Keys are stored with service name "whisper-hud" and account names like:
- whisper-hud.openai
- whisper-hud.gemini
"""

import keyring
from typing import Optional

from .logging_config import get_logger

logger = get_logger("keychain")

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
        logger.error(f"Failed to store API key: {e}")
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
        logger.error(f"Failed to delete API key: {e}")
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


def validate_api_key(provider: str, api_key: str) -> tuple[bool, str]:
    """
    Validate an API key by making a test API call.

    Args:
        provider: "openai" or "gemini"
        api_key: The API key to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if provider == "openai":
        return _validate_openai_key(api_key)
    elif provider == "gemini":
        return _validate_gemini_key(api_key)
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
            f"https://generativelanguage.googleapis.com/v1/models?key={api_key}",
            timeout=10
        )
        if response.status_code == 200:
            return True, ""
        elif response.status_code == 400:
            data = response.json()
            error_msg = data.get("error", {}).get("message", "Invalid request")
            if "API key" in error_msg.lower():
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
