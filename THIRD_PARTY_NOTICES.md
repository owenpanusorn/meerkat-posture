# Third-party notices

Meerkat (meerkat-posture) is released under the MIT License (see `LICENSE`).
It uses the following third-party software and models. Each keeps its own license.
No third-party source code is copied into this repository.

## Runtime dependencies

| Package | License | Notes |
|---|---|---|
| [MediaPipe](https://github.com/google-ai-edge/mediapipe) | Apache-2.0 | Face Landmarker and Pose Landmarker (Tasks API) |
| [OpenCV](https://github.com/opencv/opencv) (`opencv-contrib-python`) | Apache-2.0 | camera access, debug window; installed with MediaPipe |
| [NumPy](https://numpy.org) | BSD-3-Clause (bundled parts: 0BSD, MIT, Zlib) | |
| [pystray](https://github.com/moses-palmer/pystray) | LGPL-3.0 | used as an unmodified library via `import`; you may replace it with your own build |
| [Pillow](https://python-pillow.org) | MIT-CMU (HPND) | drawing tray icons |
| [desktop-notifier](https://github.com/samschott/desktop-notifier) | MIT | native notifications |
| [tomli-w](https://github.com/hukkin/tomli-w) | MIT | writing `config.toml` |

Transitive dependencies (for example `absl-py`, `flatbuffers`, `sounddevice`, `matplotlib`,
`winrt-*`) are installed by the packages above under their own licenses. Run
`uv tree` to list them.

## Models

Downloaded once by `scripts/download_models.py` into `models/` (not committed):

| File | Source | License |
|---|---|---|
| `face_landmarker.task` | Google MediaPipe Face Landmarker | Apache-2.0 |
| `pose_landmarker_lite.task` | Google MediaPipe Pose Landmarker (lite) | Apache-2.0 |

See the MediaPipe model cards for details on training data and intended use.

## Assets

- `assets/icons/*.png`: drawn by `src/meerkat/tray.py` (`scripts/make_icons.py`), part of this project (MIT).
- `assets/sounds/*.wav`: synthesized by `scripts/make_sounds.py`, part of this project (MIT).

## Development tools

| Tool | License |
|---|---|
| [pytest](https://pytest.org) | MIT |
| [ruff](https://github.com/astral-sh/ruff) | MIT |
| [uv](https://github.com/astral-sh/uv) | MIT / Apache-2.0 |
