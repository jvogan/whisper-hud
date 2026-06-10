# Support Matrix

## macOS Versions

| Feature | Requirement |
|---------|-------------|
| Core app (menu bar) | macOS 12+ |
| Apple Speech (Built-in) | macOS 12+ + `pyobjc-framework-Speech` |
| Apple Speech (Advanced) | macOS 26+ + SpeechAnalyzer Swift helper (`scripts/build-speechanalyzer.sh`) |
| Apple Translation (local) | macOS 26+ + Apple Translate Swift helper (`scripts/build-apple-translate.sh`) |
| Vision background removal | macOS 14+ + `pyobjc-framework-Vision` |

## Providers

| Provider | Requires | Notes |
|---------|----------|-------|
| OpenAI | OpenAI API key | Cloud batch transcription |
| OpenAI Realtime | OpenAI API key | Cloud live dictation, true partials while recording |
| Gemini | API key | Cloud transcription |
| Apple Speech (Built-in) | macOS 12+ | On‑device |
| Apple Speech (Advanced) | macOS 26+ + SpeechAnalyzer helper | On‑device, very fast; ~40 languages; supports vocabulary biasing |
| Whisper Local | `faster-whisper`, model download | On‑device |
| Parakeet | Apple Silicon + `parakeet-mlx` (`[parakeet]` extra) | On‑device, very fast, live streaming |
| Qwen3 ASR | Apple Silicon + `qwen3-asr-mlx` (`[qwen3-asr]` extra), model download | On‑device, 52 languages, strong on accents/noise |
| Ollama | Homebrew + Ollama server | Local translation, and local AI Cleanup |

## Compatibility Notes

- Parakeet and Qwen3 ASR are Apple Silicon only (M1/M2/M3/M4). Intel Macs should use Apple Speech (Built-in), Whisper Local, or cloud providers.
- Apple Speech (Advanced) requires macOS 26+ and the bundled Swift helper to be built (`scripts/build-speechanalyzer.sh`, run automatically by `./run.sh` when missing). It is hidden until the helper exists.
- Whisper Local works on Intel and Apple Silicon, but large models may be slow on older machines.
- Vocabulary biasing is supported on OpenAI (batch, except diarize), Whisper Local, Gemini, and Apple Speech (Advanced). Apple Speech (Built-in), Parakeet, and Qwen3 ASR ignore it.
- AI Cleanup (local) and Ollama translation both require a local Ollama server; AI Cleanup is local-only and never sends transcripts to the cloud.
