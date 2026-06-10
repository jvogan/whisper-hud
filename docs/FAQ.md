# FAQ

## Do I need an API key?

Only if you use cloud providers (OpenAI batch, OpenAI Realtime, Gemini, or Anthropic).  
Local providers (Apple Built-in, Apple Speech Advanced, Whisper Local, Parakeet, Qwen3 ASR, Ollama translation) work without API keys.

OpenAI Realtime reuses the same OpenAI API key as the batch OpenAI provider.

## What is the easiest first-time setup?

Use this path:
1. Run setup wizard
2. Choose **Local**
3. Choose **Apple (Built-in)**
4. Finish and hold `Cmd+Shift+Space` to record

That path needs no API key, no passphrase, and no model download.

## Where are API keys stored?

WhisperHUD supports three modes:
- Passphrase-encrypted local store (default)
- macOS Keychain
- Session-only memory (cleared on quit)

You can change this in **Privacy & Security → API Key Storage**.

## Why did macOS ask for Keychain access?

That happens only in **macOS Keychain** storage mode.

If you want no Keychain prompts:
1. Open **Privacy & Security → API Key Storage**
2. Switch to **Passphrase (Encrypted Local)** (recommended) or **Session Only**
3. Re-enter keys if prompted after switching

## Does passphrase unlock stay active while the app is open?

Yes. In passphrase mode, unlock once and it stays unlocked for the current app session.
It relocks on quit or when you manually choose **Lock API key store**.

## Does history encryption use Keychain?

No. History encryption uses the passphrase session and local encrypted metadata.
It does not trigger Keychain on its own.

## What does “0600 permissions” mean?

`0600` means only your macOS user account can read/write the file.
Other local users on the same machine cannot read it.

WhisperHUD uses user-only permissions for sensitive files in `~/.config/whisper-hud/`.

## Is my passphrase stored?

Not as plain text. WhisperHUD stores encrypted key material and uses a key derived from your passphrase (scrypt + salt) to unlock it during your session.

## Why not hash API keys instead of encrypting them?

Hashing is one-way, so the app could not recover the real key to call OpenAI/Gemini/Anthropic APIs.
For usable API keys, encryption at rest is required (plus unlock controls).

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
pip install -e ".[whisper-local]"   # Whisper Local
pip install -e ".[parakeet]"        # Parakeet (Apple Silicon)
pip install -e ".[qwen3-asr]"       # Qwen3 ASR (Apple Silicon)
```

Apple Speech (Advanced) needs no pip extra, but requires macOS 26+ and a one-time Swift helper build (`./scripts/build-speechanalyzer.sh`, also run automatically by `./run.sh`).
