"""Entry point: ``python -m meerkat``."""

from __future__ import annotations

import argparse

from meerkat import __version__


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="meerkat", description="Offline posture reminder.")
    parser.add_argument("--debug", action="store_true", help="open the debug camera window")
    parser.add_argument("--version", action="version", version=f"meerkat {__version__}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    # Phase 1 will wire up camera -> detector -> metrics -> debug view here.
    print(f"meerkat {__version__} (debug={args.debug}) - not implemented yet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
