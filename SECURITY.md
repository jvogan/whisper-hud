# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in WhisperHUD, please report it by:

1. **GitHub Issues** - For non-sensitive security issues, open a GitHub issue with the `security` label
2. **Private Reporting** - For sensitive vulnerabilities, use GitHub's private vulnerability reporting feature if enabled, or contact the maintainer directly

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| Latest  | :white_check_mark: |
| Older   | :x:                |

Only the latest version receives security updates. Please keep your installation up to date.

## Security Best Practices

When using WhisperHUD:

- **API Keys**: Store API keys in macOS Keychain (the app does this automatically via `keyring`)
- **Never commit secrets**: Ensure API keys are never committed to version control
- **Keep dependencies updated**: Run `pip install --upgrade -r requirements.txt` periodically
- **Review permissions**: The app requires microphone access - grant only when needed

## Known Security Considerations

- Audio is processed locally by default (when using local Whisper)
- When using cloud providers (OpenAI, Gemini, Anthropic), audio/text is sent to their servers
- Local providers may use short‑lived temp audio files, which are securely deleted after processing
- API keys are stored securely in macOS Keychain, not in plain text files
- Transcription history is off by default and can be encrypted at rest if enabled
