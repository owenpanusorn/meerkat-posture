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
uv run python -m meerkat            # tray app
uv run python -m meerkat --debug    # camera window only, shows the raw numbers
```

## Using it

On first start Meerkat asks you to sit up straight and look at your main screen for a few
seconds (calibration). After that it lives in the system tray:

- green: good posture, yellow: drifting, red: held a bad posture too long, grey: paused (camera off)
- right-click for: pause (really releases the camera), snooze the stand-up reminder,
  re-calibrate, calibrate a second screen, debug window, open config, quit

Settings live in `config.toml` in your user config folder (`%APPDATA%\meerkat` on Windows,
`~/Library/Application Support/meerkat` on macOS, `~/.config/meerkat` on Linux). Edits are
picked up within a few seconds.

See [PLAN.md](PLAN.md) for the roadmap.

License: MIT
