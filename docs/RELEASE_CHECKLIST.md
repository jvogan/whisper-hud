# Release Checklist

Use this checklist before making the repository public or cutting a release.

## Repository hygiene
- [x] `git status` is clean (no local-only edits)
- [x] No large binary artifacts committed (`dist/`, `build/`, `.app`, `.dmg`)
- [x] All sensitive files are ignored: `.env`, `*.log`, temp outputs
- [x] `firebase-debug.log` (or other local logs) removed
- [x] Secret scan passes (`secret-scan` workflow / gitleaks)
- [ ] Dependency review passes (GitHub dependency-review action)

## Security & privacy
- [x] API keys are stored only in Keychain (no hard-coded keys)
- [x] History is disabled by default; encryption at rest is optional and works
- [x] Temp audio files are securely deleted after local transcription
- [ ] Sparkle updates: HTTPS feed + signed (Ed25519) with `SUPublicEDKey`
- [x] `SECURITY.md` is accurate and has a working contact path

## Quality & docs
- [ ] README install + usage steps work on a clean macOS machine
- [x] `docs/API_PROVIDERS.md` is accurate and up to date
- [x] Demo assets are attributed in `assets/ATTRIBUTIONS.md`
- [x] License and copyright headers are current

## Build & release
- [x] Tests pass (`make test` or `pytest`)
- [x] Lint passes (`make lint`)
- [ ] App builds with `./scripts/build-app.sh --clean`
- [ ] Code signing + notarization pass (see `scripts/sign-app.sh`)
- [ ] Update feed (if used) points to the new release
