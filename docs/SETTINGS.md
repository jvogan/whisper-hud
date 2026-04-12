# Settings

Access settings from the menu bar icon.

## Transcription

- **Provider**: Choose cloud or local providers (OpenAI, OpenAI Realtime, Gemini, Apple, Whisper Local, Parakeet)
- **Model**: Select transcription model (affects accuracy and cost)

## Recording

- **Auto-stop on silence**: Automatically stop after you stop speaking
- **Silence duration**: How long to wait before auto-stopping (1-3 seconds)

## Display

- **Show floating button**: Optional click-to-record widget
- **Widget size**: Small, medium, large, or extra-large
- **Show HUD overlay**: Visual feedback during recording
- **Streaming display**: Show live text panel during transcription

## Output

- **Auto-paste**: Automatically paste transcribed text
- **Restore clipboard**: Restore previous clipboard contents after paste
- **Play sound**: Audio feedback on completion
- **Save history**: Store recent transcriptions locally (disabled by default)

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
