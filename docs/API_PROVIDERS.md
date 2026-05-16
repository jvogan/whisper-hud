# Transcription Providers Guide

WhisperHUD supports multiple transcription providers, each with different trade-offs.

## Quick Comparison

| Provider | Speed | Accuracy | Privacy | Cost | Setup |
|----------|-------|----------|---------|------|-------|
| **OpenAI** | Fast | Excellent | Cloud | ~$0.006/min | API key |
| **OpenAI Realtime** | Very Fast | Excellent | Cloud | OpenAI Realtime pricing | Same OpenAI API key |
| **Gemini** | Very Fast | Excellent | Cloud | Free tier available | API key |
| **Apple** | Fast | Good | On-device | Free | None |
| **Whisper Local** | Slow | Excellent | On-device | Free | Model download |
| **Parakeet (Apple Silicon)** | Very Fast | Good | On-device | Free | Model download |

---

## Cloud Providers

### OpenAI (Batch)

**Models available:**
- `gpt-4o-mini-transcribe` - OpenAI's currently recommended general transcription model
- `gpt-4o-mini-transcribe-2025-12-15` - Pinned mini transcription snapshot
- `gpt-4o-transcribe` - Higher-cost batch transcription
- `gpt-4o-transcribe-diarize` - Adds speaker diarization
- `whisper-1` - Original Whisper model

