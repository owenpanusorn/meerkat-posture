"""System tray icon + menu (PLAN.md section 10).

Icon images are drawn with Pillow (``draw_icon``). ``scripts/make_icons.py`` writes them
to ``assets/icons/``; the tray uses those files when present.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from PIL import Image, ImageDraw

from meerkat import paths

ICONS_DIR = paths.ICONS_DIR
ICON_STATES = ("green", "yellow", "red", "sleep")
CAMERA_CHOICES = (0, 1, 2, 3)
_BG = {
    "green": (46, 158, 68),
    "yellow": (230, 176, 0),
    "red": (208, 48, 48),
    "sleep": (130, 130, 140),
}


def draw_icon(state: str, size: int = 64) -> Image.Image:
    """The buddy's face (see ``buddy.draw_meerkat``) on a status-colored disc.

    Drawn 4x larger and scaled down for smooth edges.
    """
    from meerkat.buddy import BLUSH, DARK, FUR, FUR_DARK, FUR_LIGHT, NOSE, OUTLINE, PATCH

    ss = 4
    k = size * ss / 64
    img = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    lw = max(1, round(1.6 * k))

    def box(x0, y0, x1, y1):
        return [round(x0 * k), round(y0 * k), round(x1 * k), round(y1 * k)]

    def oval(b, fill, outline=False):
        d.ellipse(box(*b), fill=fill, outline=OUTLINE if outline else None, width=lw)

    def dot(x, y, r, fill):
        oval((x - r, y - r, x + r, y + r), fill)

    oval((1, 1, 63, 63), _BG[state])
    oval((7, 20, 19, 34), PATCH, outline=True)  # ears
    oval((45, 20, 57, 34), PATCH, outline=True)
    oval((11, 14, 53, 56), FUR, outline=True)  # head
    oval((22, 16.5, 42, 25), FUR_DARK)  # crown
    oval((16, 30, 48, 54.5), FUR_LIGHT)  # pale face
    oval((16, 27, 31, 42), PATCH)  # eye patches
    oval((33, 27, 48, 42), PATCH)
    if state == "sleep":
        for x in (23.5, 40.5):
            ew = max(1, round(2 * k))
            d.arc(box(x - 4.5, 30, x + 4.5, 37), 10, 170, fill=FUR_LIGHT, width=ew)
    else:
        for x in (23.5, 40.5):
            dot(x, 34.5, 5, DARK)
            dot(x - 1.6, 32.6, 1.9, (255, 255, 255))
    oval((13, 41, 21, 46.5), BLUSH)
    oval((43, 41, 51, 46.5), BLUSH)
    oval((28.5, 40, 35.5, 45), NOSE)
    mw = max(1, round(1.0 * k))
    d.arc(box(28.5, 43.5, 32, 47.5), 10, 170, fill=DARK, width=mw)
    d.arc(box(32, 43.5, 35.5, 47.5), 10, 170, fill=DARK, width=mw)
    return img.resize((size, size), Image.Resampling.LANCZOS)


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
    break_after_min: float

    def break_after_options(self) -> list[int]: ...
    def set_break_after(self, minutes: int) -> None: ...

    autostart_supported: bool
    autostart_enabled: bool

    def toggle_autostart(self) -> None: ...
    def open_data_folder(self) -> None: ...
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
        break_menu = Menu(
            lambda: [
                Item(
                    f"{m} นาที",
                    act(lambda m=m: ctl.set_break_after(m)),
                    checked=lambda item, m=m: ctl.break_after_min == m,
                    radio=True,
                )
                for m in ctl.break_after_options()
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
            Item(
                lambda item: f"เตือนลุกเมื่อนั่งครบ ({ctl.break_after_min:g} นาที)",
                break_menu,
            ),
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
            Item(
                "เปิดอัตโนมัติตอนเข้า Windows",
                act(ctl.toggle_autostart),
                checked=lambda item: ctl.autostart_enabled,
                visible=lambda item: ctl.autostart_supported,
            ),
            Item("เปิดไฟล์ config", act(ctl.open_config)),
            Item("เปิดโฟลเดอร์ข้อมูล / log", act(ctl.open_data_folder)),
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
