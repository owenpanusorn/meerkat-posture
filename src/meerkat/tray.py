"""System tray icon + menu (PLAN.md section 10).

Icon images are drawn with Pillow (``draw_icon``). ``scripts/make_icons.py`` writes them
to ``assets/icons/``; the tray uses those files when present.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageDraw

ICONS_DIR = Path(__file__).resolve().parents[2] / "assets" / "icons"
ICON_STATES = ("green", "yellow", "red", "sleep")
CAMERA_CHOICES = (0, 1, 2, 3)
_BG = {
    "green": (46, 158, 68),
    "yellow": (230, 176, 0),
    "red": (208, 48, 48),
    "sleep": (130, 130, 140),
}
_FUR = (222, 190, 140)
_DARK = (60, 42, 30)


def draw_icon(state: str, size: int = 64) -> Image.Image:
    """A simple meerkat face on a status-colored disc."""
    s = size / 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def box(x0, y0, x1, y1):
        return [round(x0 * s), round(y0 * s), round(x1 * s), round(y1 * s)]

    d.ellipse(box(1, 1, 63, 63), fill=_BG[state])
    d.ellipse(box(14, 9, 24, 21), fill=_FUR)  # ears
    d.ellipse(box(40, 9, 50, 21), fill=_FUR)
    d.ellipse(box(15, 12, 49, 56), fill=_FUR)  # head
    if state == "sleep":
        d.line(box(21, 31, 29, 31), fill=_DARK, width=max(1, round(3 * s)))
        d.line(box(35, 31, 43, 31), fill=_DARK, width=max(1, round(3 * s)))
    else:
        d.ellipse(box(19, 25, 30, 37), fill=_DARK)  # dark eye patches
        d.ellipse(box(34, 25, 45, 37), fill=_DARK)
        d.ellipse(box(23, 28, 27, 32), fill=(255, 255, 255))
        d.ellipse(box(38, 28, 42, 32), fill=(255, 255, 255))
    d.ellipse(box(28, 43, 36, 49), fill=_DARK)  # nose
    return img


def load_icon(state: str) -> Image.Image:
    path = ICONS_DIR / f"meerkat_{state}.png"
    if path.exists():
        return Image.open(path).convert("RGBA")
    return draw_icon(state)


class Controller(Protocol):
    """What the tray needs from the app."""

    paused: bool
    debug_enabled: bool
    recording: bool
    camera_index: int
    phone_break_active: bool

    def phone_break_options(self) -> list[int]: ...
    def start_phone_break(self, minutes: int) -> None: ...
    def end_phone_break(self) -> None: ...
    def status_text(self) -> str: ...
    def stats_lines(self) -> list[str]: ...
    def has_zone(self, zone: str) -> bool: ...
    def select_camera(self, index: int) -> None: ...
    def toggle_recording(self) -> None: ...
    def pause(self, minutes: float | None) -> None: ...
    def resume(self) -> None: ...
    def snooze_sitting(self) -> None: ...
    def calibrate(self, zone: str) -> None: ...
    def remove_zone(self, zone: str) -> None: ...
    def toggle_debug(self) -> None: ...
    def open_config(self) -> None: ...
    def quit(self) -> None: ...


class Tray:
    def __init__(self, ctl: Controller) -> None:
        import pystray

        self._pystray = pystray
        self.ctl = ctl
        self._images = {state: load_icon(state) for state in ICON_STATES}
        self._state = "green"
        self.icon = pystray.Icon("meerkat", self._images["green"], "Meerkat", self._menu())

    def _menu(self):
        Item, Menu = self._pystray.MenuItem, self._pystray.Menu
        ctl = self.ctl

        def act(fn: Callable[[], None]):
            return lambda icon, item: fn()

        pause_menu = Menu(
            Item("15 นาที", act(lambda: ctl.pause(15))),
            Item("30 นาที", act(lambda: ctl.pause(30))),
            Item("1 ชั่วโมง", act(lambda: ctl.pause(60))),
            Item("จนกว่าจะกดเปิด", act(lambda: ctl.pause(None))),
        )
        stats_menu = Menu(lambda: [Item(line, None, enabled=False) for line in ctl.stats_lines()])
        phone_menu = Menu(
            lambda: [
                Item(f"{m} นาที", act(lambda m=m: ctl.start_phone_break(m)))
                for m in ctl.phone_break_options()
            ]
        )
        camera_menu = Menu(
            *(
                Item(
                    f"กล้อง {i}",
                    act(lambda i=i: ctl.select_camera(i)),
                    checked=lambda item, i=i: ctl.camera_index == i,
                    radio=True,
                )
                for i in CAMERA_CHOICES
            )
        )
        return Menu(
            Item(lambda item: ctl.status_text(), None, enabled=False),
            Item("สถิติวันนี้", stats_menu),
            Menu.SEPARATOR,
            Item("หยุดชั่วคราว (ปิดกล้อง)", pause_menu, visible=lambda item: not ctl.paused),
            Item("เปิดต่อ", act(ctl.resume), visible=lambda item: ctl.paused),
            Item(
                "พักเล่นโทรศัพท์",
                phone_menu,
                visible=lambda item: not ctl.paused and not ctl.phone_break_active,
            ),
            Item(
                "จบพักเล่นโทรศัพท์",
                act(ctl.end_phone_break),
                visible=lambda item: ctl.phone_break_active,
            ),
            Item("เลื่อนเตือนลุก", act(ctl.snooze_sitting)),
            Menu.SEPARATOR,
            Item("Calibrate จอหลัก", act(lambda: ctl.calibrate("main"))),
            Item("Calibrate จอที่สอง", act(lambda: ctl.calibrate("second"))),
            Item(
                "ลบโซนจอที่สอง",
                act(lambda: ctl.remove_zone("second")),
                visible=lambda item: ctl.has_zone("second"),
            ),
            Item("เลือกกล้อง", camera_menu),
            Menu.SEPARATOR,
            Item(
                "บันทึก session (ตัวเลขเท่านั้น)",
                act(ctl.toggle_recording),
                checked=lambda item: ctl.recording,
            ),
            Item(
                "หน้าต่าง debug",
                act(ctl.toggle_debug),
                checked=lambda item: ctl.debug_enabled,
            ),
            Item("เปิดไฟล์ config", act(ctl.open_config)),
            Item("ออก", act(ctl.quit)),
        )

    def set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.icon.icon = self._images[state]

    def refresh(self) -> None:
        self.icon.update_menu()

    def run(self, setup: Callable[[], None]) -> None:
        """Blocks in the main thread. ``setup`` runs once the icon is visible."""

        def _setup(icon):
            icon.visible = True
            setup()

        self.icon.run(setup=_setup)

    def stop(self) -> None:
        self.icon.stop()
