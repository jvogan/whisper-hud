# Transcription Providers Guide

WhisperHUD supports multiple transcription providers, each with different trade-offs.

## Quick Comparison

| Provider | Speed | Accuracy | Privacy | Cost | Setup |
|----------|-------|----------|---------|------|-------|
| **OpenAI** | Fast | Excellent | Cloud | ~$0.003–0.006/min | API key |
| **OpenAI Realtime** | Very Fast | Excellent | Cloud | OpenAI Realtime pricing | Same OpenAI API key |
| **Gemini** | Very Fast | Excellent | Cloud | Free tier available | API key |
| **Apple (Built-in)** | Fast | Good | On-device | Free | None |
| **Whisper Local** | Slow | Excellent | On-device | Free | Model download |
| **Parakeet (Apple Silicon)** | Very Fast | Good | On-device | Free | Model download |
| **Qwen3 ASR (Apple Silicon)** | Fast | Good | On-device | Free | Extra + model download |
| **Apple Speech (Advanced)** | Very Fast | Good | On-device | Free | macOS 26+ + helper build |

---

## Cloud Providers

### OpenAI (Batch)

**Models available:**
- `gpt-4o-mini-transcribe` - OpenAI's currently recommended general transcription model (default, $0.003/min)
- `gpt-4o-mini-transcribe-2025-12-15` - Pinned mini transcription snapshot ($0.003/min)
- `gpt-4o-transcribe` - Best accuracy, handles accents and noise well ($0.006/min)
- `gpt-4o-transcribe-diarize` - Speaker-aware transcript; HUD shows plain text ($0.006/min). Custom vocabulary is not applied to this model (the API rejects the prompt parameter).
- `whisper-1` - Classic Whisper v2 ($0.006/min)

