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

log = logging.getLogger(__name__)

APP_NAME = "Meerkat"
ASSETS = Path(__file__).resolve().parents[2] / "assets"
ICON_PATH = ASSETS / "icons" / "meerkat_green.png"
SOUNDS_DIR = ASSETS / "sounds"

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
}


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
    ) -> None:
        self.enabled = enabled
        self.sound_posture = sound_posture
        self.sound_break = sound_break
        self.sound_style = sound_style
        self._q: queue.Queue[tuple[str, str, str | None] | None] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="notifier", daemon=True)
        self._thread.start()

    def send(self, title: str, message: str, sound: str | None = None) -> None:
        if self.enabled:
            self._q.put((title, message, sound))

    def alert(self, rule: str) -> None:
        title, message = RULE_MESSAGES.get(rule, (rule, ""))
        self.send(title, message, sound=POSTURE if self.sound_posture else None)

    def break_reminder(self, minutes: int) -> None:
        self.send(*break_message(minutes), sound=BREAK if self.sound_break else None)

    def close(self) -> None:
        self._q.put(None)
        self._thread.join(timeout=2)

    def _run(self) -> None:
        default_sound = None
        try:
            from desktop_notifier import DEFAULT_SOUND, DesktopNotifierSync, Icon

            default_sound = DEFAULT_SOUND
            kwargs = {"app_name": APP_NAME}
            if ICON_PATH.exists():
                kwargs["app_icon"] = Icon(path=ICON_PATH)
            notifier = DesktopNotifierSync(**kwargs)
        except Exception:
            log.exception("desktop notifications unavailable")
            notifier = None

        while (item := self._q.get()) is not None:
            title, message, sound = item
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
                notifier.send(title=title, message=message, sound=system_sound)
            except Exception:
                log.exception("failed to show notification")
