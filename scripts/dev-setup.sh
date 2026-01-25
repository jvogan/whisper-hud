#!/bin/bash
# Development environment setup script for WhisperHUD
set -e

echo "🎙️ WhisperHUD Development Setup"
echo "================================"
echo ""

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
REQUIRED_VERSION="3.11"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "❌ Python $REQUIRED_VERSION+ is required (found $PYTHON_VERSION)"
    echo "   Install with: brew install python@3.11"
    exit 1
fi
echo "✓ Python $PYTHON_VERSION"

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo ""
    echo "Creating virtual environment..."
    python3 -m venv .venv
    echo "✓ Virtual environment created"
fi

# Activate virtual environment
source .venv/bin/activate
echo "✓ Virtual environment activated"

# Upgrade pip
echo ""
echo "Upgrading pip..."
pip install --upgrade pip -q

# Install development dependencies
echo ""
echo "Installing dependencies..."
pip install -e ".[dev]" -q
echo "✓ Dependencies installed"

# Install pre-commit hooks
echo ""
echo "Setting up pre-commit hooks..."
pre-commit install -q
echo "✓ Pre-commit hooks installed"

# Verify installation
echo ""
echo "Verifying installation..."
python -c "from whisper_hud import __version__; print(f'✓ WhisperHUD v{__version__} installed')"

echo ""
echo "================================"
echo "✅ Development environment ready!"
echo ""
echo "Activate the environment with:"
echo "  source .venv/bin/activate"
echo ""
echo "Run the app with:"
echo "  make run"
echo ""
echo "Run tests with:"
echo "  make test"
echo ""
