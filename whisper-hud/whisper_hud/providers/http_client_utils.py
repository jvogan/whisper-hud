"""Hardened HTTP client helpers for cloud providers."""

from __future__ import annotations

import httpx

OPENAI_API_BASE_URL = "https://api.openai.com/v1"
OPENAI_WEBSOCKET_BASE_URL = "wss://api.openai.com/v1"
ANTHROPIC_API_BASE_URL = "https://api.anthropic.com"


def build_hardened_http_client(timeout_seconds: float) -> httpx.Client:
    """Return an HTTP client that ignores ambient proxy/base-url environment."""
    return httpx.Client(
        timeout=timeout_seconds,
        follow_redirects=False,
        trust_env=False,
    )
