"""Write the README pictures to ``docs/images/``.

    uv run python scripts/make_readme_images.py           # meerkat poses + tray icons
    uv run python scripts/make_readme_images.py --buddy   # also a real shot of the pop-up

``--buddy`` (Windows) shows the buddy for a few seconds in front of a plain backdrop window
and grabs only that area of the screen, so nothing else on your screen ends up in the image.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from PIL import Image

from meerkat.buddy import KEY, MEERKAT_H, MEERKAT_W, draw_meerkat
from meerkat.tray import ICON_STATES, draw_icon

OUT = Path(__file__).resolve().parent.parent / "docs" / "images"
BACKDROP = "#f4f1ec"


def transparent(img: Image.Image) -> Image.Image:
    """Key color -> fully transparent (the drawing never uses the key color)."""
    import numpy as np

    arr = np.array(img.convert("RGBA"))
    arr[(arr[..., :3] == KEY).all(axis=-1)] = 0
    return Image.fromarray(arr)


def poses() -> Path:
    scale, gap = 1.2, 24
    w, h = round(MEERKAT_W * scale), round(MEERKAT_H * scale)
    out = Image.new("RGBA", (3 * w + 2 * gap, h), (0, 0, 0, 0))
    for i, pose in enumerate(("stand", "wave", "happy")):
        out.alpha_composite(transparent(draw_meerkat(pose, scale)), (i * (w + gap), 0))
    path = OUT / "meerkat-poses.png"
    out.save(path, optimize=True)
    return path


def icons() -> Path:
    size, gap = 96, 20
    out = Image.new("RGBA", (len(ICON_STATES) * (size + gap) - gap, size), (0, 0, 0, 0))
    for i, state in enumerate(ICON_STATES):
        out.alpha_composite(draw_icon(state, size), (i * (size + gap), 0))
    path = OUT / "tray-icons.png"
    out.save(path, optimize=True)
    return path


def buddy_shot() -> Path:
    import ctypes
    import tkinter as tk

    from PIL import ImageGrab

    from meerkat.buddy import Buddy, _BuddyWindow, work_area

    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # real pixels, same as the buddy thread
    dpi = ctypes.windll.user32.GetDpiForSystem() / 96
    left, top, right, bottom = work_area()
    pad = round(24 * dpi)
    w = round((_BuddyWindow.BUBBLE_W + MEERKAT_W) * dpi) + 16 + 2 * pad
    h = round(MEERKAT_H * dpi) + 2 * pad
    box = (left, bottom - h, left + w, bottom)

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg=BACKDROP)
    root.geometry(f"{w}x{h}+{box[0]}+{box[1]}")
    root.update()

    buddy = Buddy(lambda: None, lambda: None, 10)
    buddy.show(1, 30)
    end = time.monotonic() + 2.5
    while time.monotonic() < end:  # keep the backdrop responsive while the buddy slides in
        root.update()
        time.sleep(0.02)
    shot = ImageGrab.grab(bbox=box, all_screens=True)
    buddy.close()
    root.destroy()

    # Trim to the buddy, keep a little margin.
    bg = Image.new("RGB", shot.size, root_color(BACKDROP))
    from PIL import ImageChops

    bbox = ImageChops.difference(shot.convert("RGB"), bg).getbbox() or (0, 0, *shot.size)
    m = round(12 * dpi)
    crop = shot.crop(
        (max(0, bbox[0] - m), max(0, bbox[1] - m), min(w, bbox[2] + m), min(h, bbox[3] + m))
    )
    path = OUT / "buddy.png"
    crop.save(path, optimize=True)
    return path


def root_color(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i : i + 2], 16) for i in (1, 3, 5))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--buddy", action="store_true", help="also capture the pop-up (Windows)")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"wrote {poses()}")
    print(f"wrote {icons()}")
    if args.buddy:
        if sys.platform != "win32":
            print("--buddy needs Windows")
            return 1
        print(f"wrote {buddy_shot()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
