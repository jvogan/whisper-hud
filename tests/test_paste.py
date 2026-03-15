"""Tests for paste/text insertion functionality."""

import subprocess
from unittest.mock import patch, MagicMock, call


class TestPaste:
    """Tests for paste module functions."""

    def test_escape_applescript_string_escapes_required_characters(self):
        """AppleScript escaping should cover quotes, slashes, and control characters."""
        from whisper_hud.paste import escape_applescript_string

        value = 'backslash \\\\ quote " newline \n carriage \r tab \t'

        assert escape_applescript_string(value) == 'backslash \\\\\\\\ quote \\" newline \\n carriage \\r tab \\t'

    def test_escape_applescript_string_strips_null_bytes(self):
        """Null bytes should be removed before building AppleScript source."""
        from whisper_hud.paste import escape_applescript_string

        assert escape_applescript_string("a\x00b") == "ab"

    def test_escape_applescript_string_preserves_backslash_quote_sequence(self):
        """Backslashes immediately before quotes should be escaped exactly once."""
        from whisper_hud.paste import escape_applescript_string

        assert escape_applescript_string('\\"') == '\\\\\\"'

    def test_as_applescript_string_expression_uses_character_ids_for_unicode(self):
        """Unicode text should avoid raw source literals that can fail in osascript."""
        from whisper_hud.paste import _as_applescript_string_expression

        expression = _as_applescript_string_expression("A🙂漢א")

        assert expression == (
            '"A" & (character id 55357) & (character id 56898) & (character id 28450) & (character id 1488)'
        )

    def test_as_applescript_string_expression_strips_null_bytes(self):
        """Null bytes should not appear in AppleScript expressions."""
        from whisper_hud.paste import _as_applescript_string_expression

        assert _as_applescript_string_expression("a\x00b") == '"ab"'

    def test_as_applescript_string_expression_chunks_long_literals(self):
        """Long AppleScript literals should be split into safe-sized chunks."""
        from whisper_hud.paste import _as_applescript_string_expression, MAX_APPLESCRIPT_LITERAL_LENGTH

        expression = _as_applescript_string_expression("a" * (MAX_APPLESCRIPT_LITERAL_LENGTH + 1))

        assert expression == f'"{"a" * MAX_APPLESCRIPT_LITERAL_LENGTH}" & "a"'

    def test_get_accessibility_error_message(self):
        """Test that accessibility error message is informative."""
        from whisper_hud.paste import get_accessibility_error_message

        message = get_accessibility_error_message()

        assert "Accessibility" in message
        assert "System Settings" in message or "System Preferences" in message
        assert "WhisperHUD" in message

    @patch("subprocess.run")
    def test_check_accessibility_permission_granted(self, mock_run):
        """Test accessibility check when permission is granted."""
        from whisper_hud.paste import check_accessibility_permission

        mock_run.return_value = MagicMock(returncode=0)

        result = check_accessibility_permission()
        assert result is True

    @patch("subprocess.run")
    def test_check_accessibility_permission_denied(self, mock_run):
        """Test accessibility check when permission is denied."""
        from whisper_hud.paste import check_accessibility_permission

        mock_run.return_value = MagicMock(returncode=1)

        result = check_accessibility_permission()
        assert result is False

    @patch("subprocess.run")
    def test_get_frontmost_app(self, mock_run):
        """Test getting frontmost application name."""
        from whisper_hud.paste import get_frontmost_app

        mock_run.return_value = MagicMock(returncode=0, stdout="Safari\n")

        result = get_frontmost_app()
        assert result == "Safari"

    @patch("subprocess.run")
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

    @patch("whisper_hud.paste.time.sleep")
    @patch("whisper_hud.paste.pyperclip.copy")
    @patch("whisper_hud.paste.pyperclip.paste")
    @patch("whisper_hud.paste.subprocess.run")
    def test_insert_text_pastes_and_restores_clipboard(
        self,
        mock_run,
        mock_paste,
        mock_copy,
        _mock_sleep,
    ):
        """Clipboard paste should restore the original clipboard contents."""
        from whisper_hud.paste import insert_text

        mock_run.return_value = MagicMock(returncode=0, stderr=b"")
        mock_paste.side_effect = ["original clipboard", "hello world"]

        result = insert_text("hello world")

        assert result is True
        assert mock_run.call_count == 1
        assert mock_run.call_args.args[0][0:2] == ["osascript", "-e"]
        assert 'keystroke "v" using command down' in mock_run.call_args.args[0][2]
        assert mock_copy.call_args_list == [call("hello world"), call("original clipboard")]

    @patch("whisper_hud.paste.time.sleep")
    @patch("whisper_hud.paste.pyperclip.copy")
    @patch("whisper_hud.paste.pyperclip.paste")
    @patch("whisper_hud.paste.subprocess.run")
    def test_insert_text_restores_clipboard_when_paste_raises(
        self,
        mock_run,
        mock_paste,
        mock_copy,
        _mock_sleep,
    ):
        """Clipboard restore should still run when the paste command raises."""
        from whisper_hud.paste import insert_text

        mock_run.side_effect = RuntimeError("paste failed")
        mock_paste.side_effect = ["original clipboard", "hello world"]

        result = insert_text("hello world")

        assert result is False
        assert mock_copy.call_args_list == [call("hello world"), call("original clipboard")]

    @patch("whisper_hud.paste.time.sleep")
    @patch("whisper_hud.paste.pyperclip.copy")
    @patch("whisper_hud.paste.pyperclip.paste")
    @patch("whisper_hud.paste.subprocess.run")
    def test_insert_text_returns_false_when_applescript_fails_without_restoring_changed_clipboard(
        self,
        mock_run,
        mock_paste,
        mock_copy,
        _mock_sleep,
    ):
        """Failed paste should not overwrite clipboard content that changed in the meantime."""
        from whisper_hud.paste import insert_text

        mock_run.return_value = MagicMock(returncode=1, stderr=b"permission denied")
        mock_paste.side_effect = ["original clipboard", "user copied something else"]

        result = insert_text("hello world")

        assert result is False
        mock_copy.assert_called_once_with("hello world")

    @patch("whisper_hud.paste.time.sleep")
    @patch("whisper_hud.paste.pyperclip.copy")
    @patch("whisper_hud.paste.pyperclip.paste")
    @patch("whisper_hud.paste.subprocess.run")
    def test_insert_text_target_app_activation_and_focus_restore(
        self,
        mock_run,
        mock_paste,
        mock_copy,
        _mock_sleep,
    ):
        """Targeted paste should activate the app, paste, then restore focus."""
        from whisper_hud.paste import insert_text

        mock_paste.side_effect = ["original clipboard", "hello world"]
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=0, stderr=b""),
            MagicMock(returncode=0),
        ]

        with patch("whisper_hud.paste.get_frontmost_app", return_value="Safari"):
            result = insert_text("hello world", target_app="Notes", return_focus=True)

        assert result is True
        assert mock_copy.call_args_list[0].args == ("hello world",)
        assert mock_copy.call_args_list[1].args == ("original clipboard",)
        assert mock_run.call_count == 3
        assert mock_run.call_args_list[0].args[0][2] == 'tell application "Notes" to activate'
        assert 'keystroke "v" using command down' in mock_run.call_args_list[1].args[0][2]
        assert mock_run.call_args_list[2].args[0][2] == 'tell application "Safari" to activate'

    @patch("subprocess.run")
    def test_insert_text_direct_preserves_newlines(self, mock_run):
        """Test direct insertion uses AppleScript newline expressions."""
        from whisper_hud.paste import insert_text_direct

        mock_run.return_value = MagicMock(returncode=0)

        result = insert_text_direct("line 1\nline 2")

        assert result is True
        mock_run.assert_called_once()
        script = mock_run.call_args.args[0][2]
        assert 'keystroke "line 1" & (ASCII character 10) & "line 2"' in script

    @patch("whisper_hud.paste.subprocess.run")
    def test_insert_text_direct_short_text_uses_keystroke_script(self, mock_run):
        """Short direct insertion should use AppleScript keystrokes."""
        from whisper_hud.paste import insert_text_direct

        mock_run.return_value = MagicMock(returncode=0)

        result = insert_text_direct('say "hi"')

        assert result is True
        script = mock_run.call_args.args[0][2]
        assert 'keystroke "say \\"hi\\""' in script

    @patch("whisper_hud.paste.subprocess.run")
    def test_insert_text_direct_unicode_uses_character_ids(self, mock_run):
        """Unicode direct insertion should use character ids instead of raw literals."""
        from whisper_hud.paste import insert_text_direct

        mock_run.return_value = MagicMock(returncode=0)

        result = insert_text_direct("🙂")

        assert result is True
        script = mock_run.call_args.args[0][2]
        assert "keystroke (character id 55357) & (character id 56898)" in script

    @patch("whisper_hud.paste.insert_text", return_value=True)
    def test_insert_text_direct_long_text_falls_back_to_clipboard(self, mock_insert_text):
        """Long direct insertion should fall back to the clipboard-based path."""
        from whisper_hud.paste import insert_text_direct

        result = insert_text_direct("x" * 51)

        assert result is True
        mock_insert_text.assert_called_once_with("x" * 51, restore_clipboard=True)

    @patch("whisper_hud.paste.subprocess.run", side_effect=RuntimeError("boom"))
    def test_insert_text_direct_failure_returns_false(self, _mock_run):
        """Direct insertion should fail closed when AppleScript execution raises."""
        from whisper_hud.paste import insert_text_direct

        result = insert_text_direct("hello")

        assert result is False

    @patch("subprocess.run")
    def test_open_accessibility_settings_success(self, mock_run):
        """Opening accessibility settings should return True on success."""
        from whisper_hud.paste import open_accessibility_settings

        mock_run.return_value = MagicMock(returncode=0)

        result = open_accessibility_settings()

        assert result is True
        assert mock_run.call_args.args[0][0:2] == ["osascript", "-e"]

    @patch("subprocess.run")
    def test_open_accessibility_settings_falls_back_to_open(self, mock_run):
        """Fallback open command should be used when AppleScript launch fails."""
        from whisper_hud.paste import open_accessibility_settings

        mock_run.side_effect = [RuntimeError("osascript failed"), MagicMock()]

        result = open_accessibility_settings()

        assert result is True
        assert mock_run.call_args_list[1].args[0] == [
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        ]

    @patch("subprocess.run")
    def test_open_accessibility_settings_returns_false_when_fallback_fails(self, mock_run):
        """Opening accessibility settings should return False if both launch paths fail."""
        from whisper_hud.paste import open_accessibility_settings

        mock_run.side_effect = [RuntimeError("osascript failed"), RuntimeError("open failed")]

        result = open_accessibility_settings()

        assert result is False

    @patch("whisper_hud.paste.time.sleep")
    @patch("whisper_hud.paste.pyperclip.copy")
    @patch("whisper_hud.paste.pyperclip.paste")
    @patch("whisper_hud.paste.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=5))
    def test_insert_text_timeout_returns_false(
        self,
        _mock_run,
        mock_paste,
        mock_copy,
        _mock_sleep,
    ):
        """Timeouts should fail closed and restore the clipboard."""
        from whisper_hud.paste import insert_text

        mock_paste.side_effect = ["original clipboard", "hello world"]
        result = insert_text("hello world")

        assert result is False
        assert mock_copy.call_args_list[0].args == ("hello world",)
        assert mock_copy.call_args_list[1].args == ("original clipboard",)