**Setup:**
1. Get API key from [platform.openai.com](https://platform.openai.com/api-keys)
2. Enter key in WhisperHUD → API Keys → OpenAI

**Pricing:** ~$0.003/min for the mini models, ~$0.006/min for `gpt-4o-transcribe`, `gpt-4o-transcribe-diarize`, and `whisper-1`

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
- `gemini-3.1-flash-lite` - Current stable default for direct audio transcription (lowest latency/cost)
- `gemini-3.5-flash` - Newest stable audio-capable Flash model; higher quality than Flash-Lite
- `gemini-3-flash-preview` - Frontier preview balanced model
- `gemini-3.1-pro-preview` - Latest preview quality model
- `gemini-2.5-pro` - Legacy stable quality option
- `gemini-2.5-flash` - Legacy stable balanced option
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

### Apple (Built-in) Speech Recognition

Uses macOS built-in speech recognition (same as Siri dictation). For the modern on-device engine, see **Apple Speech (Advanced)** below.

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

Parakeet is an Apple Silicon-optimized local model (via `parakeet-mlx`, MLX-converted weights from the `mlx-community` Hugging Face org). Supports live streaming transcription.

**Models available:**
- `parakeet-tdt-0.6b-v3` - Multilingual, 25 European languages (default)
- `parakeet-tdt-0.6b-v2` - English only; fastest and most accurate for English

**Setup:**
```bash
pip install -e ".[parakeet]"
```
Then select **Parakeet** in WhisperHUD. The model downloads on first use.

**Pros:**
- Very fast on Apple Silicon
- Runs locally (no cloud)
- Free after download
- Live streaming support

**Cons:**
- Apple Silicon only
- Limited language support compared to Whisper
- Does not support custom vocabulary biasing

---

### Qwen3 ASR (Apple Silicon)

Alibaba's Qwen3-ASR family (Apache-2.0), run fully on-device via the pure-MLX `qwen3-asr-mlx` package. Strong on accented and noisy speech and on non-European languages, closing WhisperHUD's biggest local-language gap.

**Models available:**
- `qwen3-asr-0.6b` - 52 languages, fast (default, ~700 MB; Hugging Face `mlx-community/Qwen3-ASR-0.6B-bf16`)
- `qwen3-asr-1.7b` - 52 languages, higher accuracy, larger download (~1.8 GB; `mlx-community/Qwen3-ASR-1.7B-bf16`)

**Setup:**
```bash
pip install -e ".[qwen3-asr]"
```
Then select **Qwen3 ASR** in WhisperHUD. The model downloads on first use.

**Pros:**
- 52 languages, including many non-European ones
- Robust to accents and background noise
- Runs locally (no cloud), free after download

**Cons:**
- Apple Silicon (M1/M2/M3/M4) only
- Does not support custom vocabulary biasing (the package exposes no biasing parameter)
- First transcription triggers a model download

---

### Apple Speech (Advanced)

On-device transcription via the macOS 26+ SpeechAnalyzer / SpeechTranscriber API — Apple's modern, Neural Engine-accelerated replacement for the built-in recognizer. Substantially faster than Whisper for comparable quality, free, and fully on-device. The API is Swift-only, so WhisperHUD drives a small bundled Swift helper.

**Models available:**
- `system` - macOS 26+ on-device speech model; ~40 languages, uses your current system locale

**Setup:**
1. Requires macOS 26 or later.
2. Build the bundled Swift helper (needs Xcode Command Line Tools):
   ```bash
   ./scripts/build-speechanalyzer.sh
   ```
   `./run.sh` also builds it automatically on first launch if it is missing. The provider is hidden until the helper exists.
3. Select **Apple Speech (Advanced)** in WhisperHUD.

**Pros:**
- Free and fully on-device
- Very fast (Neural Engine accelerated)
- Supports custom vocabulary biasing via SpeechAnalyzer contextual hints

**Cons:**
- Requires macOS 26+
- Requires building the Swift helper once

---

## Custom Vocabulary Biasing

WhisperHUD can bias transcription toward names, jargon, and terms you list under **Dictation Intelligence → Vocabulary & Replacements** (`custom_vocabulary`, up to 200 terms). It is threaded into every provider that supports biasing, mapped to each provider's native mechanism:

| Provider | How vocabulary is applied |
|----------|----------------------------|
| OpenAI (batch) | `prompt` glossary string (skipped for the diarize model) |
| Whisper Local | `initial_prompt` glossary string |
| Gemini | Appended hint line in the transcription instruction |
| Apple Speech (Advanced) | SpeechAnalyzer `contextualStrings` hints (capped at 100) |
| Apple (Built-in) | Not supported |
| Parakeet | Not supported |
| Qwen3 ASR | Not supported |

The same vocabulary is also applied to streaming / live sessions and to the "Transcribe Audio File…" action.

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

---

## Live Speech Translation (OpenAI)

A faster, single-step alternative to the normal transcribe-then-translate flow. While you dictate, your audio streams to OpenAI and the **translated** text comes back live and is pasted — one hop instead of two.

Enable it under **Translation → Live Speech Translation (OpenAI)**.

**Requirements (all three):**
- Translation is enabled
- An OpenAI API key is set
- Your target language is one of the supported output languages below

If any requirement is missing, the toggle has no effect and WhisperHUD quietly uses the normal transcribe-then-translate path instead. The menu shows a short hint when the toggle is on but cannot take effect (no OpenAI key, or an unsupported target language).

**Supported target languages (13):** English, Spanish, Portuguese, French, German, Italian, Japanese, Korean, Chinese, Russian, Hindi, Indonesian, Vietnamese. You can speak any of 70+ input languages — the spoken language is detected automatically.

**Pricing:** $0.034 per audio minute (OpenAI's listed price). This is counted toward WhisperHUD's in-app cost stats.

**Notes:**
- Your custom vocabulary and text replacements still apply to the translated text.
- Voice commands and AI Cleanup are skipped for live-translated turns — a translated sentence that happens to read like an editing command (e.g. "new line") will never trigger one.
- History stores the translated text, with the original-language transcript kept as the "original".
- If the live session can't connect or fails mid-turn, WhisperHUD automatically falls back to normal transcription plus text translation for that turn, so you still get a result.

---

## Voice Assistant (OpenAI)

A hands-free spoken conversation with OpenAI's `gpt-realtime-2` model. One click starts it: you talk, it talks back through your speakers, and you can interrupt its reply at any time just by speaking. Find it in the top-level **Voice Assistant** menu.

This is a **cloud** feature and **bring-your-own-key**: it requires an OpenAI API key, and while a chat is active your audio is sent to OpenAI. The menu labels it as a cloud feature.

**Options (Voice Assistant menu):**
- **Start / Stop Voice Chat** — begin or end the conversation.
- **Voice** — pick the assistant's spoken voice (10 OpenAI voices; default **marin**).
- **Reasoning Effort** — low / medium / high (default **low**). Higher effort can improve answers but costs more.
- **Allow Pasting Text** — when on, you can ask the assistant to paste text into the app you're working in. Pasting is the **only** action the assistant can perform: it cannot run commands, read files, or control anything else on your Mac.

**Things to know:**
- The menu-bar icon shows 🤖 while a chat is active.
- Dictation and the assistant can't run at the same time — the microphone belongs to one of them. Stop one before starting the other.
- Each exchange (your question plus the assistant's reply) is saved to history when history is enabled. **Private Mode** keeps exchanges out of history.

**Pricing:** Token-based, not per-minute. OpenAI lists `gpt-realtime-2` at **$32 per 1M audio input tokens** (with a 90% discount on cached context) and **$64 per 1M audio output tokens**. Cost grows with how long the conversation runs. WhisperHUD does **not** estimate assistant costs in its in-app stats — check your OpenAI usage dashboard.
