# Release Checklist

Use this checklist before making the repository public or cutting a release.

## Repository hygiene
- [ ] `git status` is clean (no local-only edits)
- [ ] No large binary artifacts committed (`dist/`, `build/`, `.app`, `.dmg`)
- [ ] All sensitive files are ignored: `.env`, `*.log`, temp outputs
- [ ] `firebase-debug.log` (or other local logs) removed
- [ ] Secret scan passes (`secret-scan` workflow / gitleaks)
 - [ ] Dependency review passes (GitHub dependency-review action)

## Security & privacy
- [ ] API keys are stored only in Keychain (no hard-coded keys)
- [ ] History is disabled by default; encryption at rest is optional and works
- [ ] Temp audio files are securely deleted after local transcription
- [ ] Sparkle updates: HTTPS feed + signed (Ed25519) with `SUPublicEDKey`
- [ ] `SECURITY.md` is accurate and has a working contact path

## Quality & docs
- [ ] README install + usage steps work on a clean macOS machine
- [ ] `docs/API_PROVIDERS.md` is accurate and up to date
- [ ] Demo assets are attributed in `assets/ATTRIBUTIONS.md`
- [ ] License and copyright headers are current

## Build & release
- [ ] Tests pass (`make test` or `pytest`)
- [ ] Lint passes (`make lint`)
- [ ] App builds with `./scripts/build-app.sh --clean`
- [ ] Code signing + notarization pass (see `scripts/sign-app.sh`)
- [ ] Update feed (if used) points to the new release
