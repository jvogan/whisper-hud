.PHONY: install dev lint format test coverage clean run check all help app dmg sign release build-dist publish

# Prefer Python 3.11 when available (matches project requirement)
PYTHON ?= $(shell command -v python3.11 >/dev/null 2>&1 && echo python3.11 || echo python3)
PIP = $(PYTHON) -m pip

# Default target
all: lint test

# Install production dependencies
install:
	$(PIP) install -e .

# Install with development dependencies
dev:
	$(PIP) install -e ".[dev]"
	pre-commit install
	@echo "✓ Development environment ready"

# Run linting
lint:
	$(PYTHON) -m flake8 whisper-hud/whisper_hud --max-line-length=120 --ignore=E203,E501,W503
	$(PYTHON) -m py_compile whisper-hud/whisper_hud/*.py
	@echo "✓ Linting passed"

# Format code with black
format:
	$(PYTHON) -m black whisper-hud/whisper_hud tests --line-length=120
	@echo "✓ Code formatted"

# Run tests
test:
	$(PYTHON) -m pytest tests/ -v

# Run tests with coverage
coverage:
	$(PYTHON) -m pytest tests/ --cov=whisper_hud --cov-report=term --cov-report=html
	@echo "✓ Coverage report generated in htmlcov/"

# Clean build artifacts
clean:
	rm -rf build/ dist/ *.egg-info/ htmlcov/ .coverage coverage.xml
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	@echo "✓ Cleaned build artifacts"

# Run the app
run:
	$(PYTHON) -m whisper_hud.main

# Check syntax of all Python files
check:
	$(PYTHON) -m py_compile whisper-hud/whisper_hud/*.py
	@echo "✓ All files have valid syntax"

# Pre-commit checks (run before committing)
pre-commit:
	pre-commit run --all-files

# Build macOS .app bundle
app:
	@echo "Building WhisperHUD.app..."
	./scripts/build-app.sh --clean
	@echo "Build complete. App at: dist/WhisperHUD.app"

# Build with Sparkle auto-updates
app-sparkle:
	@echo "Building WhisperHUD.app with Sparkle..."
	./scripts/build-app.sh --clean --sparkle
	@echo "Build complete. App at: dist/WhisperHUD.app"

# Code sign the app
sign:
	@echo "Signing WhisperHUD.app..."
	./scripts/sign-app.sh
	@echo "Signing complete."

# Create DMG installer
dmg: app
	@echo "Creating DMG installer..."
	./scripts/build-dmg.sh
	@echo "DMG created at: dist/WhisperHUD.dmg"

# Full release build (clean, build, sign, dmg)
release: clean
	@echo "Building release..."
	./scripts/build-app.sh --clean --sparkle
	./scripts/sign-app.sh || echo "Warning: Signing skipped (no certificate)"
	./scripts/build-dmg.sh
	@echo "Release build complete!"
	@echo "Files:"
	@ls -la dist/*.dmg dist/*.app 2>/dev/null || true

# Generate appcast.xml for Sparkle updates
appcast:
	@echo "Generating appcast.xml..."
	$(PYTHON) scripts/generate-appcast.py
	@echo "Appcast generated."

# Build Python distribution packages (sdist + wheel)
build-dist:
	@echo "Building Python packages..."
	$(PYTHON) -m pip install --quiet build
	$(PYTHON) -m build
	@echo "Packages built in dist/"
	@ls -la dist/*.tar.gz dist/*.whl 2>/dev/null || true

# Publish to PyPI (requires TWINE_USERNAME and TWINE_PASSWORD or ~/.pypirc)
publish: build-dist
	@echo "Publishing to PyPI..."
	$(PYTHON) -m pip install --quiet twine
	$(PYTHON) -m twine check dist/*
	$(PYTHON) -m twine upload dist/*
	@echo "Published to PyPI!"
	@echo "Install with: pip install whisper-hud"

# Publish to TestPyPI first (for testing)
publish-test: build-dist
	@echo "Publishing to TestPyPI..."
	$(PYTHON) -m pip install --quiet twine
	$(PYTHON) -m twine upload --repository testpypi dist/*
	@echo "Published to TestPyPI!"
	@echo "Install with: pip install --index-url https://test.pypi.org/simple/ whisper-hud"

# Show help
help:
	@echo "WhisperHUD Development Commands"
	@echo "================================"
	@echo ""
	@echo "Setup:"
	@echo "  make install   - Install production dependencies"
	@echo "  make dev       - Install dev dependencies + pre-commit hooks"
	@echo ""
	@echo "Development:"
	@echo "  make lint      - Run flake8 linting"
	@echo "  make format    - Format code with black"
	@echo "  make check     - Verify Python syntax"
	@echo "  make pre-commit - Run all pre-commit hooks"
	@echo ""
	@echo "Testing:"
	@echo "  make test      - Run pytest"
	@echo "  make coverage  - Run tests with coverage report"
	@echo ""
	@echo "Building:"
	@echo "  make app       - Build WhisperHUD.app"
	@echo "  make app-sparkle - Build with Sparkle auto-updates"
	@echo "  make sign      - Code sign the app"
	@echo "  make dmg       - Create DMG installer"
	@echo "  make release   - Full release build"
	@echo "  make appcast   - Generate Sparkle appcast.xml"
	@echo ""
	@echo "Publishing:"
	@echo "  make build-dist  - Build sdist + wheel packages"
	@echo "  make publish     - Publish to PyPI"
	@echo "  make publish-test - Publish to TestPyPI (for testing)"
	@echo ""
	@echo "Other:"
	@echo "  make run       - Run the app"
	@echo "  make clean     - Remove build artifacts"
	@echo "  make all       - Run lint + test (default)"
