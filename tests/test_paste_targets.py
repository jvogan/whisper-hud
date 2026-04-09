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

    def test_paste_to_iterm2_uses_safe_clipboard_paste_path(self):
        """iTerm2 routing should reuse the safe activate + paste flow."""
        from whisper_hud.paste_targets import PasteTargetManager

        manager = PasteTargetManager()

        with patch.object(manager, "paste_to_app", return_value=True) as mock_paste_to_app:
            assert manager.paste_to_iterm2('line 1\nline 2\t"quoted"\\path') is True

        mock_paste_to_app.assert_called_once_with(
            'line 1\nline 2\t"quoted"\\path',
            "iTerm2",
            return_focus=True,
            restore_clipboard=True,
        )

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

    @patch("time.sleep", return_value=None)
    @patch("subprocess.run")
    @patch("pyperclip.copy")
    @patch("pyperclip.paste")
    def test_paste_to_terminal_clears_clipboard_when_snapshot_fails(
        self,
        mock_paste,
        mock_copy,
        mock_run,
        _mock_sleep,
    ):
        """If the original clipboard cannot be snapshotted, temporary text should not be left behind."""
        from whisper_hud.paste_targets import PasteTargetManager

        manager = PasteTargetManager()
        mock_run.return_value = MagicMock(returncode=0, stderr=b"")
        mock_paste.side_effect = [RuntimeError("clipboard unavailable"), "secret text"]

        assert manager.paste_to_terminal("secret text") is True
        assert mock_copy.call_args_list == [call("secret text"), call("")]

    @patch("subprocess.run")
    def test_paste_to_tmux_uses_tmux_paste_buffer_for_multiline_text(self, mock_run):
        """tmux routing should use bracketed paste instead of send-keys for untrusted text."""
        from whisper_hud.paste_targets import PasteTargetManager

        manager = PasteTargetManager()
        mock_run.side_effect = [
            MagicMock(returncode=0, stderr=b""),
            MagicMock(returncode=0, stderr=b""),
            MagicMock(returncode=0, stderr=b""),
        ]

        with patch.object(manager, "get_tmux_sessions", return_value=["dev"]):
            assert manager.paste_to_tmux("line 1\nline 2", "dev") is True

        load_call, paste_call, delete_call = mock_run.call_args_list
        buffer_name = load_call.args[0][3]
        assert load_call.args[0] == ["tmux", "load-buffer", "-b", buffer_name, "-"]
        assert load_call.kwargs["input"] == b"line 1\nline 2"
        assert paste_call.args[0] == ["tmux", "paste-buffer", "-p", "-t", "dev", "-b", buffer_name]
        assert delete_call.args[0] == ["tmux", "delete-buffer", "-b", buffer_name]
        assert buffer_name.startswith("whisperhud-paste-")
