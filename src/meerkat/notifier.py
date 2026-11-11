"""Native desktop notifications and alert sounds, delivered from one background thread.

Cooldowns are decided in ``rules.py``; this module only delivers messages.
"""

from __future__ import annotations

import logging
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from meerkat import paths

log = logging.getLogger(__name__)

APP_NAME = "Meerkat"
ICON_PATH = paths.ICONS_DIR / "meerkat_green.png"
SOUNDS_DIR = paths.SOUNDS_DIR

# Sound kinds. Info messages (calibration, settings) have no sound.
POSTURE = "posture"
BREAK = "break"
STYLES = ("meerkat", "system")

# Meerkat's voice: short, friendly, a little cheeky.
RULE_MESSAGES: dict[str, tuple[str, str]] = {
    "head_down": ("ก้มนานไปแล้วนะ", "เงยหน้าขึ้นมาหน่อย เหมือนเมียร์แคทยืนเฝ้ายาม"),
    "head_up": ("เงยหน้าค้างนานแล้ว", "ลดคางลงนิด ให้สายตาอยู่ระดับจอ"),
    "yaw_out": ("หันข้างนานแล้วนะ", "หันกลับมาตรงจอ หรือ Calibrate จอที่สองไว้ก็ได้"),
    "roll": ("คอเอียงอยู่นะ", "ตั้งหัวให้ตรง คอจะได้ไม่ล้า"),
    "lean_in": ("เข้าใกล้จอเกินไปแล้ว", "ถอยหลังพิงพนัก ให้จออยู่ห่างประมาณหนึ่งช่วงแขน"),
    "shoulder_tilt": ("ไหล่เอียงอยู่นะ", "นั่งให้น้ำหนักลงสองข้างเท่ากัน"),
    "twist": ("ตัวบิดอยู่นะ", "หันตัวให้ตรงกับจอ ไม่ใช่แค่หันหน้า"),
    "slouch": ("ค่อมแล้วนะ", "ยืดตัวขึ้น ดึงไหล่ไปข้างหลังเบา ๆ"),
    "phone": (
        "ก้มเล่นโทรศัพท์นานไปแล้วนะ",
        "ยกโทรศัพท์ขึ้นมาระดับสายตา หรือเปิด 'พักเล่นโทรศัพท์' จากเมนู Meerkat",
    ),
}


def phone_break_started(minutes: int) -> tuple[str, str]:
    return (
        f"พักเล่นโทรศัพท์ {minutes} นาที",
        "Meerkat จะไม่เตือนเรื่องท่าระหว่างนี้ (เตือนลุกยังทำงาน)",
    )


def phone_break_over() -> tuple[str, str]:
    return ("หมดเวลาพักแล้ว", "วางโทรศัพท์ เงยหน้า ยืดคอหน่อย แล้วกลับมาลุยต่อ")


def break_message(minutes: int) -> tuple[str, str]:
    return (
        f"นั่งมา {minutes} นาทีแล้ว",
        "ลุกขึ้นยืน เดินสัก 2-3 นาทีนะ เมียร์แคทก็ยังต้องลุกไปดูต้นทาง",
    )


def sound_path(kind: str) -> Path:
    return SOUNDS_DIR / f"{kind}.wav"


def user_can_be_disturbed() -> bool:
    """False while the user is presenting / in a full-screen app / in quiet time.

    Windows mutes notification sounds itself, but we play the meerkat sounds ourselves,
    so we ask the shell first. Other platforms: assume yes.
    """
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        QUNS_ACCEPTS_NOTIFICATIONS = 5
        state = ctypes.c_int(0)
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return True
        return state.value == QUNS_ACCEPTS_NOTIFICATIONS
    except Exception:
        return True


