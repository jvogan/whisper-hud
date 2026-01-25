# Developer Notes

## Setup

```bash
git clone https://github.com/jvogan/whisper-hud.git
cd whisper-hud
./install.sh
```

## Tests

```bash
make test
```

## Lint

```bash
make lint
```

## Optional extras

```bash
cd whisper-hud
source venv/bin/activate
pip install -e ".[whisper-local]"
pip install -e ".[parakeet]"
```
