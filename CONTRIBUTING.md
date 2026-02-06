# Contributing to WhisperHUD

Thank you for your interest in contributing to WhisperHUD! This document provides guidelines for contributing to the project.

## Getting Started

### Development Setup

See `docs/DEVELOPER.md` for local setup, lint, and test commands.

1. **Clone the repository**
   ```bash
   git clone https://github.com/jvogan/whisper-hud.git
   cd whisper-hud
   ```

2. **Run the install script**
   ```bash
   ./install.sh
   ```

3. **Activate the virtual environment**
   ```bash
   cd whisper-hud
   source venv/bin/activate
   ```

4. **Run the app in development mode**
   ```bash
   python -m whisper_hud.main
   ```

### Requirements

- macOS 12+ (Monterey or later)
- Python 3.11+
- API key only if you use cloud providers (OpenAI, Gemini, or Anthropic)

## How to Contribute

### Reporting Bugs

Before submitting a bug report:
1. Check existing issues to avoid duplicates
2. Use the bug report template
3. Include system info (macOS version, Python version)
4. Provide steps to reproduce the issue

### Suggesting Features

1. Check if the feature has already been requested
2. Use the feature request template
3. Explain the use case and why it would be valuable

### Submitting Pull Requests

1. **Fork the repository** and create your branch from `main`
2. **Make your changes** following the code style guidelines below
3. **Test your changes** thoroughly
4. **Submit a pull request** using the PR template

## Code Style

### Python

- Follow PEP 8 style guidelines
- Use descriptive variable and function names
- Add docstrings to functions and classes
- Keep functions focused and reasonably sized

### Commits

- Use clear, descriptive commit messages
- Start with a verb (Add, Fix, Update, Remove, etc.)
- Reference issue numbers when applicable

**Examples:**
```
Add auto-stop silence detection feature
Fix hotkey not responding after sleep
Update README with translation docs
```

## Project Structure

```
whisper-hud/                # Repository root
├── whisper-hud/
│   └── whisper_hud/        # Python package
│       ├── app.py          # Main application logic
│       ├── main.py         # Entry point
│       ├── config.py       # Settings management
│       ├── recorder.py     # Audio recording
│       ├── transcribe.py   # Provider orchestration
│       ├── translate.py    # Translation orchestration
│       └── providers/      # Transcription & translation providers
├── tests/                  # Test suite
├── docs/                   # Documentation
├── assets/                 # Icons, banners, character packs
├── scripts/                # Build & release scripts
├── install.sh
├── run.sh
└── pyproject.toml
```

## Testing

Before submitting a PR, please test:

1. **Basic functionality**
   - Recording works with hotkey
   - Transcription completes successfully
   - Text pastes correctly

2. **Settings**
   - Changes persist after restart
   - API key storage works

3. **Edge cases**
   - App behavior when API key is missing
   - Handling of network errors
   - Behavior with very short/long recordings

## Questions?

If you have questions about contributing, feel free to open an issue with the question label.

## License

By contributing to WhisperHUD, you agree that your contributions will be licensed under the MIT License.
