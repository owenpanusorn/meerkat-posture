"""Entry point: ``python -m meerkat`` (and ``Meerkat.exe``)."""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
from pathlib import Path

from meerkat import __version__

# Quiet MediaPipe / TFLite native logging before it is imported.
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

log = logging.getLogger("meerkat")


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
    parser.add_argument(
        "--settings", action="store_true", help="open the settings window (edits config.toml)"
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="check models, icons and sounds load (no camera), log the result and exit",
    )
    parser.add_argument("--version", action="version", version=f"meerkat {__version__}")
    return parser.parse_args(argv)


def setup_logging() -> Path | None:
    """Log to the terminal when there is one, and always to meerkat.log (text only)."""
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if sys.stderr is not None:  # windowed .exe has no console
        h = logging.StreamHandler()
        h.setFormatter(fmt)
        root.addHandler(h)
    try:
        from meerkat.config import user_config_dir

        path = user_config_dir() / "meerkat.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            path, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)
        return path
    except OSError:
        return None


def selftest() -> int:
    """Load everything the app needs without touching the camera."""
    import numpy as np

    from meerkat import notifier, paths, tray
    from meerkat.detector import Detector

    log.info("selftest: frozen=%s root=%s", paths.is_frozen(), paths.resource_root())
    det = Detector()
    lm = det.detect(np.full((480, 640, 3), 128, np.uint8), 1)
    det.close()
    log.info("selftest: models ok (face=%s)", lm.face is not None)
    for state in tray.ICON_STATES:
        tray.load_icon(state)
    log.info("selftest: icons ok")
    for kind in (notifier.POSTURE, notifier.BREAK):
        if not notifier.sound_path(kind).exists():
            raise FileNotFoundError(notifier.sound_path(kind))
    log.info("selftest: sounds ok")
    import tkinter  # noqa: F401  (meerkat buddy window)

    import pystray  # noqa: F401
    from desktop_notifier import DesktopNotifierSync  # noqa: F401
    from PIL import ImageTk  # noqa: F401

    from meerkat.buddy import draw_meerkat

    draw_meerkat("wave", 1.5)
    log.info("selftest: buddy ok")
    from tkinter import ttk  # noqa: F401  (settings window)

    from meerkat import config, settings_window

    settings_window.apply(config.Config(), settings_window.defaults())
    log.info("selftest: settings ok")

    log.info("selftest: OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    log_path = setup_logging()

    if args.selftest:
        try:
            return selftest()
        except Exception:
            log.exception("selftest: FAILED")
            return 1

    if args.settings:
        from meerkat import settings_window

        return settings_window.run(args.config)

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

    from meerkat import autostart

    if not autostart.acquire_single_instance():
        log.info("another Meerkat is already running")
        from meerkat.notifier import Notifier

        n = Notifier()
        n.send("Meerkat เปิดอยู่แล้ว", "ดูที่ไอคอนเมียร์แคทใน system tray มุมขวาล่าง")
        n.close()
        return 0

    log.info("meerkat %s starting (log: %s)", __version__, log_path)
    from meerkat.app import App

    return App(args.config).run()


if __name__ == "__main__":
    raise SystemExit(main())
