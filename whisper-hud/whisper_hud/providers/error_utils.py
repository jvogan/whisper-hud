"""Helpers for turning provider exceptions into safe user-facing messages."""

from __future__ import annotations


def extract_status_code(error: Exception) -> int | None:
    """Best-effort extraction of HTTP-like status codes from SDK exceptions."""
    for attr in ("status_code", "code"):
        value = getattr(error, attr, None)
        if isinstance(value, int):
            return value
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            pass

    response = getattr(error, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int):
        return value
    try:
        if value is not None:
            return int(value)
    except (TypeError, ValueError):
        pass

    return None


def build_provider_error_message(provider_name: str, action: str, error: Exception) -> str:
    """Return a sanitized error message without leaking backend payloads."""
    details = (str(error) or "").strip().lower()
    status_code = extract_status_code(error)

    if status_code == 408 or "timed out" in details or "timeout" in details:
        reason = "request timed out"
    elif _looks_like_network_error(details):
        reason = "network error"
    elif status_code == 401 or "unauthorized" in details or "invalid api key" in details:
        reason = "invalid API key"
    elif status_code == 403 or "forbidden" in details or "not authorized" in details:
        reason = "access denied"
    elif status_code == 404 and "model" in details:
        reason = "unsupported model"
    elif status_code == 429 or "rate limit" in details or "quota" in details or "too many requests" in details:
        reason = "rate limited"
    elif status_code is not None and status_code >= 500:
        reason = "service unavailable"
    else:
        reason = "unexpected error"

    return f"{provider_name} {action} failed: {reason}"


def _looks_like_network_error(details: str) -> bool:
    network_markers = (
        "network",
        "connection",
        "connect",
        "dns",
        "socket",
        "ssl",
        "tls",
        "transport",
        "unreachable",
        "temporarily unavailable",
        "reset by peer",
        "broken pipe",
    )
    return any(marker in details for marker in network_markers)
