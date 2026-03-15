"""Tests for paste target clipboard handling."""

from unittest.mock import MagicMock, call, patch


class TestPasteTargets:
    """Tests for targeted paste behavior."""

    @patch("subprocess.run")
    def test_activate_app_uses_shared_applescript_escaping(self, mock_run):
        """App activation should escape AppleScript-sensitive characters consistently."""
        from whisper_hud.paste_targets import PasteTargetManager

        manager = PasteTargetManager()
        mock_run.return_value = MagicMock(returncode=0)

        assert manager.activate_app('Notes "Dev"\\Tab') is True
        script = mock_run.call_args.args[0][2]
        assert 'tell application "Notes \\"Dev\\"\\\\Tab"' in script

    @patch("subprocess.run")
    def test_paste_to_iterm2_uses_shared_applescript_escaping(self, mock_run):
        """iTerm2 writes should preserve escaped control characters."""
        from whisper_hud.paste_targets import PasteTargetManager

        manager = PasteTargetManager()
        mock_run.return_value = MagicMock(returncode=0, stderr=b"")

        assert manager.paste_to_iterm2('line 1\nline 2\t"quoted"\\path') is True
        script = mock_run.call_args.args[0][2]
        assert 'write text "line 1\\nline 2\\t\\"quoted\\"\\\\path" without newline' in script

    @patch("time.sleep", return_value=None)
    @patch("subprocess.run")
    @patch("pyperclip.copy")
    @patch("pyperclip.paste")
    def test_paste_to_app_restores_clipboard_only_if_unchanged(
        self,
        mock_paste,
        mock_copy,
        mock_run,
        _mock_sleep,
    ):
        """App-target paste should not clobber newer clipboard contents."""
        from whisper_hud.paste_targets import PasteTargetManager

        manager = PasteTargetManager()
        mock_run.return_value = MagicMock(returncode=0, stderr=b"")
        mock_paste.side_effect = ["original", "new clipboard value"]

        with patch.object(manager, "activate_app", return_value=True):
            assert manager.paste_to_app("hello", "Notes", return_focus=False, restore_clipboard=True) is True

        assert mock_copy.call_args_list == [call("hello")]

    @patch("time.sleep", return_value=None)
    @patch("subprocess.run")
    @patch("pyperclip.copy")
    @patch("pyperclip.paste")
    def test_paste_to_terminal_restores_clipboard_when_still_ours(
        self,
        mock_paste,
        mock_copy,
        mock_run,
        _mock_sleep,
    ):
        """Terminal-target paste should restore only when the pasted text is still on the clipboard."""
        from whisper_hud.paste_targets import PasteTargetManager

        manager = PasteTargetManager()
        mock_run.return_value = MagicMock(returncode=0, stderr=b"")
        mock_paste.side_effect = ["original", "hello"]

        assert manager.paste_to_terminal("hello") is True
        assert mock_copy.call_args_list == [call("hello"), call("original")]
