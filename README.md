# Meerkat (meerkat-posture)

Offline posture reminder. It watches your webcam, detects head/shoulder posture with MediaPipe,
and nudges you when you hold a bad posture too long or sit too long.

**Privacy:** frames are processed in memory and discarded. Nothing is saved to disk except
numbers (angles, states, timestamps). The app makes no network calls at runtime.

## Dev setup

```sh
uv sync
uv run python scripts/download_models.py   # one-time, downloads models into models/
uv run pytest
uv run ruff check .
uv run python -m meerkat --debug
```

See [PLAN.md](PLAN.md) for the roadmap.

License: MIT
