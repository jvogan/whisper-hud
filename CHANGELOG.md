# Changelog

All notable changes to WhisperHUD will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
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

- Multiple transcription providers, including OpenAI Whisper, Google Gemini, Apple Speech Recognition, Local Whisper, and a dedicated OpenAI Realtime low-latency dictation mode with live microphone chunk forwarding and batch fallback.
- Translation support across local and cloud providers, including Ollama, OpenAI, Gemini, Apple Translate, and Anthropic, with streaming translation output and support for 15+ target languages.
- A first-run setup wizard with step progress, API key validation, dark mode support, and the ability to skip translation setup.
- A configurable floating widget with click-to-record behavior, multiple sizes, appearance themes, custom icon modes, tooltip help, recording animation, and processing indicators.
- A live HUD and streaming display with audio level visualization, status messaging, word counts, and real-time transcription and translation output.
- Flexible output flows including auto-paste, paste target locking for specific apps and terminals, clipboard restoration, and transcription history.
- macOS release and distribution plumbing, including DMG packaging, PyPI publishing support, Sparkle auto-update integration, release automation, secret scanning, and dependency review workflows.
- Broader automated coverage for provider integrations, menu construction, recording dispatch, setup wizard behavior, HUD behavior, floating widget behavior, and installation smoke testing.

### Changed

- Reorganized menus and settings flows to better separate transcription, translation, setup, and appearance controls.
- Improved the appearance editor and button rendering so widget customization is easier to preview and validate.
- Extended streaming panel behavior with longer auto-dismiss timing, manual dismissal, and active-screen placement.
- Improved HUD placement and dismissal behavior for multi-display setups and click-to-dismiss error states.
- Hardened startup helpers, configuration handling, credential storage flows, public-release UX, documentation, and release readiness materials for the public launch.
- Strengthened the test and CI pipeline with coverage artifact uploads, broader regression coverage, and Ruff adoption in CI.
- Tightened OpenAI Realtime product copy, provider wiring, and supported model scope to match the v1 runtime.

### Fixed

- Fixed GitHub Actions workflows that referenced the nonexistent `actions/checkout@v6` release.
- Fixed `paste.py` newline escaping in direct text insertion paths.
- Fixed Apple Silicon detection in the local Whisper provider.
- Fixed missing error handling in Gemini transcription calls.
- Fixed duplicate AppleScript escaping logic by consolidating it behind one shared implementation.
- Fixed a recorder race where `recording=True` could be observed inconsistently across threads.
- Fixed repeated provider discovery work by caching `TranscriptionManager.get_available_providers()`.
- Fixed keychain validator import ordering so configuration checks fail predictably.
- Fixed whitespace-only transcription handling and added click-to-dismiss error HUD behavior.
- Fixed installation UX gaps with progress feedback, error trapping, and a smoke test in `install.sh`.
- Fixed test runner interruptions caused by unexpected macOS Keychain prompts by enforcing mocked keychain access in tests.

### Removed

- Removed duplicate internal AppleScript escape helper paths in favor of a single shared escaping implementation.

---

## Future Releases

Features under consideration for future releases:
- PyPI distribution
- Homebrew formula
- Additional transcription providers
- Voice commands
- Custom prompt templates
