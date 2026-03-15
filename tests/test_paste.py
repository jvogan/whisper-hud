"""Tests for paste/text insertion functionality."""

from unittest.mock import patch, MagicMock


class TestPaste:
    """Tests for paste module functions."""

    def test_escape_applescript_string_escapes_required_characters(self):
        """AppleScript escaping should cover quotes, slashes, and control characters."""
        from whisper_hud.paste import escape_applescript_string

        value = 'backslash \\\\ quote " newline \n carriage \r tab \t'

        assert escape_applescript_string(value) == 'backslash \\\\\\\\ quote \\" newline \\n carriage \\r tab \\t'

    def test_get_accessibility_error_message(self):
        """Test that accessibility error message is informative."""
        from whisper_hud.paste import get_accessibility_error_message

        message = get_accessibility_error_message()

        assert "Accessibility" in message
        assert "System Settings" in message or "System Preferences" in message
        assert "WhisperHUD" in message

    @patch('subprocess.run')
    def test_check_accessibility_permission_granted(self, mock_run):
        """Test accessibility check when permission is granted."""
        from whisper_hud.paste import check_accessibility_permission

        mock_run.return_value = MagicMock(returncode=0)

        result = check_accessibility_permission()
        assert result is True

    @patch('subprocess.run')
    def test_check_accessibility_permission_denied(self, mock_run):
        """Test accessibility check when permission is denied."""
        from whisper_hud.paste import check_accessibility_permission

        mock_run.return_value = MagicMock(returncode=1)

        result = check_accessibility_permission()
        assert result is False

    @patch('subprocess.run')
    def test_get_frontmost_app(self, mock_run):
        """Test getting frontmost application name."""
        from whisper_hud.paste import get_frontmost_app

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Safari\n"
        )

        result = get_frontmost_app()
        assert result == "Safari"

    @patch('subprocess.run')
    def test_get_frontmost_app_failure(self, mock_run):
        """Test frontmost app detection failure."""
        from whisper_hud.paste import get_frontmost_app

        mock_run.return_value = MagicMock(returncode=1)

        result = get_frontmost_app()
        assert result is None

    def test_insert_text_empty_string(self):
        """Test that inserting empty string returns False."""
        from whisper_hud.paste import insert_text

        result = insert_text("")
        assert result is False

        result = insert_text(None)
        assert result is False

    @patch('subprocess.run')
    def test_insert_text_direct_preserves_newlines(self, mock_run):
        """Test direct insertion uses AppleScript newline expressions."""
        from whisper_hud.paste import insert_text_direct

        mock_run.return_value = MagicMock(returncode=0)

        result = insert_text_direct("line 1\nline 2")

        assert result is True
        mock_run.assert_called_once()
        script = mock_run.call_args.args[0][2]
        assert 'keystroke "line 1" & (ASCII character 10) & "line 2"' in script
