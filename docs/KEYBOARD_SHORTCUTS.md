# Keyboard Shortcuts Reference

## Default Hotkey

| Shortcut | Action |
|----------|--------|
| `⌘ + ⇧ + Space` | Hold to record (push-to-talk mode) |

## Recording Modes

### Push-to-Talk (Default)
- **Hold** the hotkey to record
- **Release** to stop and transcribe

### Toggle Mode
- **Press** once to start recording
- **Press** again to stop and transcribe

## Customizing the Hotkey

1. Click the WhisperHUD menu bar icon
2. Select **Hotkey** → **Change Hotkey**
3. Press your desired key combination
4. Supported modifiers: `⌘` (Cmd), `⇧` (Shift), `⌃` (Ctrl), `⌥` (Option)

## Supported Special Keys

| Category | Keys |
|----------|------|
| Function Keys | F1-F20 |
| Navigation | ↑ ↓ ← → Home End PgUp PgDn |
| Media | Play/Pause, Volume, Next/Previous |
| USB Devices | Foot pedals and other HID devices |

## Tips

- **Foot pedals**: Many USB foot pedals work out of the box. Configure them in Hotkey settings.
- **Single key hotkeys**: You can use just `F13` or another unused key without modifiers.
- **Conflicts**: If your hotkey conflicts with another app, try adding/removing a modifier.

## Troubleshooting

### Hotkey not working?

1. **Check Accessibility permissions**:
   - System Settings → Privacy & Security → Accessibility
   - Ensure WhisperHUD (or Terminal/Python) is enabled

2. **Hotkey conflict**: Another app might be using the same shortcut
   - Try a different key combination

3. **App not running**: Check the menu bar for the WhisperHUD icon

### Recording doesn't start?

1. **Check microphone permissions**:
   - System Settings → Privacy & Security → Microphone
   - Ensure WhisperHUD has access

2. **Check audio input**: Make sure your microphone is selected in System Settings → Sound
