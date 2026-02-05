# Transcription Providers Guide

WhisperHUD supports multiple transcription providers, each with different trade-offs.

## Quick Comparison

| Provider | Speed | Accuracy | Privacy | Cost | Setup |
|----------|-------|----------|---------|------|-------|
| **OpenAI** | Fast | Excellent | Cloud | ~$0.006/min | API key |
| **Gemini** | Very Fast | Excellent | Cloud | Free tier available | API key |
| **Apple** | Fast | Good | On-device | Free | None |
| **Whisper Local** | Slow | Excellent | On-device | Free | Model download |
| **Parakeet (Apple Silicon)** | Very Fast | Good | On-device | Free | Model download |

---

## Cloud Providers

### OpenAI Whisper

**Models available:**
- `gpt-4o-transcribe` - Best quality, faster (recommended)
- `gpt-4o-transcribe-diarize` - Adds speaker diarization
- `gpt-4o-mini-transcribe` - Good quality, cheapest
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

### Google Gemini

**Models available:**
- `gemini-3-flash-preview` - Fast and strong quality
- `gemini-3-pro-preview` - Highest quality (preview)
- `gemini-2.5-flash` - Stable, fast, cost-effective
- `gemini-2.5-flash-lite` - Lowest latency/cost

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
→ **OpenAI** (`gpt-4o-transcribe`) or **Local Whisper** (`large-v3-turbo`)

### For privacy
→ **Apple** or **Local Whisper**

### For speed
→ **Gemini** or **Apple**

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

Uses the same API keys as transcription where applicable (Gemini/OpenAI). Anthropic requires its own API key.
Enable in settings and select target language.
### Apple (Local Translation)

Uses Apple's Translation framework (macOS 26+). For dev builds, run:
```bash
./scripts/build-apple-translate.sh
```
