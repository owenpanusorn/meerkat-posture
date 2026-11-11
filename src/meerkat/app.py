"""Wires everything together (PLAN.md section 5).

Threads:
    main     - tray icon (pystray needs the main thread on macOS)
    worker   - camera -> detector -> metrics -> rules / sitting -> notifier + tray state
    notifier - delivers desktop notifications

Tray callbacks never touch the camera. They queue commands for the worker.
"""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from meerkat import calibration, config
from meerkat.camera import Camera, CameraError
from meerkat.debug_view import DebugWindow
from meerkat.detector import Detector
from meerkat.metrics import PostureMetrics, Smoother, compute_metrics
from meerkat.notifier import Notifier
from meerkat.rules import RULE_ORDER, Evaluation, RulesEngine, State
from meerkat.sitting import SittingTimer
from meerkat.tray import Tray

log = logging.getLogger(__name__)

CAL_COUNTDOWN_S = 5.0
CONFIG_CHECK_S = 5.0
MENU_REFRESH_S = 5.0
CAMERA_RETRY_S = 10.0
_ICON_FOR_STATE = {State.OK: "green", State.WARN: "yellow", State.ALERT: "red"}


@dataclass
class _Calibration:
    zone: str
    start_at: float
    end_at: float
    samples: list[PostureMetrics]


