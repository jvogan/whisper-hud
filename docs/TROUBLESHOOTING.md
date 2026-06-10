# Troubleshooting Guide

## Common Issues

### Installation Issues

#### "Python not found" error
```bash
# Install Python 3.11+ via Homebrew
brew install python@3.11

# Or use pyenv
brew install pyenv
pyenv install 3.11
pyenv global 3.11
```

#### pip install fails with permission error
```bash
# Use a virtual environment instead of system Python
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

#### PyObjC fails to install
```bash
# Ensure Xcode Command Line Tools are installed
xcode-select --install

# Try installing with specific versions
pip install pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-Quartz
```

---

### Permission Issues

#### Accessibility permission not working

1. Open **System Settings** → **Privacy & Security** → **Accessibility**
2. Remove WhisperHUD/Terminal from the list
3. Re-add it and enable the toggle
4. **Restart WhisperHUD**

#### Microphone permission denied

1. Open **System Settings** → **Privacy & Security** → **Microphone**
2. Enable access for WhisperHUD/Terminal
3. Restart the app

#### "Operation not permitted" errors

You may need to grant Full Disk Access:
1. **System Settings** → **Privacy & Security** → **Full Disk Access**
2. Add Terminal or your Python installation

---

### Recording Issues

#### No audio being captured

1. Check microphone selection in **System Settings** → **Sound** → **Input**
2. Verify microphone works in other apps (Voice Memos, QuickTime)
3. Check the audio level meter in the HUD while recording

#### Recording cuts off too early

Adjust silence detection settings:
- Increase **Silence Duration** (default: 1.5 seconds)
- Or disable **Auto-stop on silence**

#### Recording too quiet

- Move closer to the microphone
- Increase input volume in System Settings → Sound → Input
- Use an external microphone for better quality

---

### Transcription Issues

#### "Invalid API key" error

1. Verify your API key is correct
2. Check the API key has proper permissions
3. For OpenAI: Ensure you have credits/billing set up
4. For Gemini: Ensure the Generative Language API is enabled

#### "API keys locked" error

1. Open WhisperHUD menu → **Privacy & Security** → **API Key Storage** → **Unlock...**
2. Enter your API key passphrase
3. The store stays unlocked for the app session (until quit or manual lock)

WhisperHUD only asks for unlock when an operation actually needs cloud keys.
Local Apple/Whisper/Parakeet flows do not require unlock.

#### macOS asks for Keychain access

This only happens when **API Key Storage** is set to **macOS Keychain**.

To avoid Keychain prompts:
1. Open WhisperHUD menu → **Privacy & Security** → **API Key Storage**
2. Switch to **Passphrase (Encrypted Local)** (default) or **Session Only**
3. Re-enter API keys if prompted after switching modes

#### Python quit unexpectedly after denying Keychain access

If this happened right after a Keychain prompt, switch off Keychain mode:
1. Reopen WhisperHUD
2. Go to **Privacy & Security → API Key Storage**
3. Select **Passphrase (Encrypted Local)** (recommended) or **Session Only**
4. Re-enter your API keys

History encryption does not require Keychain.

#### Transcription takes too long

- Check your internet connection
- Try a different provider (Gemini is often faster than OpenAI)
- For local: Ensure the model is fully downloaded

#### Poor transcription accuracy

- Speak clearly and at a moderate pace
- Reduce background noise
- Try a different model (e.g., `gpt-4o-transcribe` for better accuracy)
- For non-English: Set the correct source language

---

### Paste Issues

#### Text not pasting

1. Verify Accessibility permissions (see above)
2. Check that the target app accepts paste (some apps block it)
3. Try toggling **Restore Clipboard** setting

#### Paste goes to wrong app

- Use **Paste Target Lock** to specify the destination
- Enable **Return Focus** to go back to your original app

#### Clipboard content lost

Enable **Restore Clipboard** in settings to preserve your clipboard contents.

---

### Translation Issues

#### Cloud translation not working

- Ensure your OpenAI, Gemini, or Anthropic API key is set in **API Keys**
- If using passphrase storage, unlock API key storage in **Privacy & Security**
- Verify the key is valid and has permissions
- Check your internet connection
- If a preview model is unavailable, re-open Translation settings and pick a stable model

#### Ollama not found

```bash
# Install Ollama
brew install ollama

# Start the server
ollama serve
```

#### Translation model download fails

```bash
# Manually pull the model
ollama pull translategemma:4b