**Setup:**
1. Get API key from [platform.openai.com](https://platform.openai.com/api-keys)
2. Enter key in WhisperHUD → API Keys → OpenAI

**Pricing:** ~$0.006 per minute of audio

**Pros:**
- Excellent accuracy
- Fast processing
- Supports many languages

**Cons:**
- Requires internet
- Audio sent to cloud
- Costs money

---

### OpenAI Realtime

Uses OpenAI's Realtime WebSocket transcription flow for low-latency dictation.

**Models available:**
- `gpt-realtime-whisper` - Lowest-latency live dictation option (default)
- `gpt-4o-mini-transcribe` - Lower-cost transcription model retained for compatibility
- `gpt-4o-transcribe` - Higher accuracy transcription model retained for compatibility

**Setup:**
1. Get API key from [platform.openai.com](https://platform.openai.com/api-keys)
2. Enter key in WhisperHUD → API Keys → OpenAI
3. Select **OpenAI Realtime** as your transcription provider

**Pricing:** Uses OpenAI Realtime transcription pricing rather than the batch minute estimates above.

**Pros:**
- True live partial transcripts while you are still speaking
- Uses the same OpenAI key as batch transcription
- Good fit for push-to-talk dictation

**Cons:**
- Requires internet
- Audio sent to cloud
- More moving parts than batch upload
- v1 focuses on transcription only; no diarization or cleanup pass

---

### Google Gemini

**Models available:**
- `gemini-3.1-flash-lite` - Current stable default for direct audio transcription
- `gemini-3-flash-preview` - Newer preview balanced model
- `gemini-3.1-pro-preview` - Latest preview quality model
- `gemini-2.5-flash` - Legacy stable balanced option
- `gemini-2.5-pro` - Legacy stable quality option
- `gemini-2.5-flash-lite` - Legacy stable speed option

**Setup:**
1. Get API key from [aistudio.google.com](https://aistudio.google.com/apikey)
2. Enter key in WhisperHUD → API Keys → Gemini

**Pricing:** Free tier available (rate limited), then pay-per-use

**Pros:**
- Often faster than OpenAI
- Free tier for light use
- Excellent multilingual support

**Cons:**
- Requires internet
- Audio sent to cloud
- Rate limits on free tier

---

## Local Providers

### Apple Speech Recognition

Uses macOS built-in speech recognition (same as Siri dictation).

**Setup:** None required - works out of the box!

**Supported languages:** Set via `apple_model` in config (e.g., `en-US`, `es-ES`)

**Pros:**
- No setup required
- Free
- Fast
- Completely private (on-device)

**Cons:**
- Accuracy varies by language
- Limited language support compared to Whisper
- No custom vocabulary

---

### Local Whisper

Run OpenAI's Whisper model locally on your Mac.

**Models available:**
| Model | Size | VRAM | Quality |
|-------|------|------|---------|
| `tiny` | 75 MB | ~1 GB | Basic |
| `base` | 142 MB | ~1 GB | Good |
| `small` | 466 MB | ~2 GB | Better |
| `medium` | 1.5 GB | ~5 GB | Great |
| `large-v3` | 3 GB | ~10 GB | Best |
| `large-v3-turbo` | 1.6 GB | ~6 GB | Best (faster) |

**Setup:**
1. Install the local engine:
   ```bash
   pip install -e ".[whisper-local]"
   ```
2. Select Local Whisper as provider
3. Choose a model size
4. Wait for model download (first time only)

**Pros:**
- Completely private
- No internet required
- Free after download
- Excellent accuracy (large models)

**Cons:**
- Slower than cloud
- Requires disk space for models
- First transcription triggers download

---

### Parakeet (Apple Silicon)

Parakeet is an Apple Silicon-optimized local model (via `parakeet-mlx`).

**Models available:**
- `parakeet-tdt-0.6b-v3` - Multilingual (25 European languages)

**Setup:**
```bash
pip install -e ".[parakeet]"
```
Then select **Parakeet** in WhisperHUD. The model downloads on first use.

**Pros:**
- Very fast on Apple Silicon
- Runs locally (no cloud)
- Free after download

**Cons:**
- Apple Silicon only
- Limited language support compared to Whisper

---

## Choosing a Provider

### For best accuracy
→ **OpenAI** (`gpt-4o-transcribe`), **OpenAI Realtime** (`gpt-4o-transcribe`), or **Local Whisper** (`large-v3-turbo`)

### For privacy
→ **Apple** or **Local Whisper**

### For speed
→ **OpenAI Realtime**, **Gemini**, or **Apple**

### For free usage
→ **Apple** (unlimited) or **Gemini** (free tier) or **Local Whisper**

### For offline use
→ **Apple** or **Local Whisper**

---

## Translation Providers

After transcription, you can optionally translate to another language.

| Provider | Speed | Quality | Privacy | Cost |
|----------|-------|---------|---------|------|
| **Apple** | Fast | Good | Local | Free |
| **Ollama** | Medium | Good | Local | Free |
| **Gemini** | Fast | Excellent | Cloud | Free tier |
| **OpenAI** | Fast | Excellent | Cloud | Paid |
| **Anthropic** | Fast | Excellent | Cloud | Paid |

### Ollama (Local Translation)

Uses TranslateGemma models running locally:
- `translategemma:4b` - Fast, good quality
- `translategemma:12b` - Better quality
- `translategemma:27b` - Best quality, slow

**Setup:**
```bash
brew install ollama
ollama serve  # Start server (WhisperHUD can auto-start this)
```

### Cloud Translation

Cloud translation uses API keys and model-specific defaults with compatibility fallbacks.

#### OpenAI Translation

- API: **Responses API** (not Chat Completions)
- Models:
  - `gpt-5.4-pro` (highest quality)
  - `gpt-5.4` (quality)
  - `gpt-5.4-mini` (balanced, default)
  - `gpt-5.4-nano` (speed)
- Notes:
  - Older aliases and dated snapshots are normalized to current GPT-5.4 slugs.
  - If unavailable, WhisperHUD falls back to the configured default model.

#### Gemini Translation

- Models:
  - `gemini-3.1-flash-lite` (current stable default)
  - `gemini-3.1-pro-preview` (latest preview quality)
  - `gemini-3-flash-preview` (newer preview balanced)
  - `gemini-2.5-flash` (legacy stable balanced)
  - `gemini-2.5-pro` (legacy stable quality)
  - `gemini-2.5-flash-lite` (legacy stable speed)
- Notes:
  - Older Gemini 3 preview aliases are normalized to current Gemini 3.1 preview IDs where possible.
  - If a preview ID is unavailable, WhisperHUD automatically retries with `gemini-3.1-flash-lite`.

#### Anthropic Translation

- Models:
  - `claude-sonnet-4-6` (balanced, default)
  - `claude-haiku-4-5` (speed)
  - `claude-opus-4-6` (quality)
- Notes:
  - Historical Opus IDs are normalized to current aliases.
  - If a selected model alias is rejected, WhisperHUD retries with default Sonnet.

Use the same API keys as transcription where applicable (Gemini/OpenAI). Anthropic requires its own API key.
Enable translation in settings, then choose provider/model/source/target language.

### Apple (Local Translation)

Uses Apple's Translation framework (macOS 26+). For dev builds, run:
```bash
./scripts/build-apple-translate.sh
```
