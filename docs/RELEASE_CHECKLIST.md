# Release Checklist (Public GitHub)

## Visual & Branding
- Add a short demo GIF or video to `assets/` and enable it in `README.md`
- Ensure any third‑party assets are listed in `assets/ATTRIBUTIONS.md`

## Docs & Metadata
- Confirm README reflects current providers, pricing, and requirements
- Update `CHANGELOG.md` with a release entry
- Verify `LICENSE`, `CODE_OF_CONDUCT.md`, and `SECURITY.md`

## Code Health
- Run `make test` and `make lint`
- Search for secrets: `rg -n "api[_-]?key|sk-[A-Za-z0-9]|AIza" -S .`
- Check packaging: `pip install -e .` and launch

## CI / Repo
- Confirm GitHub Actions are green
- Ensure default branch is `main`
- Add topics/description on GitHub repo page

## Release
- Bump version in `pyproject.toml`
- Tag release (e.g., `v1.0.1`)
