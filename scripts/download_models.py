"""Download MediaPipe model files into ``models/``.

Run once during development:  ``uv run python scripts/download_models.py``

This is the ONLY place in the project allowed to touch the network. The app itself
loads models from ``models/`` and never downloads anything at runtime (PLAN.md section 2).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"

BASE = "https://storage.googleapis.com/mediapipe-models"
MODELS: dict[str, str] = {
    "face_landmarker.task": (
        f"{BASE}/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
    ),
    "pose_landmarker_lite.task": (
        f"{BASE}/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
    ),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as resp, tmp.open("wb") as out:
        while chunk := resp.read(1 << 16):
            out.write(chunk)
    tmp.replace(dest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download even if present")
    args = parser.parse_args(argv)

    MODELS_DIR.mkdir(exist_ok=True)
    for name, url in MODELS.items():
        dest = MODELS_DIR / name
        if dest.exists() and not args.force:
            print(f"skip  {name} (exists)")
        else:
            print(f"get   {name} <- {url}")
            download(url, dest)
        print(f"      {dest.stat().st_size:,} bytes  sha256={sha256(dest)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
