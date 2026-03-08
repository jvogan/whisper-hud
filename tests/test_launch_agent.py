"""Tests for launch-at-login path selection."""

from pathlib import Path
from unittest.mock import patch


class TestLaunchAgent:
    """Tests for trusted executable resolution."""

    def test_get_app_executable_uses_current_executable(self):
        """Launch-agent setup should not resolve WhisperHUD via PATH."""
        from whisper_hud.launch_agent import get_app_executable

        with patch("whisper_hud.launch_agent.sys.executable", "/usr/local/bin/python3"):
            assert get_app_executable() == str(Path("/usr/local/bin/python3"))

    def test_get_launch_agent_plist_uses_module_launch_for_python(self):
        """Interpreter-based installs should run the module explicitly."""
        from whisper_hud.launch_agent import get_launch_agent_plist

        with patch("whisper_hud.launch_agent.get_app_executable", return_value="/usr/bin/python3"):
            with patch("whisper_hud.launch_agent._is_standalone_executable", return_value=False):
                plist = get_launch_agent_plist()

        assert plist["ProgramArguments"] == ["/usr/bin/python3", "-m", "whisper_hud"]

    def test_get_launch_agent_plist_uses_bundle_binary_directly(self):
        """Standalone app builds should register the app executable itself."""
        from whisper_hud.launch_agent import get_launch_agent_plist

        executable = "/Applications/WhisperHUD.app/Contents/MacOS/WhisperHUD"
        with patch("whisper_hud.launch_agent.get_app_executable", return_value=executable):
            with patch("whisper_hud.launch_agent._is_standalone_executable", return_value=True):
                plist = get_launch_agent_plist()

        assert plist["ProgramArguments"] == [executable]
