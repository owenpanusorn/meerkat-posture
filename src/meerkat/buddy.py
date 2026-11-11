"""Meerkat buddy: a little standing meerkat that pops up to get you on your feet.

Used only for the stand-up reminder (posture alerts stay as small notifications):

    level 1  pops up above the taskbar, bottom-right, holding up "time to stand!"
    level 2  after ``escalate_after_min``: hops to get your attention
    level 3  after ``center_after_min``: walks to the middle of the screen (optional)

It disappears by itself once the camera sees you leave the desk, and pops up briefly
to cheer when you come back. Click its buttons to acknowledge or snooze.

The window is a frameless, always-on-top Tk window with a transparent key color. All Tk
calls happen on the buddy's own thread. ``Nudge`` (the escalation timing) and
``draw_meerkat`` are pure and tested without a display.
"""

from __future__ import annotations

import logging
import math
import queue
import sys
import threading
import time
from collections.abc import Callable

from PIL import Image, ImageDraw

log = logging.getLogger(__name__)

# ------------------------------------------------------------------- timing


class Nudge:
    """Escalation level of the current stand-up reminder. Pure."""

    def __init__(
        self, escalate_after_s: float = 300.0, center_after_s: float = 600.0, center: bool = True
    ) -> None:
        self.escalate_after_s = escalate_after_s
        self.center_after_s = center_after_s
        self.center = center
        self._start: float | None = None

    @property
    def active(self) -> bool:
        return self._start is not None

    def start(self, t: float) -> None:
        if self._start is None:
            self._start = t

    def stop(self) -> None:
        self._start = None

    def level(self, t: float) -> int:
        if self._start is None:
            return 0
        waited = t - self._start
        if self.center and waited >= self.center_after_s:
            return 3
        if waited >= self.escalate_after_s:
            return 2
        return 1


# ------------------------------------------------------------------ drawing

KEY = (255, 0, 255)  # transparent color of the window; never used in the drawing
KEY_HEX = "#ff00ff"
FUR = (214, 178, 128)
FUR_LIGHT = (240, 220, 186)
DARK = (70, 50, 36)
OUTLINE = (92, 66, 44)
WHITE = (255, 255, 255)

MEERKAT_W, MEERKAT_H = 150, 230


def draw_meerkat(pose: str = "stand", scale: float = 1.0) -> Image.Image:
    """A standing meerkat on the key color. Poses: stand, wave, happy.

    Drawn without anti-aliasing so the transparent key color has no fringe.
    """
    w, h = round(MEERKAT_W * scale), round(MEERKAT_H * scale)
    img = Image.new("RGB", (w, h), KEY)
    d = ImageDraw.Draw(img)
    lw = max(2, round(2 * scale))

    def b(x0, y0, x1, y1):
        return [round(x0 * scale), round(y0 * scale), round(x1 * scale), round(y1 * scale)]

    def p(*pts):
        return [(round(x * scale), round(y * scale)) for x, y in pts]

    # tail (behind the body)
    d.line(p((100, 200), (122, 190), (134, 168), (138, 140)), fill=OUTLINE, width=round(9 * scale))
    d.line(p((100, 200), (122, 190), (134, 168), (138, 140)), fill=FUR, width=round(5 * scale))
    # feet
    d.ellipse(b(42, 206, 74, 222), fill=DARK)
    d.ellipse(b(76, 206, 108, 222), fill=DARK)
    # body + belly
    d.ellipse(b(38, 92, 112, 216), fill=FUR, outline=OUTLINE, width=lw)
    d.ellipse(b(55, 112, 95, 206), fill=FUR_LIGHT)
    # arms
    d.ellipse(b(48, 118, 66, 152), fill=FUR, outline=OUTLINE, width=lw)
    if pose == "wave":
        d.line(p((92, 122), (114, 92), (124, 64)), fill=OUTLINE, width=round(15 * scale))
        d.line(p((92, 122), (114, 92), (124, 64)), fill=FUR, width=round(10 * scale))
        d.ellipse(b(116, 52, 134, 70), fill=FUR, outline=OUTLINE, width=lw)
    else:
        d.ellipse(b(84, 118, 102, 152), fill=FUR, outline=OUTLINE, width=lw)
    # head
    d.ellipse(b(40, 44, 50, 58), fill=DARK)  # ears
    d.ellipse(b(100, 44, 110, 58), fill=DARK)
    d.ellipse(b(44, 28, 106, 96), fill=FUR, outline=OUTLINE, width=lw)
    d.ellipse(b(60, 62, 90, 104), fill=FUR_LIGHT, outline=OUTLINE, width=lw)  # snout
    d.ellipse(b(52, 30, 98, 44), fill=(196, 160, 112))  # darker crown
    # eyes: dark patches
    d.ellipse(b(52, 48, 70, 68), fill=DARK)
    d.ellipse(b(80, 48, 98, 68), fill=DARK)
    if pose == "happy":
        d.arc(b(55, 54, 67, 66), 200, 340, fill=WHITE, width=lw)
        d.arc(b(83, 54, 95, 66), 200, 340, fill=WHITE, width=lw)
        d.arc(b(67, 92, 83, 103), 30, 150, fill=DARK, width=lw)  # smile
    else:
        d.ellipse(b(58, 53, 65, 60), fill=WHITE)
        d.ellipse(b(86, 53, 93, 60), fill=WHITE)
    d.ellipse(b(70, 88, 80, 95), fill=DARK)  # nose
    return img


