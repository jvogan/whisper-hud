#!/bin/bash
# Pre-release checklist for WhisperHUD
set -e

echo "🎙️ WhisperHUD Release Checklist"
echo "================================"
echo ""

ERRORS=0

# Check version consistency
echo "Checking version numbers..."
INIT_VERSION=$(grep -o '__version__ = "[^"]*"' whisper-hud/whisper_hud/__init__.py | cut -d'"' -f2)
PYPROJECT_VERSION=$(grep -o 'version = "[^"]*"' pyproject.toml | head -1 | cut -d'"' -f2)
CHANGELOG_VERSION=$(grep -E '^## \[[0-9]+\.[0-9]+\.[0-9]+\]' CHANGELOG.md | head -1 | sed -E 's/^## \[([0-9]+\.[0-9]+\.[0-9]+)\].*/\1/')

if [ "$INIT_VERSION" != "$PYPROJECT_VERSION" ]; then
    echo "❌ Version mismatch: __init__.py ($INIT_VERSION) vs pyproject.toml ($PYPROJECT_VERSION)"
    ERRORS=$((ERRORS + 1))
else
    echo "✓ Versions match: $INIT_VERSION"
fi

if [ -z "$CHANGELOG_VERSION" ]; then
    echo "⚠️  Could not detect a semantic version header in CHANGELOG.md"
elif [ "$INIT_VERSION" != "$CHANGELOG_VERSION" ]; then
    echo "⚠️  CHANGELOG version ($CHANGELOG_VERSION) differs from code version ($INIT_VERSION)"
fi

# Run linting
echo ""
echo "Running linting..."
if make lint > /dev/null 2>&1; then
    echo "✓ Linting passed"
else
    echo "❌ Linting failed"
    ERRORS=$((ERRORS + 1))
fi

# Run tests
echo ""
echo "Running tests..."
if make test > /dev/null 2>&1; then
    echo "✓ Tests passed"
else
    echo "❌ Tests failed"
    ERRORS=$((ERRORS + 1))
fi

# Check for uncommitted changes
echo ""
echo "Checking git status..."
if [ -n "$(git status --porcelain)" ]; then
    echo "⚠️  Uncommitted changes detected"
    git status --short
else
    echo "✓ Working directory clean"
fi

# Check required files exist
echo ""
echo "Checking required files..."
REQUIRED_FILES="README.md LICENSE CHANGELOG.md pyproject.toml"
for file in $REQUIRED_FILES; do
    if [ -f "$file" ]; then
        echo "✓ $file"
    else
        echo "❌ Missing: $file"
        ERRORS=$((ERRORS + 1))
    fi
done

# Check for sensitive files
echo ""
echo "Checking for sensitive files..."
SENSITIVE_PATTERNS=(".env" "*.pem" "*.key" "*credentials*" "*secret*")
SENSITIVE_EXCLUDES=(
    "./.git/*"
    "./.github/*"
    "./.venv/*"
    "./venv/*"
    "./whisper-hud/venv/*"
    "./build/*"
    "./dist/*"
)
FOUND_SENSITIVE=0
for pattern in "${SENSITIVE_PATTERNS[@]}"; do
    find_cmd=(find . -name "$pattern")
    for exclude_path in "${SENSITIVE_EXCLUDES[@]}"; do
        find_cmd+=(-not -path "$exclude_path")
    done
    matches=$("${find_cmd[@]}" 2>/dev/null | head -5)
    if [ -n "$matches" ]; then
        echo "⚠️  Potentially sensitive: $matches"
        FOUND_SENSITIVE=1
    fi
done
if [ $FOUND_SENSITIVE -eq 0 ]; then
    echo "✓ No sensitive files detected"
fi

# Summary
echo ""
echo "================================"
if [ $ERRORS -eq 0 ]; then
    echo "✅ All checks passed!"
    echo ""
    echo "Ready to release. Next steps:"
    echo "  1. git tag v$INIT_VERSION"
    echo "  2. git push origin v$INIT_VERSION"
    echo "  3. Create GitHub release"
else
    echo "❌ $ERRORS check(s) failed"
    exit 1
fi
