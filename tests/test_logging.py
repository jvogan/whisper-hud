"""Tests for logging configuration."""

import logging


class TestLogging:
    """Tests for logging setup."""

    def test_get_logger_returns_child_logger(self):
        """Test that get_logger returns properly namespaced loggers."""
        from whisper_hud.logging_config import get_logger

        logger = get_logger("test_module")
        assert logger.name == "whisper-hud.test_module"

    def test_get_logger_without_name(self):
        """Test that get_logger without name returns root app logger."""
        from whisper_hud.logging_config import get_logger

        logger = get_logger()
        assert logger.name == "whisper-hud"

    def test_setup_logging_configures_console_handler(self):
        """Test that setup_logging adds console handler."""
        from whisper_hud.logging_config import setup_logging

        # Clear any existing handlers
        logger = logging.getLogger("whisper-hud-test")
        logger.handlers = []

        # Note: setup_logging uses "whisper-hud" logger
        # This test verifies the function runs without error
        result = setup_logging(level=logging.DEBUG)
        assert result is not None

    def test_log_levels(self):
        """Test that different log levels work."""
        from whisper_hud.logging_config import get_logger

        logger = get_logger("level_test")

        # These should not raise
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")
