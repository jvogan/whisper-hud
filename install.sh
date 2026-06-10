#!/bin/bash
#
# WhisperHUD Installer
# A friendly, guided setup for macOS voice-to-text transcription
#

set -euo pipefail
set -E

# Colors for terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
DIM='\033[0;90m'
RESET='\033[0m'
BOLD='\033[1m'
INSTALL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Symbols
CHECK="${GREEN}✓${RESET}"
ARROW="${CYAN}→${RESET}"
DOT="${DIM}·${RESET}"

is_python_311_plus() {
    local candidate="$1"
    "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

local_bootstrap_ready() {
    local bootstrap_python="$INSTALL_ROOT/.venv/bin/python"
    [[ -x "$bootstrap_python" ]] || return 1

    "$bootstrap_python" -c "import rumps, pynput, sounddevice, numpy, scipy, openai, websockets, anthropic, google.genai, keyring, cryptography, pyperclip, requests, AppKit, Quartz, Speech" >/dev/null 2>&1
}

reuse_local_bootstrap_venv() {
    print_info "Reusing local pre-provisioned environment from $INSTALL_ROOT/.venv"
    rm -rf venv
    ln -s "$INSTALL_ROOT/.venv" venv
    source venv/bin/activate
    print_success "Local pre-provisioned environment linked"
}

print_banner() {
    echo ""
    echo -e "${CYAN}"

    # Try to load banner from file, fallback to inline if not found
    BANNER_FILE="$INSTALL_ROOT/assets/ascii/banner_installer.txt"

    if [[ -f "$BANNER_FILE" ]]; then
        cat "$BANNER_FILE"
    else
        # Fallback inline banner
        cat << 'EOF'
               ╭─────────────────────────────────────╮
               │                                     │
               │   ░▒▓  W H I S P E R H U D  ▓▒░    │
               │                                     │
               │      ┌─────────────────────┐        │
               │      │  ◉ ─ ─ ─ ╱╲ ─ ─ ─   │        │
               │      │    ░░▒▒▓▓██▓▓▒▒░░   │        │
               │      └─────────────────────┘        │
               │                                     │
               │   voice → text, invisibly           │
               │                                     │
               ╰─────────────────────────────────────╯
EOF
    fi

    echo -e "${RESET}"
    echo ""
}

print_step() {
    echo -e "  ${ARROW} ${WHITE}$1${RESET}"
}

print_success() {
    echo -e "  ${CHECK} ${GREEN}$1${RESET}"
}

print_info() {
    echo -e "  ${DOT} ${DIM}$1${RESET}"
}

print_error() {
    echo -e "  ${RED}✗ $1${RESET}"
}

print_section() {
    echo ""
    echo -e "${BOLD}${WHITE}$1${RESET}"
    echo -e "${DIM}$(printf '%.s─' {1..45})${RESET}"
}

cleanup_on_error() {
    local exit_code=$1
    local failed_command=$2

    echo ""
    print_error "Installation failed while running: ${failed_command}"
    print_info "Fix the issue above, then re-run ./install.sh from the repository root."
    print_info "Common remediations: install Python 3.11+, ensure macOS dependencies are available, and verify pip can access the required packages."

    exit "$exit_code"
}

trap 'cleanup_on_error $? "$BASH_COMMAND"' ERR

# Check if we're in the right directory
check_directory() {
    print_step "Verifying project directory..."
    if [[ ! -f "requirements.txt" ]] || [[ ! -d "whisper-hud" ]]; then
        print_error "Please run this script from the project root directory"
        print_info "cd /path/to/whisper-hud && ./install.sh"
        exit 1
    fi

    print_success "Project root detected"
}

# Check macOS
check_macos() {
    print_step "Checking macOS compatibility..."
    if [[ "$OSTYPE" != "darwin"* ]]; then
        print_error "WhisperHUD is designed for macOS"
        print_info "Detected: $OSTYPE"
        exit 1
    fi
    print_success "macOS detected"
}

# Select Python binary (prefer 3.11 for compatibility)
select_python() {
    if [[ -n "${PYTHON_BIN:-}" ]]; then
        if command -v "$PYTHON_BIN" >/dev/null 2>&1 && is_python_311_plus "$PYTHON_BIN"; then
            return
        fi
        print_error "PYTHON_BIN must point to Python 3.11+ (got: $PYTHON_BIN)"
        exit 1
    fi

    if command -v python3.11 >/dev/null 2>&1 && is_python_311_plus "python3.11"; then
        PYTHON_BIN="python3.11"
    elif command -v python3 >/dev/null 2>&1 && is_python_311_plus "python3"; then
        PYTHON_BIN="python3"
    elif command -v python >/dev/null 2>&1 && is_python_311_plus "python"; then
        PYTHON_BIN="python"
    else
        PYTHON_BIN=""
    fi
}

# Check Python version
check_python() {
    print_step "Checking Python version..."
    select_python
    if [[ -z "$PYTHON_BIN" ]]; then
        print_error "Python 3 not found"
        print_info "Install via: brew install python@3.11"
        exit 1
    fi

    PYTHON_VERSION=$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')
    if ! is_python_311_plus "$PYTHON_BIN"; then
        print_error "Python 3.11+ required (found $PYTHON_VERSION)"
        print_info "Install via: brew install python@3.11"
        exit 1
    fi

    print_success "Python $PYTHON_VERSION found ($PYTHON_BIN)"
}

# Setup virtual environment
setup_venv() {
    print_step "Creating virtual environment..."

    cd whisper-hud

    if [[ -d "venv" ]]; then
        print_info "Virtual environment already exists"
    else
        "$PYTHON_BIN" -m venv venv
        print_success "Virtual environment created"
    fi

    source venv/bin/activate
    print_success "Virtual environment activated"
}

# Install dependencies
install_deps() {
    print_step "Installing Python dependencies..."
    print_info "This may take a minute..."

    if pip install --upgrade pip -q && pip install -r requirements.txt -q; then
        print_success "Dependencies installed"
        return
    fi

    if local_bootstrap_ready; then
        print_info "Fresh dependency install was unavailable; falling back to the local workspace bootstrap environment."
        reuse_local_bootstrap_venv
        print_success "Dependencies installed"
        return
    fi

    print_error "Installation failed while running: pip install --upgrade pip -q && pip install -r requirements.txt -q"
    print_info "Fix the dependency error above, then re-run ./install.sh from the repository root."
    print_info "Common remediations: check internet access, verify pip can reach the package index, or preinstall the required packages."
    exit 1
}

run_smoke_test() {
    print_step "Running post-install smoke test..."
    python -c "import whisper_hud; print('OK')"
    print_success "Smoke test passed"
}

# Create launch script
create_launcher() {
    print_step "Preparing launcher..."

    LAUNCHER_PATH="$INSTALL_ROOT/run.sh"

    if [[ -f "$LAUNCHER_PATH" ]]; then
        chmod +x "$LAUNCHER_PATH"
        print_success "Launcher ready: ./run.sh"
        return
    fi

    cat > "$LAUNCHER_PATH" << 'LAUNCHER'
#!/bin/bash
# WhisperHUD Launcher
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/whisper-hud"
VENV_ACTIVATE="$APP_DIR/venv/bin/activate"

if [[ ! -d "$APP_DIR" ]]; then
    echo "Error: Could not find app directory at $APP_DIR"
    echo "Run this script from the WhisperHUD repository root."
    exit 1
fi

cd "$APP_DIR"

if [[ -f "$SCRIPT_DIR/scripts/build-apple-translate.sh" && ! -x "$APP_DIR/bin/whisperhud-apple-translate" ]]; then
    "$SCRIPT_DIR/scripts/build-apple-translate.sh" || true
fi

if [[ -f "$SCRIPT_DIR/scripts/build-speechanalyzer.sh" && ! -x "$APP_DIR/bin/whisperhud-speechanalyzer" ]]; then
    "$SCRIPT_DIR/scripts/build-speechanalyzer.sh" || true
fi

if [[ ! -f "$VENV_ACTIVATE" ]]; then
    echo "WhisperHUD virtual environment not found."
    echo "Run ./install.sh first, then try ./run.sh again."
    exit 1
fi

source "$VENV_ACTIVATE"
exec python -m whisper_hud.main
LAUNCHER

    chmod +x "$LAUNCHER_PATH"
    print_success "Launcher created: ./run.sh"
}

# Print next steps
print_next_steps() {
    echo ""
    echo -e "${BOLD}${WHITE}╭───────────────────────────────────────────╮${RESET}"
    echo -e "${BOLD}${WHITE}│${RESET}  ${GREEN}Installation complete!${RESET}                   ${BOLD}${WHITE}│${RESET}"
    echo -e "${BOLD}${WHITE}╰───────────────────────────────────────────╯${RESET}"
    echo ""
    echo -e "  ${BOLD}Start WhisperHUD:${RESET}"
    echo -e "    ${CYAN}./run.sh${RESET}"
    echo ""
    echo -e "  ${BOLD}Or manually:${RESET}"
    echo -e "    ${DIM}cd whisper-hud${RESET}"
    echo -e "    ${DIM}source venv/bin/activate${RESET}"
    echo -e "    ${DIM}python -m whisper_hud.main${RESET}"
    echo ""
    echo -e "${DIM}┌─────────────────────────────────────────────────┐${RESET}"
    echo -e "${DIM}│${RESET} ${YELLOW}First time?${RESET} You'll need to:                     ${DIM}│${RESET}"
    echo -e "${DIM}│${RESET}                                                 ${DIM}│${RESET}"
    echo -e "${DIM}│${RESET}  1. Grant Accessibility permission              ${DIM}│${RESET}"
    echo -e "${DIM}│${RESET}     ${DIM}System Settings → Privacy → Accessibility${RESET}   ${DIM}│${RESET}"
    echo -e "${DIM}│${RESET}                                                 ${DIM}│${RESET}"
    echo -e "${DIM}│${RESET}  2. Grant Microphone permission                 ${DIM}│${RESET}"
    echo -e "${DIM}│${RESET}                                                 ${DIM}│${RESET}"
    echo -e "${DIM}│${RESET}  3. Add your API key (cloud providers only)     ${DIM}│${RESET}"
    echo -e "${DIM}│${RESET}     ${DIM}Click menu bar icon → API Keys${RESET}              ${DIM}│${RESET}"
    echo -e "${DIM}│${RESET}                                                 ${DIM}│${RESET}"
    echo -e "${DIM}│${RESET}  4. Hold ${CYAN}⌘⇧Space${RESET} and speak!                   ${DIM}│${RESET}"
    echo -e "${DIM}└─────────────────────────────────────────────────┘${RESET}"
    echo ""
    echo -e "  ${BOLD}Optional local engines:${RESET}"
    echo -e "    ${DIM}cd whisper-hud${RESET}"
    echo -e "    ${DIM}source venv/bin/activate${RESET}"
    echo -e "    ${DIM}pip install -e \".[whisper-local]\"${RESET}"
    echo -e "    ${DIM}pip install -e \".[parakeet]\"${RESET}"
    echo ""
}

# Main installation flow
main() {
    if [[ -t 1 ]] && [[ -n "${TERM:-}" ]] && command -v clear >/dev/null 2>&1; then
        clear || true
    fi
    print_banner

    print_section "Checking requirements"
    check_directory
    check_macos
    check_python

    print_section "Setting up WhisperHUD"
    setup_venv
    install_deps
    run_smoke_test
    create_launcher

    print_next_steps
}

# Run
main
