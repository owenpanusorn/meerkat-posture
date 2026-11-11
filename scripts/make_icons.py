"""Write the tray icons to ``assets/icons/meerkat_<state>.png``.

Run after changing ``meerkat.tray.draw_icon``:  ``uv run python scripts/make_icons.py``
"""

from __future__ import annotations

from meerkat.tray import ICON_STATES, ICONS_DIR, draw_icon


def main() -> int:
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    for state in ICON_STATES:
        path = ICONS_DIR / f"meerkat_{state}.png"
        draw_icon(state, 256).save(path)
        print(f"wrote {path}")
    ico = ICONS_DIR / "meerkat.ico"  # Windows .exe icon
    draw_icon("green", 256).save(ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])
    print(f"wrote {ico}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
