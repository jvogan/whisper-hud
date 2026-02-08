# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in WhisperHUD, please report it by:

1. **GitHub Issues** - For non-sensitive security issues, open a GitHub issue with the `security` label
2. **Private Reporting** - For sensitive vulnerabilities, use [GitHub's private vulnerability reporting](https://github.com/jvogan/whisper-hud/security/advisories/new)

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

- **API Keys**: Use passphrase-encrypted local storage (default) unless you explicitly want Keychain behavior
- **Never commit secrets**: Ensure API keys are never committed to version control
- **Keep dependencies updated**: Run `pip install --upgrade -r requirements.txt` periodically
- **Review permissions**: The app requires microphone access - grant only when needed

## Credential Prompt Behavior (No-Surprise Rules)

- **Keychain prompts appear only in Keychain mode**
- **Passphrase prompts appear only when cloud credentials are needed and currently locked**
- **History encryption does not trigger Keychain prompts**
- **Passphrase unlock is session-scoped**: unlock once per app session; relock on quit/manual lock

## Known Security Considerations

- Audio is processed locally by default (when using local Whisper)
- When using cloud providers (OpenAI, Gemini, Anthropic), audio/text is sent to their servers
- Local providers may use short‑lived temp audio files, which are securely deleted after processing
- API keys are never hard-coded and are stored via the selected credential mode
- Passphrase mode stores encrypted credentials at `~/.config/whisper-hud/credentials.enc`
- Transcription history encryption uses a locally stored wrapped key tied to passphrase unlock (not Keychain)
- Passphrase mode derives encryption keys with scrypt (`N=16384, r=8, p=1`) and per-store random salt
- Changing passphrase rotates credential-store salt and re-wraps history-encryption key material
- Sensitive files use restrictive permissions: config dir `0700`, files `0600`
- Transcription history is off by default and can be encrypted at rest if enabled

## Notes On Hashing vs Encryption

API keys cannot be stored as hash-only values because the app must recover the real key to call provider APIs.
WhisperHUD uses encryption at rest for stored keys and explicit unlock controls for in-session access.