def play_file(path: Path) -> bool:
    """Start playing a WAV without blocking. Returns False if it couldn't."""
    try:
        if sys.platform == "win32":
            import winsound

            flags = winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
            winsound.PlaySound(str(path), flags)
            return True
        for player in ("afplay", "paplay", "aplay"):
            if exe := shutil.which(player):
                subprocess.Popen(
                    [exe, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                return True
    except Exception:
        log.exception("cannot play %s", path)
    return False


class Notifier:
    """Posture alerts and stand-up reminders can make a sound:

    - style "meerkat": our own short chirps (assets/sounds), different for each kind
    - style "system":  the OS default notification sound
    """

    def __init__(
        self,
        enabled: bool = True,
        sound_posture: bool = True,
        sound_break: bool = True,
        sound_style: str = "meerkat",
        sticky: bool = True,
    ) -> None:
        self.enabled = enabled
        self.sound_posture = sound_posture
        self.sound_break = sound_break
        self.sound_style = sound_style
        self.sticky = sticky
        self._q: queue.Queue[tuple[str, str, str | None, bool] | None] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="notifier", daemon=True)
        self._thread.start()

    def send(
        self, title: str, message: str, sound: str | None = None, sticky: bool = False
    ) -> None:
        """``sticky``: stay on screen until the user closes it (posture / stand-up alerts)."""
        if self.enabled:
            self._q.put((title, message, sound, sticky))

    def alert(self, rule: str) -> None:
        title, message = RULE_MESSAGES.get(rule, (rule, ""))
        self.send(title, message, sound=POSTURE if self.sound_posture else None, sticky=self.sticky)

    def break_reminder(self, minutes: int) -> None:
        self.send(
            *break_message(minutes),
            sound=BREAK if self.sound_break else None,
            sticky=self.sticky,
        )

    def close(self) -> None:
        self._q.put(None)
        self._thread.join(timeout=2)

    def _run(self) -> None:
        default_sound = None
        ok_button: tuple = ()
        try:
            from desktop_notifier import DEFAULT_SOUND, Button, DesktopNotifierSync, Icon

            default_sound = DEFAULT_SOUND
            ok_button = (Button(title="รับทราบ"),)
            kwargs = {"app_name": APP_NAME}
            if ICON_PATH.exists():
                kwargs["app_icon"] = Icon(path=ICON_PATH)
            notifier = DesktopNotifierSync(**kwargs)
            _install_sticky_toasts(self)
        except Exception:
            log.exception("desktop notifications unavailable")
            notifier = None

        while (item := self._q.get()) is not None:
            title, message, sound, sticky = item
            self._sending_sticky = sticky
            log.info("notify%s: %s / %s", f" ({sound})" if sound else "", title, message)

            system_sound = None
            if sound:
                path = sound_path(sound)
                if self.sound_style == "meerkat" and path.exists():
                    if user_can_be_disturbed():
                        play_file(path)
                else:
                    system_sound = default_sound

            if notifier is None:
                continue
            try:
                notifier.send(
                    title=title,
                    message=message,
                    sound=system_sound,
                    buttons=ok_button if sticky else (),
                )
            except Exception:
                log.exception("failed to show notification")


def _install_sticky_toasts(owner: Notifier) -> None:
    """Windows only: mark toasts as ``scenario="reminder"`` while ``owner`` is sending a
    sticky one. Windows then keeps the toast on screen until the user clicks a button or
    the close (X) instead of hiding it after ~5 s. desktop-notifier has no option for this,
    so we wrap the XML builder it uses. Reminder toasts need at least one button.
    """
    if sys.platform != "win32":
        return
    from desktop_notifier.backends import winrt

    original = winrt.Element
    if getattr(original, "_meerkat_wrapped", False):
        return

    def element(tag, attrib=None, **extra):
        el = original(tag, attrib or {}, **extra)
        if tag == "toast" and getattr(owner, "_sending_sticky", False):
            el.set("scenario", "reminder")
        return el

    element._meerkat_wrapped = True  # type: ignore[attr-defined]
    winrt.Element = element
