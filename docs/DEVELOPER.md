# Developer Notes

## Setup

```bash
git clone https://github.com/jvogan/whisper-hud.git
cd whisper-hud
./install.sh
```

## Tests

```bash
make test
```

## Lint

```bash
make lint
```

## Optional extras

```bash
cd whisper-hud
source venv/bin/activate
pip install -e ".[whisper-local]"   # Whisper Local (faster-whisper)
pip install -e ".[parakeet]"        # Parakeet (Apple Silicon, parakeet-mlx>=0.5.1)
pip install -e ".[qwen3-asr]"       # Qwen3 ASR (Apple Silicon, qwen3-asr-mlx>=0.1.1)
```

## Swift helpers (on-device Apple providers)

Two providers drive small bundled Swift helper binaries that must be compiled once. They require Xcode Command Line Tools (`swiftc`) and are macOS 26+ only — the build scripts no-op (exit 0) on older macOS or when `swiftc` is missing.

```bash
./scripts/build-speechanalyzer.sh   # Apple Speech (Advanced) — SpeechAnalyzer
./scripts/build-apple-translate.sh  # Apple (local) translation
```

- `build-speechanalyzer.sh` compiles `whisper-hud/speechanalyzer-helper/main.swift` to `whisper-hud/bin/whisperhud-speechanalyzer`.
- `./run.sh` runs both scripts automatically on launch when the corresponding binary is missing, so a normal `./install.sh` + `./run.sh` flow builds them for you on a supported OS.
- The provider stays hidden (its module is unavailable) until the helper binary exists and is executable.

## Realtime endpoints (OpenAI)

WhisperHUD talks to three OpenAI realtime endpoints over websockets — live transcription, live speech translation, and the voice assistant conversation. The `openai` SDK floor is **>=2.41.0** for these.

- `providers/realtime_audio.py` — shared PCM16 encode/decode helpers. All OpenAI realtime endpoints consume base64-encoded 24 kHz mono PCM16 audio, so encode/decode lives in one place.
- `providers/openai_realtime.py` — live dictation transcription session. The realtime client deliberately pins **`max_retries=0`** on both the client and `realtime.connect()`: a one-shot dictation turn keeps its audio in the server-side input buffer, and an SDK auto-reconnect mid-turn would silently drop that buffer and truncate the transcript. Failing fast instead hands the turn to the local batch-fallback path, which still holds the full recording. (The rationale is commented at the `CONNECT_MAX_RETRIES` constant.)
- `providers/openai_translate_live.py` — live speech-translation session for the `/v1/realtime/translations` endpoint. The SDK exposes no client for this endpoint, so it carries the JSON wire protocol over a raw `websockets` sync client. Validates the target language against the 13 supported output languages before connecting.
- `assistant.py` — the Voice Assistant: a long-lived realtime conversation (`gpt-realtime-2` by default, `gpt-realtime-mini` as the menu's budget tier). Mic audio streams up, spoken replies stream back via `PCM16Player`, and server VAD drives turn-taking. The model may request exactly one tool, `paste_text`; no other tool is ever executed and model-supplied strings are treated as opaque data (the paste callback is the single side-effect channel).
- `audio_output.py` — `PCM16Player`, streaming 24 kHz PCM16 playback via `sounddevice`. Built for low-latency barge-in: `flush()` drops queued audio and interrupts the chunk mid-write so the assistant stops the instant the user speaks.

## Character pack manifest (v2 authoring)

Character packs live in `assets/character-packs/<pack-id>/manifest.json` (built-in) or `~/.config/whisper-hud/character-packs/<pack-id>/` (user-installed). Manifest v2 adds optional per-state animation and sound; **all v2 keys are optional and v1 single-icon packs continue to work unchanged**.

Top-level keys:

| Key | Notes |
|-----|-------|
| `id` | Slug; `[A-Za-z0-9_-]+` only |
| `name`, `description`, `author`, `version` | Metadata |
| `preview_image` | Filename inside the pack used as the menu preview |
| `states` | Map of state name → state spec (see below) |
| `settings` | Optional: `shape_mode`, `apply_state_tint`, `tint_opacity`, `recommended_size`, and the v2 `interpolation` hint |

States: the pipeline uses `idle`, `recording`, `processing`, `success`, and `error`. A pack **must** define at least `idle`. Each state value is either a bare filename string (v1) or an object:

| State key | Notes |
|-----------|-------|
| `file` | Required. The static icon for the state (also the fallback if frames are missing) |
| `description` | Optional |
| `frames` | Optional ordered list of image filenames; when present the widget animates them (loop for steady states, one-shot for `success`/`error`) |
| `fps` | Optional playback speed for `frames`; **clamped to 0.5–30** (default 12). Invalid values fall back to the default |
| `sound` | Optional filename played once when the widget enters the state (gated on the **Play sound** preference) |

`settings.interpolation` accepts `"smooth"` (default) or `"nearest"` — use `"nearest"` for crisp pixel art.

Constraints enforced at load time:

- All `file`, `frames`, `sound`, and `preview_image` paths must resolve **inside the pack directory** (no traversal/symlink escape). Missing or out-of-bounds frames are dropped (the state falls back to `file`); an out-of-bounds `file` drops the whole state.
- Sounds must be `.wav`, `.aiff`, or `.aif` and **≤ 2 MB**; otherwise the sound is skipped.
- On install, the manifest, every state `file`, all `frames`, each `sound`, and `preview_image` are copied with user-only permissions; any missing referenced member fails the install.

Built-in v2 packs to use as references: `pixel-adventurer`, `handheld-89`, `crt-terminal` (`panda` is a v1 pack).
