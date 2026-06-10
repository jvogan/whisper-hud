# Settings

Access settings from the menu bar icon.

## Transcription

- **Provider**: Choose cloud or local providers (OpenAI, OpenAI Realtime, Gemini, Apple (Built-in), Whisper Local, Parakeet, Qwen3 ASR, Apple Speech (Advanced))
- **Model**: Select transcription model (affects accuracy and cost)
- **Transcribe Audio File…**: Transcribe an existing audio/video file with the current provider. Lives in **Providers & Keys**. See [Transcribe Audio File](#transcribe-audio-file) below.

### Providers & Keys

This submenu holds provider selection, per-provider model picks, API keys, and the file-transcription action.

- New local providers (Apple Silicon / newer macOS only — see the [provider guide](API_PROVIDERS.md)):
  - **Qwen3 ASR**: On-device MLX, 52 languages. Apple Silicon only; install the `qwen3-asr` extra.
  - **Apple Speech (Advanced)**: macOS 26+ on-device SpeechAnalyzer. Free, fast; needs the bundled Swift helper built once.

### Transcribe Audio File…

Pick an audio or video file (wav, mp3, m4a, aac, aiff/aif, caf, flac, mp4, mov, m4v) and transcribe it with your current provider. Files up to ~2 hours are supported. Your custom vocabulary and text replacements are applied; voice commands, AI Cleanup, paste, and auto-send are deliberately **not** (a file is not live dictation). The result is copied to the clipboard and added to history (when history is enabled and Private Mode is off).

## Recording

- **Auto-stop on silence**: Automatically stop after you stop speaking
- **Silence duration**: How long to wait before auto-stopping (1-3 seconds)

## Display

- **Show floating button**: Optional click-to-record widget
- **Widget size**: Small, medium, large, or extra-large
- **Show HUD overlay**: Visual feedback during recording
- **Streaming display**: Show live text panel during transcription
- **Character pack**: Themed icon set for the floating widget (Settings → Appearance → Character Pack). Built-in packs: Panda, Pixel Adventurer, Handheld '89, CRT Terminal. The newer packs animate per state, play short per-state sounds (when **Play sound** is on), and flash a one-shot success/error animation before reverting to idle.

## Dictation Intelligence

A post-transcription text pipeline. All features are off by default and additive.

- **Voice Commands**: Recognize spoken editing commands such as "scratch that", "new line", and "press enter" (built-in commands plus any custom ones you add).
- **Dictation Modes**: Per-app profiles that control formatting, vocabulary, and auto-send. Built-in modes are always available when enabled; some (e.g. a chat-style mode) auto-send a Return after pasting. You can add custom modes that match specific apps.
- **AI Cleanup (Local)**: Tidy transcripts (capitalization, punctuation, filler removal) using a **local** Ollama model. This is **local-only** — transcripts go to a loopback Ollama server on `127.0.0.1` and are **never** sent to any cloud service, and a guardrail rejects any rewrite that paraphrases your words (it falls back to the raw text). Requires Ollama running locally; the menu shows whether it is reachable.
- **Vocabulary & Replacements**: Edit your custom vocabulary, text replacements, custom voice commands, and custom modes via a JSON file.
  - **Edit in editor…**: Opens `~/.config/whisper-hud/dictation.json` (a commented template is created on first use).
  - **Reload from file**: Re-reads that file into the app after you save it.

**Custom vocabulary** biases transcription toward names/jargon you list. It is threaded into every provider that can use it (up to 200 terms): OpenAI/Whisper Local as a prompt/initial-prompt glossary, Gemini as a hint line, Apple Speech (Advanced) as contextual hints. Parakeet and Qwen3 ASR ignore it (their APIs expose no biasing).

## Output

- **Auto-paste**: Automatically paste transcribed text
- **Restore clipboard**: Restore previous clipboard contents after paste
- **Play sound**: Audio feedback on completion
- **Save history**: Store recent transcriptions locally (disabled by default; default cap 50 entries)
- **History Size**: Choose how many entries to retain — 20, 50, 100, or 200 (History & Stats → History Size)
- **View History… / Search History…**: Open a read-only rendering of your saved transcriptions (Search filters by text/provider/source). The view is written to a user-only (0600) temporary file and opened in your default editor; that plaintext copy lives on disk only briefly (about 60 seconds) and is securely deleted after the grace window, on quit, and during a startup sweep. History entries record source (mic/file), model, duration, and mode. Honors **history encryption** and **Private Mode**.

## Privacy & Security

- **API key storage**: Passphrase-encrypted local store (default), macOS Keychain, or session-only
- **Passphrase lock/unlock**: Unlock once per app session when using passphrase mode

## Translation

- **Provider**: Apple (local), Ollama (local), Gemini, OpenAI, or Anthropic
- **Enable translation**: Translate transcriptions before pasting
- **Source language**: Auto detect (default) or explicit source language
- **Target language**: Language to translate into (50+ supported)
- **Translation model**: Choose an Ollama size (4B/12B/27B) or a cloud model

### Enabling Translation

1. Go to Settings > Translation
2. Select a provider:
   - **Apple (local)**: Uses Apple's Translation framework (macOS 26+). For dev builds, run `./scripts/build-apple-translate.sh` to compile the helper.
   - **Ollama (local)**: WhisperHUD can install/start Ollama and download a model (~3-18GB)
   - **Gemini/OpenAI/Anthropic (cloud)**: Requires API key, no local model download
3. Enable translation
4. Select source language (or keep **Auto detect**) and target language
5. Transcribe as usual - text will be translated before pasting

### Ollama Translation Models

| Model | Size | Speed | Quality |
|-------|------|-------|---------|
| translategemma-4b | ~3GB | Fast | Good |
| translategemma-12b | ~8GB | Medium | Better |
| translategemma-27b | ~18GB | Slower | Best |

### Supported Languages

Language support varies by provider. Common options include:
Arabic, Chinese, Dutch, French, German, Hindi, Indonesian, Italian, Japanese, Korean, Portuguese, Russian, Spanish, Turkish, Vietnamese

## Streaming Display

Enable "Streaming display" in Settings to see a live panel showing:
- Transcription text as it's recognized
- Translation text as it's generated (when translation enabled)

The panel auto-dismisses after text is pasted.
With **OpenAI Realtime**, the transcription panel updates while you are still speaking. Other providers continue to stream after recording stops.
