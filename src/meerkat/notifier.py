"""Native desktop notifications, sent from one background thread.

Cooldowns are decided in ``rules.py``; this module only delivers messages.
"""

from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "Meerkat"
ICON_PATH = Path(__file__).resolve().parents[2] / "assets" / "icons" / "meerkat_green.png"

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


class Notifier:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._q: queue.Queue[tuple[str, str] | None] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="notifier", daemon=True)
        self._thread.start()

    def send(self, title: str, message: str) -> None:
        if self.enabled:
            self._q.put((title, message))

    def alert(self, rule: str) -> None:
        title, message = RULE_MESSAGES.get(rule, (rule, ""))
        self.send(title, message)

    def break_reminder(self, minutes: int) -> None:
        self.send(*break_message(minutes))

    def close(self) -> None:
        self._q.put(None)
        self._thread.join(timeout=2)

    def _run(self) -> None:
        try:
            from desktop_notifier import DesktopNotifierSync, Icon

            kwargs = {"app_name": APP_NAME}
            if ICON_PATH.exists():
                kwargs["app_icon"] = Icon(path=ICON_PATH)
            notifier = DesktopNotifierSync(**kwargs)
        except Exception:
            log.exception("desktop notifications unavailable")
            notifier = None

        while (item := self._q.get()) is not None:
            title, message = item
            log.info("notify: %s / %s", title, message)
            if notifier is None:
                continue
            try:
                notifier.send(title=title, message=message)
            except Exception:
                log.exception("failed to show notification")
