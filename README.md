# WhisperHUD

A lightweight macOS menu bar app for system-wide voice-to-text transcription. Hold a hotkey, speak, and your words appear at your cursor. Uses your own API keys—no subscription required.

## Features

- **Hold-to-record**: Press `Cmd+Shift+Space` anywhere to start recording
- **Auto-transcribe**: Audio is sent to OpenAI Whisper or Google Gemini on release
- **Auto-paste**: Transcribed text appears instantly at your cursor
- **Visual feedback**: Menu bar icon and optional HUD show recording/processing status
- **Auto-stop**: Optionally stop recording automatically after silence
- **Secure**: API keys stored in macOS Keychain, never in files
- **Cost tracking**: See your usage and estimated costs in the menu

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/whisper-hud.git
cd whisper-hud

# Create virtual environment
cd whisper-hud
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the app
python -m src.main
```

## First Run Setup

1. **Grant Accessibility access** when prompted (System Settings → Privacy & Security → Accessibility)
   - Required for global hotkey detection and text pasting
2. **Grant Microphone access** when prompted
3. **Add your API key**: Click the menu bar icon → API Keys → Select provider
4. **Start using**: Hold `Cmd+Shift+Space`, speak, release

## Getting API Keys

### OpenAI (Recommended)
1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Create a new API key
3. Add billing/credits to your account

### Google Gemini
1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Create a new API key

## Usage

| Action | How |
|--------|-----|
| Start recording | Hold `Cmd+Shift+Space` |
| Stop & transcribe | Release the hotkey (or wait for auto-stop) |
| Click to record | Enable floating button in Settings |

The transcribed text is automatically pasted wherever your cursor is.

## Menu Bar Icons

| Icon | Status |
|------|--------|
| 🎙️ | Ready |
| 🔴 | Recording |
| ⏳ | Processing |
| ✅ | Success |
| ❌ | Error |

## Settings

Access settings from the menu bar icon:

- **Provider**: Choose between OpenAI and Google Gemini
- **Model**: Select transcription model (affects accuracy and cost)
- **Show floating button**: Optional click-to-record widget
- **Show HUD overlay**: Visual feedback during recording
- **Auto-stop on silence**: Automatically stop after you stop speaking
- **Auto-paste**: Automatically paste transcribed text
- **Restore clipboard**: Restore previous clipboard contents after paste

## Estimated Costs

| Provider | Model | Cost |
|----------|-------|------|
| OpenAI | GPT-4o Transcribe | ~$0.006/min |
| OpenAI | GPT-4o Mini Transcribe | ~$0.003/min |
| OpenAI | Whisper v2 | ~$0.006/min |
| Google | Gemini 2.0 Flash | ~$0.001/min |

Typical usage (30 seconds of speech): $0.001 - $0.003

## Security

- **API keys** are stored in macOS Keychain (encrypted, system-protected)
- **Audio** is processed in memory and never saved to disk
- **Settings** are stored locally in `~/.config/whisper-hud/`
- **No telemetry** or data collection

## Requirements

- macOS 12+ (Monterey or later)
- Python 3.11+
- OpenAI API key and/or Google AI API key

## Troubleshooting

### "This process is not trusted"
Grant Accessibility permission: System Settings → Privacy & Security → Accessibility → Add Terminal/IDE

### "Could not open audio device"
Grant Microphone permission: System Settings → Privacy & Security → Microphone

### Hotkey doesn't work
Make sure no other app is using `Cmd+Shift+Space`. Check Accessibility permissions.

### Transcription fails
Verify your API key is valid and has credits/billing enabled.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Author

Jacob Vogan
