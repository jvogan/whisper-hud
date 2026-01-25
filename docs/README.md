# WhisperHUD Documentation

Welcome to the WhisperHUD documentation!

## Quick Links

| Document | Description |
|----------|-------------|
| [API Providers](./API_PROVIDERS.md) | Compare transcription & translation providers |
| [Keyboard Shortcuts](./KEYBOARD_SHORTCUTS.md) | Hotkey reference and customization |
| [Troubleshooting](./TROUBLESHOOTING.md) | Common issues and solutions |
| [Release Checklist](./RELEASE_CHECKLIST.md) | Steps to go public on GitHub |
| [Developer Notes](./DEVELOPER.md) | Local dev setup and checks |
| [Branding & Assets](./BRANDING.md) | Banners, demo GIFs, and attribution |
| [FAQ](./FAQ.md) | Quick answers |
| [Support Matrix](./SUPPORT_MATRIX.md) | Platform/provider requirements |
| [Glossary](./GLOSSARY.md) | Key terms |

## Getting Started

1. **Install**: See the main [README](../README.md) for installation
2. **Configure**: Run the setup wizard on first launch
3. **Use**: Hold your hotkey, speak, release to transcribe

## Configuration

Settings are stored in `~/.config/whisper-hud/config.json`.

API keys are securely stored in the macOS Keychain.

## Optional Extras

Enable local transcription engines with extras:

```bash
pip install -e ".[whisper-local]"   # Whisper Local
pip install -e ".[parakeet]"        # Parakeet (Apple Silicon)
```

## Need Help?

- Check [Troubleshooting](./TROUBLESHOOTING.md) for common issues
- Open a [GitHub Issue](https://github.com/jvogan/whisper-hud/issues)
- See [CONTRIBUTING](../CONTRIBUTING.md) to help improve WhisperHUD
