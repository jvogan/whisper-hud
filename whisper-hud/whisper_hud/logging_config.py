"""
Logging configuration for WhisperHUD.

Provides a centralized logging setup with appropriate handlers
for both file and console output.
"""

import logging
import os
from pathlib import Path


def setup_logging(
    level: int = logging.INFO,
    log_file: bool = False,
    log_dir: Path = None
) -> logging.Logger:
    """
    Configure logging for WhisperHUD.

    Args:
        level: Logging level (default: INFO)
        log_file: Whether to also log to a file
        log_dir: Directory for log files (default: ~/.config/whisper-hud/logs/)

    Returns:
        The root logger for the application
    """
    # Create the logger
    logger = logging.getLogger("whisper-hud")

    # Avoid adding handlers multiple times
    if logger.handlers:
        return logger

    if os.environ.get("WHISPER_HUD_DEBUG"):
        level = logging.DEBUG
        log_file = True

    if os.environ.get("WHISPER_HUD_LOG_FILE"):
        log_file = True

    logger.setLevel(level)

    # Console handler with simple format
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)

    # Use a simple format for console output
    console_format = logging.Formatter(
        "%(levelname)s: %(message)s"
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        if log_dir is None:
            log_dir = Path.home() / ".config" / "whisper-hud" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        _tighten_permissions(log_dir, 0o700)

        file_handler = logging.FileHandler(
            log_dir / "whisper-hud.log",
            encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)

        file_format = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
        _tighten_permissions(log_dir / "whisper-hud.log", 0o600)

    return logger


def get_logger(name: str = None) -> logging.Logger:
    """
    Get a logger for a specific module.

    Args:
        name: Module name (e.g., "app", "recorder", "paste")

    Returns:
        Logger instance
    """
    if name:
        return logging.getLogger(f"whisper-hud.{name}")
    return logging.getLogger("whisper-hud")


def _tighten_permissions(path: Path, mode: int) -> None:
    """Best-effort chmod for logs/configs on multi-user systems."""
    try:
        os.chmod(path, mode)
    except Exception:
        pass


# Convenience: set up basic logging on import
# This ensures logging is configured even if setup_logging() isn't called explicitly
_root_logger = logging.getLogger("whisper-hud")
if not _root_logger.handlers:
    # Default setup: INFO level, console only
    setup_logging(level=logging.INFO)
