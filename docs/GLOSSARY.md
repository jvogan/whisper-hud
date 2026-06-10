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
