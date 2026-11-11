"""Entry point: ``python -m meerkat``."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from meerkat import __version__

# Quiet MediaPipe / TFLite native logging before it is imported.
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="meerkat", description="Offline posture reminder.")
    parser.add_argument(
        "--debug", action="store_true", help="only open the debug camera window (no tray)"
    )
    parser.add_argument("--camera", type=int, default=None, help="camera index for --debug")
    parser.add_argument("--fps", type=float, default=None, help="frames per second for --debug")
    parser.add_argument("--config", type=Path, default=None, help="path to config.toml")
    parser.add_argument(
        "--replay",
        type=Path,
        default=None,
        metavar="CSV",
        help="re-run the rules on a recorded session (numbers only) and print the alerts",
    )
    parser.add_argument("--version", action="version", version=f"meerkat {__version__}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    if args.replay:
        from meerkat import config, replay, storage

        try:
            samples = storage.read_session(args.replay)
        except (OSError, ValueError) as e:
            print(f"error: {e}")
            return 2
        events = replay.replay(samples, config.load(args.config))
        print(replay.report(events))
        return 0

    if args.debug:
        from meerkat import config, debug_view

        cam = config.load(args.config).camera
        return debug_view.run(
            camera_index=cam.index if args.camera is None else args.camera,
            fps=cam.fps if args.fps is None else args.fps,
            smoothing_s=cam.smoothing_s,
        )

    from meerkat.app import App

    return App(args.config).run()


if __name__ == "__main__":
    raise SystemExit(main())
