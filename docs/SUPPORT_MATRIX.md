# Support Matrix

## macOS Versions

| Feature | Requirement |
|---------|-------------|
| Core app (menu bar) | macOS 12+ |
| Apple Speech | macOS 12+ + `pyobjc-framework-Speech` |
| Vision background removal | macOS 14+ + `pyobjc-framework-Vision` |

## Providers

| Provider | Requires | Notes |
|---------|----------|-------|
| OpenAI | API key | Cloud transcription |
| Gemini | API key | Cloud transcription |
| Apple Speech | macOS 12+ | On‑device |
| Whisper Local | `faster-whisper`, model download | On‑device |
| Parakeet | Apple Silicon + `parakeet-mlx` | On‑device, very fast |
| Ollama | Homebrew + Ollama server | Local translation |

## Compatibility Notes

- Parakeet is Apple Silicon only (M1/M2/M3/M4). Intel Macs should use Apple Speech, Whisper Local, or cloud providers.
- Whisper Local works on Intel and Apple Silicon, but large models may be slow on older machines.
