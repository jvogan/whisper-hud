# Changelog

All notable changes to WhisperHUD will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Changelog Policy

- Add entries under **Unreleased** during development.
- Include a date when you cut a release.

## [Unreleased]

### Added

- Added **OpenAI Realtime** as a separate transcription provider for low-latency live dictation.
- Added live microphone chunk forwarding, Realtime session handling, and batch OpenAI fallback for failed Realtime turns.
- Added targeted tests for Realtime provider wiring, recorder chunk callbacks, and turn-state regressions.

### Changed

- Updated provider menus, setup flow, and docs to distinguish **OpenAI (batch)** from **OpenAI Realtime**.
- Raised the declared OpenAI SDK floor to the Realtime-capable generation and documented the required WebSocket dependency.
- Updated cloud-provider copy to clarify that OpenAI Realtime reuses the existing OpenAI API key.

## [1.0.0] - 2026-02-07

### Added

- **Multiple Transcription Providers**
  - OpenAI Whisper (GPT-4o Transcribe, GPT-4o Mini Transcribe, Whisper v2)
  - Google Gemini (Gemini 2.0 Flash)
  - Apple Speech Recognition (on-device, no API key required)
  - Local Whisper (on-device, multiple model sizes)

- **Translation Support**
  - Local translation via Ollama (TranslateGemma models)
  - Cloud translation via Gemini and OpenAI
  - Support for 15+ target languages
  - Streaming translation display

- **Floating Widget**
  - Click-to-record floating button
  - Multiple sizes (small, medium, large, extra-large)
  - 7 appearance themes (Default, Sunset, Ocean, Forest, Neon, Minimal, Midnight)
  - Custom icon support with shape modes (circle, alpha, subject extraction)

- **HUD Overlay**
  - Visual feedback during recording and processing
  - Audio level visualization
  - Status messages and word count

- **Streaming Display**
  - Live transcription text as it's recognized
  - Live translation text as it's generated
  - Auto-dismiss after paste

- **Recording Features**
  - Hold-to-record (push-to-talk) mode
  - Press-to-toggle recording mode
  - Customizable hotkey support
  - Auto-stop on silence detection
  - Audio level monitoring

- **Output Options**
  - Auto-paste to cursor position
  - Paste target locking (specific apps, tmux sessions, iTerm2)
  - Clipboard restoration after paste
  - Transcription history with copy support

- **Security**
  - API key storage modes: passphrase-encrypted local store (default), macOS Keychain, or session-only
  - Audio processed in memory only
  - Local translation via Ollama
  - No telemetry or data collection

- **User Experience**
  - First-run setup wizard
  - Cost tracking and usage statistics
  - Comprehensive error handling with helpful messages
  - Terminal ASCII art branding

### Technical

- Python 3.11+ required
- PyObjC for native macOS integration
- rumps for menu bar app framework
- Provider pattern for extensibility

---

## Future Releases

Features under consideration for future releases:
- PyPI distribution
- Homebrew formula
- Additional transcription providers
- Voice commands
- Custom prompt templates