# ------------------------------------------------------------------- texts

MESSAGES = {
    1: ("นั่งมา {minutes} นาทีแล้ว", "ลุกยืดเส้นกันหน่อย!"),
    2: ("ยังนั่งอยู่เลยนะ", "ลุกเดินสัก 2-3 นาที"),
    3: ("เมียร์แคทยืนรออยู่นะ", "ลุกขึ้นมายืนด้วยกัน!"),
    "celebrate": ("เก่งมาก!", "กลับมาสดชื่นแล้ว"),
}
CELEBRATE_S = 4.0


def work_area() -> tuple[int, int, int, int]:
    """(left, top, right, bottom) of the primary screen excluding the taskbar."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            rect = wintypes.RECT()
            SPI_GETWORKAREA = 0x0030
            if ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
            ):
                return rect.left, rect.top, rect.right, rect.bottom
        except Exception:
            pass
    return 0, 0, 0, 0  # caller falls back to Tk's screen size


# ------------------------------------------------------------------- window


class Buddy:
    """Thread-safe front end. Methods only queue commands for the Tk thread."""

    def __init__(
        self,
        on_ack: Callable[[], None],
        on_snooze: Callable[[], None],
        snooze_min: float = 10.0,
    ) -> None:
        self.on_ack = on_ack
        self.on_snooze = on_snooze
        self.snooze_min = snooze_min
        self._q: queue.Queue[tuple] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="buddy", daemon=True)
        self._thread.start()

    def show(self, level: int, minutes: int) -> None:
        self._q.put(("show", level, minutes))

    def celebrate(self) -> None:
        self._q.put(("celebrate",))

    def hide(self) -> None:
        self._q.put(("hide",))

    def close(self) -> None:
        self._q.put(("close",))
        self._thread.join(timeout=3)

    # ---- Tk thread below -------------------------------------------------

    def _run(self) -> None:
        dpi = _make_thread_dpi_aware()
        try:
            import tkinter as tk

            from PIL import ImageTk
        except Exception:
            log.exception("buddy disabled: tkinter unavailable")
            return
        try:
            _BuddyWindow(self, tk, ImageTk, dpi).loop()
        except Exception:
            log.exception("buddy crashed")


class _BuddyWindow:
    BUBBLE_W = 230

    def __init__(self, owner: Buddy, tk, image_tk, dpi: float = 1.0) -> None:
        self.owner = owner
        self.tk = tk
        self.image_tk = image_tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.win = None
        self.canvas = None
        self.images: dict[str, object] = {}
        self.scale = 0.0
        self.dpi = dpi  # windows of this thread render at real resolution
        self.big = 1.0
        self.level = 0
        self.pos = (0.0, 0.0)
        self.target = (0.0, 0.0)
        self.size = (0, 0)
        self.hiding = False
        self.hide_at: float | None = None
        self.shown_at = 0.0

    def loop(self) -> None:
        self.root.after(50, self._poll)
        self.root.after(33, self._animate)
        self.root.mainloop()

    # ---- commands

    def _poll(self) -> None:
        try:
            while True:
                cmd, *args = self.owner._q.get_nowait()
                if cmd == "show":
                    self._show(*args)
                elif cmd == "celebrate":
                    self._celebrate()
                elif cmd == "hide":
                    self._hide()
                elif cmd == "close":
                    self.root.quit()
                    return
        except queue.Empty:
            pass
        self.root.after(50, self._poll)

    def _show(self, level: int, minutes: int) -> None:
        title, line = MESSAGES[level]
        scale = (1.5 if level == 3 else 1.0) * self.dpi
        self._build(scale, "wave" if level >= 2 else "stand", title.format(minutes=minutes), line)
        self.level = level
        self.hide_at = None
        self.target = self._home(level)

    def _celebrate(self) -> None:
        title, line = MESSAGES["celebrate"]
        self._build(self.dpi, "happy", title, line, buttons=False)
        self.level = 1
        self.target = self._home(1)
        self.hide_at = time.monotonic() + CELEBRATE_S

    def _hide(self) -> None:
        if self.win is None:
            return
        self.hiding = True
        left, top, right, bottom = self._area()
        self.target = (self.pos[0], bottom + 10)

    # ---- geometry

    def _area(self) -> tuple[int, int, int, int]:
        area = work_area()
        if area[2] <= area[0]:
            return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        return area

    def _home(self, level: int) -> tuple[float, float]:
        left, top, right, bottom = self._area()
        w, h = self.size
        if level == 3:
            return (left + right - w) / 2, (top + bottom - h) / 2
        return right - w - 16, bottom - h

    # ---- window

    def _build(self, scale: float, pose: str, title: str, line: str, buttons: bool = True) -> None:
        tk = self.tk
        fresh = self.win is None or scale != self.scale
        if fresh:
            if self.win is not None:
                self.win.destroy()
            self.scale = scale
            mw, mh = round(MEERKAT_W * scale), round(MEERKAT_H * scale)
            bw = round(self.BUBBLE_W * scale)
            self.size = (bw + mw, mh)
            self.win = tk.Toplevel(self.root)
            self.win.overrideredirect(True)
            self.win.attributes("-topmost", True)
            self.win.configure(bg=KEY_HEX)
            self.win.attributes("-transparentcolor", KEY_HEX)
            self.canvas = tk.Canvas(
                self.win, width=self.size[0], height=self.size[1], bg=KEY_HEX, highlightthickness=0
            )
            self.canvas.pack()
            left, top, right, bottom = self._area()
            corner = scale <= self.dpi + 1e-6
            start = self._home(1 if corner else 3)
            self.pos = (start[0], bottom + 10) if corner else start
            self._place()
            self.win.update_idletasks()
            _no_activate(self.win)
        self.hiding = False
        self._draw(pose, title, line, buttons)
        self.shown_at = time.monotonic()

    def _draw(self, pose: str, title: str, line: str, buttons: bool) -> None:
        c, s = self.canvas, self.scale
        c.delete("all")
        bw = round(self.BUBBLE_W * s)
        key = f"{pose}@{s}"
        if key not in self.images:
            self.images[key] = self.image_tk.PhotoImage(draw_meerkat(pose, s))
        c.create_image(bw, 0, image=self.images[key], anchor="nw")

        # speech bubble with a little tail pointing at the meerkat
        x0, y0, x1 = round(6 * s), round(20 * s), bw - round(8 * s)
        y1 = round((132 if buttons else 100) * s)
        r = round(14 * s)
        _round_rect(c, x0, y0, x1, y1, r, fill="white", outline="#5c422c", width=2)
        ty = round(60 * s)
        c.create_polygon(
            x1 - 1,
            ty - round(10 * s),
            x1 + round(18 * s),
            ty + round(4 * s),
            x1 - 1,
            ty + round(10 * s),
            fill="white",
            outline="#5c422c",
            width=2,
        )
        c.create_line(x1 - 1, ty - round(9 * s), x1 - 1, ty + round(9 * s), fill="white", width=3)
        font = "Leelawadee UI" if sys.platform == "win32" else "TkDefaultFont"
        c.create_text(
            (x0 + x1) / 2,
            y0 + round(24 * s),
            text=title,
            font=(font, -round(17 * s), "bold"),
            fill="#3c2a1c",
        )
        c.create_text(
            (x0 + x1) / 2,
            y0 + round(52 * s),
            text=line,
            font=(font, -round(15 * s)),
            fill="#3c2a1c",
        )
        if buttons:
            by = y1 - round(32 * s)
            half = (x0 + x1) / 2
            self._button(x0 + round(10 * s), by, half - round(4 * s), "รับทราบ", self._ack, font)
            self._button(
                half + round(4 * s),
                by,
                x1 - round(10 * s),
                f"เลื่อน {self.owner.snooze_min:g} นาที",
                self._snooze,
                font,
            )

    def _button(self, x0, y, x1, text, action, font) -> None:
        c, s = self.canvas, self.scale
        tag = f"btn{int(x0)}"
        _round_rect(
            c,
            x0,
            y,
            x1,
            y + round(24 * s),
            round(8 * s),
            fill="#f3e6d3",
            outline="#b08a5c",
            width=1,
            tags=tag,
        )
        c.create_text(
            (x0 + x1) / 2,
            y + round(12 * s),
            text=text,
            font=(font, -round(13 * s)),
            fill="#3c2a1c",
            tags=tag,
        )
        c.tag_bind(tag, "<Button-1>", lambda e: action())
        c.tag_bind(tag, "<Enter>", lambda e: c.config(cursor="hand2"))
        c.tag_bind(tag, "<Leave>", lambda e: c.config(cursor=""))

    def _ack(self) -> None:
        self._hide()
        _safe(self.owner.on_ack)

    def _snooze(self) -> None:
        self._hide()
        _safe(self.owner.on_snooze)

    # ---- animation

    def _place(self) -> None:
        self.win.geometry(f"+{round(self.pos[0])}+{round(self.pos[1] + self._hop())}")

    def _hop(self) -> float:
        if self.level < 2 or self.hiding or self.hide_at is not None:
            return 0.0
        phase = (time.monotonic() - self.shown_at) % 2.0
        return -abs(math.sin(phase / 0.6 * math.pi)) * 14 * self.scale if phase < 0.6 else 0.0

    def _animate(self) -> None:
        try:
            if self.win is not None:
                x, y = self.pos
                tx, ty = self.target
                self.pos = (x + (tx - x) * 0.18, y + (ty - y) * 0.18)
                self._place()
                if self.hide_at is not None and time.monotonic() >= self.hide_at:
                    self.hide_at = None
                    self._hide()
                if self.hiding and abs(self.pos[1] - ty) < 2:
                    self.win.destroy()
                    self.win = None
                    self.hiding = False
                    self.level = 0
        except Exception:
            log.exception("buddy animation")
        self.root.after(33, self._animate)


def _round_rect(c, x0, y0, x1, y1, r, **kw) -> None:
    pts = [
        x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
        x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
    ]  # fmt: skip
    c.create_polygon(pts, smooth=True, **kw)


def _make_thread_dpi_aware() -> float:
    """Windows: render this thread's windows at the real screen resolution (sharp on
    125%/150% displays) and return the scale factor to size them with."""
    if sys.platform != "win32":
        return 1.0
    try:
        import ctypes

        user32 = ctypes.windll.user32
        PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
        user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        if not user32.SetThreadDpiAwarenessContext(PER_MONITOR_AWARE_V2):
            return 1.0
        return max(1.0, user32.GetDpiForSystem() / 96)
    except Exception:
        return 1.0


def _no_activate(win) -> None:
    """Windows: don't steal focus from the user's app, and keep out of the taskbar."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_NOACTIVATE = 0x08000000
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(win.winfo_id())
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
    except Exception:
        log.exception("cannot set no-activate style")


def _safe(fn: Callable[[], None]) -> None:
    try:
        fn()
    except Exception:
        log.exception("buddy callback failed")