# Check available models
ollama list
```

#### Translation is slow

- Use a smaller model (`translategemma:4b` vs `translategemma:27b`)
- Ensure Ollama server is running locally
- Consider using cloud translation (Gemini/OpenAI) for speed

---

## Known Limitations

- **Hotkey conflicts**: If another app uses the same shortcut, WhisperHUD won’t receive it.
- **Large local models**: Whisper/Translate large models can be slow on older Macs.
- **First‑use downloads**: Local providers download models on first use.

---

## Security Notes

### What “0600 permissions” means

Sensitive local files are created with user-only permissions:
- `0700` on config directory (only your user can access)
- `0600` on sensitive files (only your user can read/write)

This reduces exposure on shared machines with multiple local user accounts.

---

## Performance Tips

- Prefer **Gemini/OpenAI** if you need the fastest turnaround.
- For **Whisper Local**, use `large-v3-turbo` or `small` on older machines.
- Enable **Streaming display** to see partial results sooner.

---

### Local Whisper Issues

#### Whisper Local not available

```bash
# Install the local engine
pip install -e ".[whisper-local]"
```

Then select **Whisper Local** again and download a model.

---

### Parakeet Issues

#### Parakeet not available

```bash
# Install the Apple Silicon engine
pip install -e ".[parakeet]"
```

Then select **Parakeet** again and download a model.

---

### Qwen3 ASR Issues

#### Qwen3 ASR not available

Qwen3 ASR is Apple Silicon (M1/M2/M3/M4) only and ships as an optional extra.

- On an Intel Mac it is unavailable — use Apple Speech, Whisper Local, or a cloud provider instead.
- On Apple Silicon, install the engine:
  ```bash
  pip install -e ".[qwen3-asr]"
  ```
  Then select **Qwen3 ASR** again. The model (`qwen3-asr-0.6b` by default) downloads on first use.

---

### Apple Speech (Advanced) Issues

#### Apple Speech (Advanced) not listed

This provider uses the macOS 26+ SpeechAnalyzer API via a small bundled Swift helper, and stays hidden until both conditions are met:

1. **macOS version**: It requires macOS 26 or later. On older macOS it is not offered — use Apple Speech (Built-in) instead.
2. **Helper not built**: Build the Swift helper once (needs Xcode Command Line Tools):
   ```bash
   ./scripts/build-speechanalyzer.sh
   ```
   `./run.sh` also builds it automatically on launch when it is missing. After it builds, select **Apple Speech (Advanced)** again.

---

### AI Cleanup (Local) Issues

#### AI Cleanup shows unavailable

AI Cleanup is an **optional, local-only** feature that tidies transcripts using a local Ollama model — transcripts are never sent to the cloud. The menu shows "Ollama: not reachable" when no local server is running.

```bash
# Install Ollama (if needed)
brew install ollama

# Start the server
ollama serve

# Optional: pull a small instruct model for cleanup
ollama pull qwen3:1.7b
```

Then re-open **Dictation Intelligence**; the status should read "Ollama: ready". If you have no model installed, cleanup is skipped and the raw transcript is used. You can also use **Check Cleanup Status…** in that menu to re-probe.

---

### Widget Issues

#### Floating widget not appearing

1. Check **Show Widget** is enabled in settings
2. Restart the app
3. Check if the widget is off-screen (resize your display)

#### Custom icon not loading

- Verify the image file exists
- Supported formats: PNG, JPG, HEIC, WebP, GIF
- Maximum file size: 10 MB
- Minimum dimensions: 16×16 pixels

---

## Getting Help

If your issue isn't listed here:

1. **Check existing issues**: [GitHub Issues](https://github.com/jvogan/whisper-hud/issues)
2. **Search discussions**: Others may have solved the same problem
3. **Open a new issue**: Include:
   - macOS version
   - Python version (`python3 --version`)
   - Steps to reproduce
   - Error messages (if any)

## Debug Mode

For detailed logs, run with debug logging:

```bash
# Set environment variable
export WHISPER_HUD_DEBUG=1

# Run the app
python -m whisper_hud.main
```

Or modify `logging_config.py` to set `level=logging.DEBUG`.

---

### Extras Quick Setup

If you skipped the docs and want local engines:

```bash
cd whisper-hud
source venv/bin/activate
pip install -e ".[whisper-local]"   # Whisper Local
pip install -e ".[parakeet]"        # Parakeet (Apple Silicon)
```
