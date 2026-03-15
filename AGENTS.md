# WhisperHUD — Agent Operating Guide

> **Current date:** March 15, 2026. Use this when selecting library versions or checking API docs.

## Project Layout

```
transcribe_1/                    ← repo root (run commands from here)
├── whisper-hud/
│   └── whisper_hud/             ← THE MAIN PACKAGE (all source code)
│       ├── app.py               ← main orchestrator (rumps.App), ~1400 lines
│       ├── providers/            ← transcription + translation providers
│       └── ...
├── tests/                       ← pytest test suite
├── pyproject.toml               ← project metadata, deps, tool config
└── install.sh / run.sh          ← user-facing scripts
```

The package lives in `whisper-hud/whisper_hud/` (a subdirectory), NOT the repo root.
`pyproject.toml` uses `where = ["whisper-hud"]` for package discovery.
Editable installs must be run from the repo root.

## Dev Commands

```bash
# Install (editable + dev deps)
pip install -e ".[dev]"

# Run tests
python -m pytest tests/ -x -q

# Lint
python -m flake8 whisper-hud/whisper_hud --max-line-length=120 --ignore=E501,W503

# Format check
python -m black whisper-hud/whisper_hud tests --line-length=120 --check

# Syntax check
python -m py_compile whisper-hud/whisper_hud/main.py
```

## Key Patterns and Conventions

### Provider pattern
All transcription providers extend `TranscriptionProvider` ABC from `providers/base.py`.
All translation providers extend `TranslationProvider` ABC from `providers/translation/base.py`.
Each provider has: `transcribe()` / `translate()`, `is_configured()`, `get_models()`, `set_model()`.
Providers are lazily instantiated by `TranscriptionManager` and `TranslationManager`.

### Config pattern
Single `Config` dataclass in `config.py`, serialized to JSON at `~/.config/whisper-hud/config.json`.
Directory permissions `0700`, file `0600`. Use `config.save()` and `Config.load()`.

### Credential storage pattern
Three modes in `keychain.py`: passphrase (default, scrypt+Fernet), keychain (macOS Keychain via `keyring`), session-only (in-memory dict).
API keys are NEVER stored in plaintext on disk in the default mode.

### Test mock pattern
All macOS frameworks are mocked in `tests/conftest.py`:
- `mock_appkit` fixture patches `AppKit`, `Cocoa`, `Quartz`, `PyObjCTools`, `Speech`, `rumps`
- `mock_config` fixture patches `CONFIG_FILE` and `CONFIG_DIR` to temp dirs
- `mock_keychain` fixture patches keyring operations
- `sample_audio_bytes` provides test audio data
- Tests use `sys.path.insert(0, ...)` in conftest to find the package

Never import real PyObjC/AppKit/rumps in tests — always use the mocked versions.

### Paste pattern
`paste.py` uses clipboard + AppleScript `Cmd+V` simulation.
`paste_targets.py` routes text to specific apps, tmux sessions, or iTerm2.
AppleScript strings must be properly escaped — see `_escape_applescript_string()`.

## Risk Areas — Read Before Changing

### `app.py` (HIGH RISK)
The main orchestrator at ~1400 lines. Contains recording state machine, menu building, settings dialogs, all UI callbacks. Changes here affect everything. The `ActiveTranscriptionTurn` state machine uses threading locks — respect the lock ordering.

### `keychain.py` and `encryption.py` (SECURITY CRITICAL)
Credential storage and history encryption. Module-level globals hold session secrets. Never log API keys. Never weaken the scrypt parameters. Always use `secure_delete()` for temp files containing sensitive data.

### `paste.py` AppleScript escaping (SECURITY)
`_escape_applescript_string()` must escape `\`, `"`, and control characters. Incomplete escaping can cause AppleScript injection. The `insert_text_direct()` path is limited to <50 chars but still must be safe.

### `recorder.py` threading
`self.recording` flag is read from multiple threads. The `_check_silence()` callback runs on the audio thread. Respect the existing lock patterns.

### PyObjC main thread requirement
All AppKit/Cocoa UI calls must happen on the main thread. Background threads must use `AppHelper.callAfter()` or `rumps.Timer` to dispatch UI updates.

## CI

CI runs on `macos-latest` via GitHub Actions:
- `lint.yml`: flake8 + py_compile
- `test.yml`: pytest matrix (Python 3.11, 3.12)
- `secret-scan.yml`: gitleaks
- `dependency-review.yml`: on PRs

**Note:** CI is currently broken due to `actions/checkout@v6` references (v6 does not exist). This is being fixed.

## What NOT to Do

- Do not make live API calls (OpenAI, Gemini, Anthropic) in tests
- Do not import real `rumps`, `AppKit`, `pynput`, or `sounddevice` in tests
- Do not modify `keychain.py` scrypt parameters or encryption algorithms
- Do not add `print()` statements — use `logger.debug/info/warning/error`
- Do not change the Config dataclass field names (breaks existing user configs)
- Do not use `git rm` in workspaces (workspace git is synthetic, not upstream)
- Do not run `pip install` inside the Codex sandbox (no network; deps are pre-installed)
