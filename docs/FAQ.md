# FAQ

## Do I need an API key?

Only if you use cloud providers (OpenAI or Gemini). Local providers (Apple, Whisper Local, Parakeet) work without keys.

## Why does the hotkey not work?

WhisperHUD needs Accessibility permission:
System Settings → Privacy & Security → Accessibility.

## Why doesn’t the microphone work?

Grant Microphone permission:
System Settings → Privacy & Security → Microphone.

## Is my audio saved?

No. Audio is processed in memory. Cloud providers receive audio/text only when selected.

## Is my data private?

Local providers keep data on‑device. Cloud providers receive audio/text when selected.

## Is history stored?

History is disabled by default. If enabled, recent transcriptions are saved locally in `~/.config/whisper-hud/`.

## Is Accessibility permission safe?

Accessibility allows apps to control your Mac. Only grant it to trusted apps and remove access if you no longer use WhisperHUD.

## How do I use local engines?

Install extras in your venv:

```bash
pip install -e ".[whisper-local]"
pip install -e ".[parakeet]"
```
