```
               ╭─────────────────────────────────────╮
               │                                     │
               │   ░▒▓  W H I S P E R H U D  ▓▒░    │
               │                                     │
               │      ┌─────────────────────┐        │
               │      │  ◉ ─ ─ ─ ╱╲ ─ ─ ─   │        │
               │      │    ░░▒▒▓▓██▓▓▒▒░░   │        │
               │      └─────────────────────┘        │
               │                                     │
               │   voice → text, invisibly           │
               │                                     │
               ╰─────────────────────────────────────╯
```

**Hold a hotkey. Speak naturally. Text appears at your cursor.**

A lightweight macOS menu bar app for system-wide voice-to-text transcription. Uses your own API keys—no subscription required.

---

## Quick Start

```bash
git clone https://github.com/jvogan/whisper-hud.git
cd whisper-hud
./install.sh
```

The installer will set everything up for you. Then run:

```bash
cd whisper-hud && ./run.sh
```

<details>
<summary><b>Manual Installation</b></summary>

```bash
git clone https://github.com/jvogan/whisper-hud.git
cd whisper-hud/whisper-hud
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

</details>

---

## First Run Setup

| Step | Action |
|:----:|--------|
| **1** | Grant **Accessibility** permission when prompted |
|       | *System Settings → Privacy & Security → Accessibility* |
| **2** | Grant **Microphone** permission when prompted |
| **3** | Click menu bar icon → **API Keys** → Add your key |
| **4** | Hold **⌘⇧Space**, speak, release! |

---

## Features

| | |
|:--|:--|
| **Hold-to-record** | Press `Cmd+Shift+Space` anywhere to start |
| **Auto-transcribe** | Audio sent to OpenAI Whisper or Google Gemini on release |
| **Auto-paste** | Transcribed text appears instantly at your cursor |
| **Visual feedback** | Menu bar icon and optional HUD show status |
| **Auto-stop** | Optionally stop recording after silence |
| **Secure** | API keys stored in macOS Keychain, never in files |
| **Cost tracking** | See your usage and estimated costs in the menu |

---

## Usage

| Action | How |
|:-------|:----|
| Start recording | Hold `⌘⇧Space` |
| Stop & transcribe | Release the hotkey (or wait for auto-stop) |
| Click to record | Enable floating button in Settings |

The transcribed text is automatically pasted wherever your cursor is.

---

## Menu Bar Status

| Icon | Status |
|:----:|:-------|
| 🎙️ | Ready |
| 🔴 | Recording |
| ⏳ | Processing |
| ✅ | Success |
| ❌ | Error |

---

## Getting API Keys

### OpenAI (Recommended)

1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Create a new API key
3. Add billing/credits to your account

### Google Gemini

1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Create a new API key

---

## Settings

Access settings from the menu bar icon:

| Setting | Description |
|:--------|:------------|
| **Provider** | Choose between OpenAI and Google Gemini |
| **Model** | Select transcription model (affects accuracy and cost) |
| **Show floating button** | Optional click-to-record widget |
| **Show HUD overlay** | Visual feedback during recording |
| **Auto-stop on silence** | Automatically stop after you stop speaking |
| **Auto-paste** | Automatically paste transcribed text |
| **Restore clipboard** | Restore previous clipboard contents after paste |

---

## Estimated Costs

| Provider | Model | Cost |
|:---------|:------|-----:|
| OpenAI | GPT-4o Transcribe | ~$0.006/min |
| OpenAI | GPT-4o Mini Transcribe | ~$0.003/min |
| OpenAI | Whisper v2 | ~$0.006/min |
| Google | Gemini 2.0 Flash | ~$0.001/min |

*Typical usage (30 seconds of speech): $0.001 - $0.003*

---

## Security & Privacy

- **API keys** stored in macOS Keychain (encrypted, system-protected)
- **Audio** processed in memory, never saved to disk
- **Settings** stored locally in `~/.config/whisper-hud/`
- **No telemetry** or data collection

---

## Requirements

- macOS 12+ (Monterey or later)
- Python 3.11+
- OpenAI API key and/or Google AI API key

---

## Troubleshooting

<details>
<summary><b>"This process is not trusted"</b></summary>

Grant Accessibility permission:
*System Settings → Privacy & Security → Accessibility → Add Terminal/IDE*

</details>

<details>
<summary><b>"Could not open audio device"</b></summary>

Grant Microphone permission:
*System Settings → Privacy & Security → Microphone*

</details>

<details>
<summary><b>Hotkey doesn't work</b></summary>

- Make sure no other app is using `Cmd+Shift+Space`
- Check Accessibility permissions are granted

</details>

<details>
<summary><b>Transcription fails</b></summary>

Verify your API key is valid and has credits/billing enabled.

</details>

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

**Author:** Jacob Vogan