class App:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or config.default_config_path()
        self.cfg = config.load(self.config_path)
        if not self.config_path.exists():
            config.save(self.cfg, self.config_path)  # give the user a file to edit
        self._cfg_mtime = self._mtime()

        self.zones = calibration.load_zones(self.cfg.zones)
        self.rules = RulesEngine(self.cfg.rules, self.cfg.alerts)
        self.sitting = SittingTimer()
        self._apply_sitting_config()
        self.smoother = Smoother(self.cfg.camera.smoothing_s)
        self.notifier = Notifier(self.cfg.alerts.notifications)

        self.paused = False
        self.debug_enabled = False
        self._pause_until: float | None = None
        self._cal: _Calibration | None = None
        self._status = "กำลังเปิดกล้อง..."
        self._cmds: queue.Queue[tuple] = queue.Queue()
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._run_worker, name="worker", daemon=True)
        self.tray = Tray(self)

    # ---------------------------------------------------------------- lifecycle

    def run(self) -> int:
        try:
            self.tray.run(setup=self._worker.start)
        finally:
            self._stop.set()
            if self._worker.is_alive():
                self._worker.join(timeout=5)
            self.notifier.close()
        return 0

    # ------------------------------------------------- tray Controller interface

    def status_text(self) -> str:
        return self._status

    def has_zone(self, zone: str) -> bool:
        return zone in self.zones

    def pause(self, minutes: float | None) -> None:
        self._cmds.put(("pause", minutes))

    def resume(self) -> None:
        self._cmds.put(("resume",))

    def snooze_sitting(self) -> None:
        self._cmds.put(("snooze",))

    def calibrate(self, zone: str) -> None:
        self._cmds.put(("calibrate", zone))

    def remove_zone(self, zone: str) -> None:
        self._cmds.put(("remove_zone", zone))

    def toggle_debug(self) -> None:
        self.debug_enabled = not self.debug_enabled

    def open_config(self) -> None:
        path = self.config_path
        if not path.exists():
            config.save(self.cfg, path)
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError:
            log.exception("cannot open %s", path)

    def quit(self) -> None:
        self._stop.set()
        self.tray.stop()

    # ------------------------------------------------------------------ worker

    def _run_worker(self) -> None:
        try:
            detector = Detector()
        except Exception as e:
            log.exception("cannot load models")
            self.notifier.send("Meerkat เปิดไม่ได้", str(e))
            self.quit()
            return

        cam: Camera | None = None
        window = DebugWindow()
        next_camera_try = 0.0
        next_config_check = time.monotonic() + CONFIG_CHECK_S
        next_menu_refresh = 0.0
        bad_reads = 0

        if calibration.MAIN not in self.zones:
            self._start_calibration(calibration.MAIN, time.monotonic(), first_run=True)

        try:
            while not self._stop.is_set():
                now = time.monotonic()
                self._handle_commands(now)

                if now >= next_config_check:
                    next_config_check = now + CONFIG_CHECK_S
                    if self._reload_config_if_changed() and cam is not None:
                        cam.release()  # pick up camera index / fps changes
                        cam = None

                if self._pause_until is not None and now >= self._pause_until:
                    self._resume()

                if self.paused or not self.debug_enabled:
                    window.close()

                if self.paused:
                    if cam is not None:
                        cam.release()  # really turn the camera off
                        cam = None
                    self._set_status(self._paused_text(), "sleep")
                    self._stop.wait(0.5)
                    continue

                if cam is None:
                    if now < next_camera_try:
                        self._stop.wait(0.5)
                        continue
                    cam = Camera(self.cfg.camera.index, self.cfg.camera.fps)
                    try:
                        cam.open()
                        bad_reads = 0
                    except CameraError:
                        log.warning("camera %d not available", self.cfg.camera.index)
                        self._set_status("เปิดกล้องไม่ได้ จะลองใหม่", "sleep")
                        cam = None
                        next_camera_try = now + CAMERA_RETRY_S
                        continue

                frame = cam.read()
                if frame is None:
                    bad_reads += 1
                    if bad_reads >= 10:
                        cam.release()
                        cam = None
                        next_camera_try = time.monotonic() + CAMERA_RETRY_S
                    continue
                bad_reads = 0

                now = time.monotonic()
                lm = detector.detect(frame, int(now * 1000))
                raw = compute_metrics(lm)
                m = self.smoother.update(now, raw)
                ev = self._evaluate(now, raw, m)

                if self.debug_enabled and not window.show(frame, lm, m, self._debug_lines(ev)):
                    self.debug_enabled = False
                del frame, lm  # frames are never kept

                if now >= next_menu_refresh:
                    next_menu_refresh = now + MENU_REFRESH_S
                    self.tray.refresh()
        except Exception:
            log.exception("worker crashed")
            self.notifier.send("Meerkat หยุดทำงาน", "เกิดข้อผิดพลาด ดูรายละเอียดใน terminal")
            self.quit()
        finally:
            window.close()
            if cam is not None:
                cam.release()
            detector.close()

    def _evaluate(self, now: float, raw: PostureMetrics, m: PostureMetrics) -> Evaluation:
        if self._cal is not None:
            self._calibration_step(now, raw)
            ev = Evaluation(State.OK)
        else:
            ev = self.rules.update(now, m, self.zones)
            for rule in ev.alerts:
                self.notifier.alert(rule)

        if self.sitting.update(now, m.present):
            self.notifier.break_reminder(int(self.sitting.sitting_s(now) // 60))

        self._set_status(self._live_text(now, m), _ICON_FOR_STATE[ev.status])
        return ev

    def _handle_commands(self, now: float) -> None:
        while True:
            try:
                cmd, *args = self._cmds.get_nowait()
            except queue.Empty:
                return
            if cmd == "pause":
                (minutes,) = args
                self.paused = True
                self._pause_until = None if minutes is None else now + minutes * 60
                self._cal = None
                self.rules.reset()
                self.sitting.reset()
                self.smoother.reset()
                self.tray.refresh()
            elif cmd == "resume":
                self._resume()
            elif cmd == "snooze":
                minutes = self.cfg.sitting.snooze_min
                self.sitting.snooze(now, minutes * 60)
                self.notifier.send("เลื่อนเตือนลุกแล้ว", f"จะไม่เตือนให้ลุกไป {minutes:g} นาที")
            elif cmd == "calibrate":
                (zone,) = args
                if self.paused:
                    self._resume()
                self._start_calibration(zone, now)
            elif cmd == "remove_zone":
                (zone,) = args
                if self.cfg.zones.pop(zone, None) is not None:
                    self._save_config()
                    self.zones = calibration.load_zones(self.cfg.zones)
                    self.rules.reset()
                    self.tray.refresh()

    def _resume(self) -> None:
        self.paused = False
        self._pause_until = None
        self.tray.refresh()

    # ------------------------------------------------------------- calibration

    def _start_calibration(self, zone: str, now: float, first_run: bool = False) -> None:
        label = calibration.ZONE_LABELS.get(zone, zone)
        start = now + CAL_COUNTDOWN_S
        self._cal = _Calibration(zone, start, start + calibration.CAPTURE_S, [])
        intro = "สวัสดี! Meerkat ขอจำท่านั่งดีของคุณก่อน " if first_run else ""
        self.notifier.send(
            f"Calibrate {label}",
            f"{intro}นั่งหลังตรง มอง{label} แล้วนิ่งไว้ "
            f"เริ่มใน {CAL_COUNTDOWN_S:g} วินาที ใช้เวลา {calibration.CAPTURE_S:g} วินาที",
        )

    def _calibration_step(self, now: float, raw: PostureMetrics) -> None:
        cal = self._cal
        if now < cal.start_at:
            return
        if now < cal.end_at:
            cal.samples.append(raw)
            return
        self._cal = None
        label = calibration.ZONE_LABELS.get(cal.zone, cal.zone)
        baseline = calibration.average(cal.samples) if calibration.capture_ok(cal.samples) else None
        if baseline is None:
            self.notifier.send(
                "Calibrate ไม่สำเร็จ",
                "มองไม่เห็นหน้าชัดพอ ลองใหม่จากเมนู Calibrate ที่ไอคอน Meerkat",
            )
            return
        self.cfg.zones[cal.zone] = calibration.to_config(baseline)
        self._save_config()
        self.zones = calibration.load_zones(self.cfg.zones)
        self.rules.reset()
        self.tray.refresh()
        log.info("calibrated %s: %s", cal.zone, self.cfg.zones[cal.zone])
        self.notifier.send("จำแล้ว!", f"Meerkat จำท่านั่งดีตอนมอง{label}ไว้แล้ว")

    # ------------------------------------------------------------------ config

    def _mtime(self) -> float | None:
        try:
            return self.config_path.stat().st_mtime
        except OSError:
            return None

    def _save_config(self) -> None:
        config.save(self.cfg, self.config_path)
        self._cfg_mtime = self._mtime()

    def _reload_config_if_changed(self) -> bool:
        """Return True if camera settings changed."""
        mtime = self._mtime()
        if mtime is None or mtime == self._cfg_mtime:
            return False
        self._cfg_mtime = mtime
        try:
            new = config.load(self.config_path)
        except Exception as e:
            log.warning("config not reloaded: %s", e)
            self.notifier.send("อ่าน config ไม่ได้", f"ใช้ค่าเดิมต่อไปก่อน ({e})")
            return False
        camera_changed = new.camera != self.cfg.camera
        self.cfg = new
        self.zones = calibration.load_zones(new.zones)
        self.rules.rules = dict(new.rules)
        self.rules.alerts = new.alerts
        self.rules.reset()
        self.smoother = Smoother(new.camera.smoothing_s)
        self.notifier.enabled = new.alerts.notifications
        self._apply_sitting_config()
        log.info("config reloaded")
        return camera_changed

    def _apply_sitting_config(self) -> None:
        s = self.cfg.sitting
        self.sitting.break_after_s = s.break_after_min * 60
        self.sitting.repeat_s = s.repeat_min * 60
        self.sitting.away_s = s.away_s

    # ------------------------------------------------------------------ status

    def _set_status(self, text: str, icon_state: str) -> None:
        self._status = text
        self.tray.set_state(icon_state)

    def _paused_text(self) -> str:
        if self._pause_until is None:
            return "หยุดชั่วคราว (กล้องปิด)"
        left = max(0, round((self._pause_until - time.monotonic()) / 60))
        return f"หยุดชั่วคราว อีก {left} นาที (กล้องปิด)"

    def _live_text(self, now: float, m: PostureMetrics) -> str:
        if self._cal is not None:
            return "กำลัง Calibrate..."
        if not self.zones:
            return "ยังไม่ได้ Calibrate"
        minutes = int(self.sitting.sitting_s(now) // 60)
        if not m.present:
            return "ไม่เห็นใครหน้าจอ"
        text = f"นั่งมาแล้ว {minutes} นาที"
        if self.sitting.snoozed(now):
            text += " (เลื่อนเตือนลุกอยู่)"
        return text

    def _debug_lines(self, ev: Evaluation) -> list[str]:
        lines = [f"zone {ev.zone or '-'}   status {ev.status.name}"]
        bad = [f"{r}:{ev.states[r].name}" for r in RULE_ORDER if ev.states.get(r, State.OK)]
        if bad:
            lines.append(" ".join(bad))
        if self._cal is not None:
            now = time.monotonic()
            if now < self._cal.start_at:
                lines.append(f"calibrate {self._cal.zone} in {self._cal.start_at - now:.0f}s")
            else:
                lines.append(f"calibrating {self._cal.zone}... hold still")
        return lines
