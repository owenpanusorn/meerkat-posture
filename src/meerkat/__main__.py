"""Entry point: ``python -m meerkat``."""

from __future__ import annotations

import argparse

from meerkat import __version__


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="meerkat", description="Offline posture reminder.")
    parser.add_argument("--debug", action="store_true", help="open the debug camera window")
    parser.add_argument("--camera", type=int, default=0, help="camera index (default 0)")
    parser.add_argument("--fps", type=float, default=5.0, help="frames per second (default 5)")
    parser.add_argument("--version", action="version", version=f"meerkat {__version__}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.debug:
        from meerkat import debug_view

        return debug_view.run(camera_index=args.camera, fps=args.fps)
    # Phase 2 will run the tray app here.
    print(f"meerkat {__version__}: tray app not implemented yet, try --debug")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
