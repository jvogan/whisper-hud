# Glossary

## Auto‑stop

Automatically ends recording after a period of silence.

## Streaming

Shows partial transcription/translation as it is generated.

## Provider

The engine used for transcription or translation (local or cloud).

## Local provider

Runs on‑device (Apple Speech Built-in, Apple Speech Advanced, Whisper Local, Parakeet, Qwen3 ASR, Ollama).

## Cloud provider

Uses a remote API (OpenAI, OpenAI Realtime, Gemini; Anthropic for translation).

## Live Speech Translation

An OpenAI cloud option that translates your speech in real time as you dictate and pastes the translated text directly, instead of transcribing then translating. Requires translation enabled, an OpenAI key, and a supported target language; otherwise WhisperHUD uses the normal transcribe-then-translate path.

## Voice Assistant

A hands-free spoken conversation with an OpenAI cloud model: you talk, it replies through your speakers, and you can interrupt it. Bring-your-own-key, off by default. Its only possible action is pasting text, and only when you allow it.

## Barge-in

Interrupting the Voice Assistant's spoken reply simply by starting to speak; it stops talking and listens to you.

## Custom vocabulary

A list of names/jargon/terms that biases transcription toward their exact spelling. Applied per provider where supported (OpenAI, Whisper Local, Gemini, Apple Speech Advanced).

## Dictation mode

A per-app profile that controls formatting, vocabulary, and optional auto-send of a Return after pasting.

## Voice command

A spoken editing instruction recognized in your speech (e.g. "scratch that", "new line", "press enter"), built-in or custom.

## AI Cleanup (Local)

An optional pass that tidies transcript formatting using a local Ollama model. Local-only (never sent to the cloud) and guard-checked so it cannot paraphrase your words.

## Character pack

A themed set of floating-widget icons for each state. v2 packs add per-state frame animation, sounds, and one-shot success/error animations.
