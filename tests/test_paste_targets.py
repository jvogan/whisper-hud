"""Tests for paste target clipboard handling."""

from unittest.mock import MagicMock, call, patch


class TestPasteTargets:
    """Tests for targeted paste behavior."""

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
