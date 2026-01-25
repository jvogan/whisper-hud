# WhisperHUD Color Palette

Official color scheme for WhisperHUD branding and visual assets.

## Primary Gradient

The signature cyan-to-purple gradient used across icons and graphics.

| Color | Hex | RGB | Usage |
|-------|-----|-----|-------|
| Gradient Start (Cyan) | `#00D4FF` | `rgb(0, 212, 255)` | Left/top of gradients |
| Gradient Mid | `#7B61FF` | `rgb(123, 97, 255)` | Middle of gradients |
| Gradient End (Purple) | `#BD00FF` | `rgb(189, 0, 255)` | Right/bottom of gradients |

## Background & Text

| Color | Hex | RGB | Usage |
|-------|-----|-----|-------|
| Dark Background | `#0D1117` | `rgb(13, 17, 23)` | GitHub dark mode, cards |
| Light Text | `#E6EDF3` | `rgb(230, 237, 243)` | Headings, primary text |
| Dim Text | `#8B949E` | `rgb(139, 148, 158)` | Secondary, muted text |

## Status Colors

| Color | Hex | RGB | ANSI | Usage |
|-------|-----|-----|------|-------|
| Success Green | `#3FB950` | `rgb(63, 185, 80)` | `\033[0;32m` | Success states, checkmarks |
| Recording Red | `#F85149` | `rgb(248, 81, 73)` | `\033[0;31m` | Recording indicator |
| Processing Orange | `#F0883E` | `rgb(240, 136, 62)` | `\033[0;33m` | Processing/waiting |

## ANSI Terminal Colors

For terminal/CLI output, use these ANSI escape sequences:

```bash
CYAN='\033[0;36m'     # Primary accent
PURPLE='\033[0;35m'   # Secondary accent
GREEN='\033[0;32m'    # Success
RED='\033[0;31m'      # Recording/Error
YELLOW='\033[0;33m'   # Warning/Processing
WHITE='\033[1;37m'    # Bold headings
DIM='\033[0;90m'      # Muted text
RESET='\033[0m'       # Reset to default
BOLD='\033[1m'        # Bold text
```

## Dithering Palette

For retro/lo-fi dithered graphics, use this 4-color palette:

1. `#0D1117` - Dark (black)
2. `#00D4FF` - Cyan
3. `#BD00FF` - Purple
4. `#FFFFFF` - White

## Gradient Direction

| Asset Type | Direction |
|------------|-----------|
| Icons | Diagonal (top-left → bottom-right) |
| Banners | Horizontal (left → right) |
| Waveforms | Horizontal (left → right) |

## Usage Examples

### CSS

```css
:root {
  --whisper-cyan: #00D4FF;
  --whisper-purple: #BD00FF;
  --whisper-dark: #0D1117;
}

.gradient-bg {
  background: linear-gradient(135deg, var(--whisper-cyan), var(--whisper-purple));
}
```

### Python (PIL)

```python
CYAN_RGB = (0, 212, 255)
PURPLE_RGB = (189, 0, 255)
```

## Brand Guidelines

1. **Primary color** is cyan (`#00D4FF`) - use for main accents
2. **Secondary color** is purple (`#BD00FF`) - use for gradients and highlights
3. **Dark mode friendly** - all assets designed for dark backgrounds
4. **Retro aesthetic** - use dithering for lo-fi effect on larger graphics
5. **Minimal and clean** - prefer simple, flat designs
