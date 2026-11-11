"""Wires everything together (PLAN.md section 5).

Threads:
    main     - tray icon (pystray needs the main thread on macOS)
    worker   - camera -> detector -> metrics -> rules / sitting -> notifier, storage, tray
    notifier - delivers desktop notifications

Tray callbacks never touch the camera or the database. They queue commands for the worker.
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

import numpy as np

from meerkat import autostart, calibration, config, notifier, storage
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
STATS_REFRESH_S = 30.0
CAMERA_RETRY_S = 10.0

# Hourly zone check (PLAN.md section 8): side zone > 60% of the last hour -> suggest moving.
ZONE_CHECK_EVERY_S = 600.0
ZONE_WINDOW_S = 3600.0
ZONE_MIN_PRESENT_S = 1800.0
ZONE_SIDE_SHARE = 0.6

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
        a = self.cfg.alerts
        self.notifier = Notifier(
            a.notifications, a.sound_posture, a.sound_break, a.sound_style, a.sticky
        )

        self.paused = False
        self.debug_enabled = False
        self.recording = False
        self._pause_until: float | None = None
        self._phone_until: float | None = None
        self._cal: _Calibration | None = None
        self._status = "กำลังเปิดกล้อง..."
        self._stats_lines: list[str] = ["ยังไม่มีข้อมูล"]
        self._cmds: queue.Queue[tuple] = queue.Queue()
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._run_worker, name="worker", daemon=True)
        self.tray = Tray(self)

    # ---------------------------------------------------------------- lifecycle

    def run(self) -> int:
        self._install_ctrl_c_handler()
        try:
            self.tray.run(setup=self._worker.start)
        finally:
            self._stop.set()
            if self._worker.is_alive():
                self._worker.join(timeout=5)
            self.notifier.close()
        return 0

    def _install_ctrl_c_handler(self) -> None:
        """Make Ctrl+C in the terminal quit cleanly.

        The tray loop blocks the main thread inside a native call, so Python's own
        SIGINT handling never gets a chance to run. On Windows we register a console
        control handler, which Windows calls on its own thread.
        """
        if sys.platform != "win32":
            import signal

            signal.signal(signal.SIGINT, lambda *_: self.quit())
            return

        import ctypes

        CTRL_CLOSE_EVENT = 2

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)
        def handler(event: int) -> bool:
            log.info("console event %d: quitting", event)
            self.quit()
            if event == CTRL_CLOSE_EVENT:
                # Terminal window closing: give the worker a moment to release the camera.
                self._worker.join(timeout=3)
            return True

        self._console_handler = handler  # keep a reference so it isn't garbage collected
        if not ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True):
            log.warning("could not install Ctrl+C handler")

    # ------------------------------------------------- tray Controller interface

    @property
    def camera_index(self) -> int:
        return self.cfg.camera.index

    def status_text(self) -> str:
        return self._status

    def stats_lines(self) -> list[str]:
        return list(self._stats_lines)

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

    def select_camera(self, index: int) -> None:
        self._cmds.put(("camera", index))

    def toggle_recording(self) -> None:
        self._cmds.put(("recording",))

    @property
    def break_after_min(self) -> float:
        return self.cfg.sitting.break_after_min

    def break_after_options(self) -> list[int]:
        return list(self.cfg.sitting.break_after_options_min)

    def set_break_after(self, minutes: int) -> None:
        self._cmds.put(("break_after", minutes))

    @property
    def phone_break_active(self) -> bool:
        return self._phone_until is not None

    def phone_break_options(self) -> list[int]:
        return list(self.cfg.alerts.phone_break_options_min)

    def start_phone_break(self, minutes: int) -> None:
        self._cmds.put(("phone_break", minutes))

    def end_phone_break(self) -> None:
        self._cmds.put(("phone_break_end",))

    def toggle_debug(self) -> None:
        self.debug_enabled = not self.debug_enabled

    @property
    def autostart_supported(self) -> bool:
        return autostart.supported()

    @property
    def autostart_enabled(self) -> bool:
        return autostart.is_enabled()

    def toggle_autostart(self) -> None:
        on = autostart.set_enabled(not autostart.is_enabled())
        self.notifier.send(
            "เปิดอัตโนมัติแล้ว" if on else "ปิดการเปิดอัตโนมัติแล้ว",
            "Meerkat จะเปิดเองทุกครั้งที่เข้า Windows" if on else "ต้องเปิด Meerkat เองเมื่อต้องการใช้",
        )
        self.tray.refresh()

    def open_data_folder(self) -> None:
        self._open_path(config.user_config_dir())

    def open_config(self) -> None:
        path = self.config_path
        if not path.exists():
            config.save(self.cfg, path)
        self._open_path(path)

    @staticmethod
    def _open_path(path: Path) -> None:
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
            detector = Detector(min_confidence=self.cfg.camera.min_confidence)
        except Exception as e:
            log.exception("cannot load models")
            self.notifier.send("Meerkat เปิดไม่ได้", str(e))
            self.quit()
            return

        self.db: storage.Storage | None = None
        if self.cfg.storage.enabled:
            try:
                self.db = storage.Storage()
            except Exception:
                log.exception("storage disabled: cannot open database")
        self.aggregator = storage.Aggregator(self.cfg.storage.sample_period_s)
        self.recorder: storage.SessionRecorder | None = None
        if self.cfg.storage.record_sessions:
            self._start_recording()
        self._last_zone_tip = -float("inf")

        self.cam: Camera | None = None
        window = DebugWindow()
        self._next_camera_try = 0.0
        next_config_check = time.monotonic() + CONFIG_CHECK_S
        next_menu_refresh = 0.0
        next_stats = 0.0
        next_zone_check = time.monotonic() + ZONE_CHECK_EVERY_S
        bad_reads = 0

        self._restore_sitting()
        if calibration.MAIN not in self.zones:
            self._start_calibration(calibration.MAIN, time.monotonic(), first_run=True)

        try:
            while not self._stop.is_set():
                now = time.monotonic()
                self._handle_commands(now)

                if now >= next_config_check:
                    next_config_check = now + CONFIG_CHECK_S
                    if self._reload_config_if_changed():
                        self._close_camera()  # pick up camera index / fps changes

                if now >= next_stats:
                    next_stats = now + STATS_REFRESH_S
                    self._refresh_stats()

                if now >= next_zone_check:
                    next_zone_check = now + ZONE_CHECK_EVERY_S
                    self._check_zone_usage(now)

                if now >= next_menu_refresh:
                    next_menu_refresh = now + MENU_REFRESH_S
                    self.tray.refresh()

                if self._pause_until is not None and now >= self._pause_until:
                    self._resume()

                if self._phone_until is not None and now >= self._phone_until:
                    self._finish_phone_break(timed_out=True)

                if self.paused or not self.debug_enabled:
                    window.close()

                if self.paused:
                    self._close_camera()  # really turn the camera off
                    self._set_status(self._paused_text(), "sleep")
                    self._stop.wait(0.5)
                    continue

                if self.cam is None and not self._open_camera(now):
                    self._stop.wait(0.5)
                    continue

                frame = self.cam.read()
                if frame is None:
                    bad_reads += 1
                    if bad_reads >= 10:
                        self._close_camera()
                        self._next_camera_try = time.monotonic() + CAMERA_RETRY_S
                    continue
                bad_reads = 0

                now = time.monotonic()
                too_dark = float(np.mean(frame)) < self.cfg.camera.min_brightness
                lm = detector.detect(frame, int(now * 1000))
                raw = compute_metrics(lm)
                m = self.smoother.update(now, raw)
                if too_dark:
                    # Can't judge posture reliably: don't alert, don't count as absent.
                    ev = Evaluation(State.OK)
                    self._set_status("แสงน้อยเกินไป มองไม่ชัด", "green")
                else:
                    ev = self._evaluate(now, raw, m)

                if self.debug_enabled:
                    extra = self._debug_lines(ev) + (["too dark: skipped"] if too_dark else [])
                    if not window.show(frame, lm, m, extra):
                        self.debug_enabled = False
                del frame, lm  # frames are never kept
        except Exception:
            log.exception("worker crashed")
            self.notifier.send("Meerkat หยุดทำงาน", "เกิดข้อผิดพลาด ดูรายละเอียดใน terminal")
            self.quit()
        finally:
            window.close()
            self._close_camera()
            detector.close()
            self._stop_recording()
            if self.db is not None:
                if (last := self.aggregator.flush(time.time())) is not None:
                    self.db.add_sample(last)
                self.db.close()

    def _restore_sitting(self) -> None:
        """After a quick restart, keep counting the sitting time from before."""
        if self.db is None:
            return
        try:
            wall = time.time()
            start = self.db.current_session_start(wall, self.cfg.sitting.away_s)
        except Exception:
            log.exception("cannot restore sitting time")
            return
        if start is not None:
            self.sitting.restore(time.monotonic(), wall - start)
            log.info("continuing sitting session: %.0f min so far", (wall - start) / 60)

    def _open_camera(self, now: float) -> bool:
        if now < self._next_camera_try:
            return False
        cam = Camera(self.cfg.camera.index, self.cfg.camera.fps)
        try:
            cam.open()
        except CameraError:
            log.warning("camera %d not available", self.cfg.camera.index)
            self._set_status(f"เปิดกล้อง {self.cfg.camera.index} ไม่ได้ จะลองใหม่", "sleep")
            self._next_camera_try = now + CAMERA_RETRY_S
            return False
        self.cam = cam
        return True

    def _close_camera(self) -> None:
        if self.cam is not None:
            self.cam.release()
            self.cam = None
            self.smoother.reset()

    def _evaluate(self, now: float, raw: PostureMetrics, m: PostureMetrics) -> Evaluation:
        if self.recorder is not None:
            self.recorder.write(now, raw)

        if self._cal is not None:
            self._calibration_step(now, raw)
            ev = Evaluation(State.OK)
        else:
            ev = self.rules.update(now, m, self.zones)
            for rule in ev.alerts:
                self.notifier.alert(rule)
                self._event("alert", rule)

        was_sitting = self.sitting.active
        if self.sitting.update(now, m.person_present):
            self.notifier.break_reminder(int(self.sitting.sitting_s(now) // 60))
            self._event("break_reminder")
        if was_sitting and not self.sitting.active:
            self._event("stood_up")

        summary = self.aggregator.add(time.time(), m, ev.zone, ev.status)
        if summary is not None and self.db is not None:
            self.db.add_sample(summary)

        self._set_status(self._live_text(now, m), _ICON_FOR_STATE[ev.status])
        return ev

    def _event(self, kind: str, detail: str | None = None) -> None:
        if self.db is not None:
            self.db.add_event(kind, detail)

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
                self._phone_until = None
                self.rules.unmute()
                self.rules.reset()
                self.sitting.reset()
                self.smoother.reset()
                self._event("pause", None if minutes is None else f"{minutes:g}")
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
            elif cmd == "camera":
                (index,) = args
                if index != self.cfg.camera.index:
                    self.cfg.camera.index = index
                    self._save_config()
                    self._close_camera()
                    self._next_camera_try = 0.0
                    self.notifier.send(
                        "เปลี่ยนกล้องแล้ว",
                        f"ใช้กล้อง {index} ถ้าตำแหน่งกล้องเปลี่ยน ควร Calibrate ใหม่",
                    )
                    self.tray.refresh()
            elif cmd == "recording":
                if self.recorder is None:
                    self._start_recording()
                else:
                    self._stop_recording()
                self.tray.refresh()
            elif cmd == "phone_break":
                (minutes,) = args
                self._phone_until = now + minutes * 60
                self.rules.mute(self._phone_until)
                self._event("phone_break", str(minutes))
                self.notifier.send(*notifier.phone_break_started(minutes))
                self.tray.refresh()
            elif cmd == "phone_break_end":
                self._finish_phone_break(timed_out=False)
            elif cmd == "break_after":
                (minutes,) = args
                if minutes != self.cfg.sitting.break_after_min:
                    self.cfg.sitting.break_after_min = float(minutes)
                    self._save_config()
                    self._apply_sitting_config()
                    self.notifier.send(
                        f"เตือนลุกทุก {minutes} นาที",
                        f"Meerkat จะเตือนให้ลุกเมื่อนั่งต่อเนื่องครบ {minutes} นาที",
                    )
                    self.tray.refresh()

    def _finish_phone_break(self, timed_out: bool) -> None:
        if self._phone_until is None:
            return
        self._phone_until = None
        self.rules.unmute()
        self._event("phone_break_end", "timeout" if timed_out else "manual")
        if timed_out:
            self.notifier.send(*notifier.phone_break_over(), sound=notifier.POSTURE)
        self.tray.refresh()

    def _resume(self) -> None:
        if self.paused:
            self._event("resume")
        self.paused = False
        self._pause_until = None
        self.tray.refresh()

    # ---------------------------------------------------------------- recording

    def _start_recording(self) -> None:
        try:
            self.recorder = storage.SessionRecorder()
        except OSError:
            log.exception("cannot start session recording")
            return
        self.recording = True
        log.info("recording metrics to %s", self.recorder.path)
        self.notifier.send("เริ่มบันทึก session", f"เก็บเฉพาะตัวเลข ไม่มีภาพ\n{self.recorder.path}")

    def _stop_recording(self) -> None:
        self.recording = False
        if getattr(self, "recorder", None) is not None:
            self.recorder.close()
            log.info("recording saved: %s", self.recorder.path)
            self.recorder = None

    # ------------------------------------------------------------ stats/zones

    def _refresh_stats(self) -> None:
        if self.db is None:
            self._stats_lines = ["ปิดการเก็บข้อมูลไว้ใน config"]
            return
        try:
            self._stats_lines = storage.format_stats(self.db.day_stats(*storage.day_bounds()))
        except Exception:
            log.exception("cannot compute stats")

    def _check_zone_usage(self, now: float) -> None:
        if self.db is None or now - self._last_zone_tip < ZONE_WINDOW_S:
            return
        end = time.time()
        start = end - ZONE_WINDOW_S
        if self.db.present_seconds(start, end) < ZONE_MIN_PRESENT_S:
            return
        share = self.db.zone_share(start, end)
        side = {z: s for z, s in share.items() if z != calibration.MAIN}
        if not side:
            return
        zone, frac = max(side.items(), key=lambda kv: kv[1])
        if frac <= ZONE_SIDE_SHARE:
            return
        self._last_zone_tip = now
        label = calibration.ZONE_LABELS.get(zone, zone)
        self.notifier.send(
            f"ชั่วโมงที่ผ่านมามอง{label} {frac:.0%}",
            f"ใช้{label}มากกว่าจอหลัก ลองย้าย{label}มาไว้ตรงหน้า แล้ว Calibrate ใหม่",
        )
        self._event("zone_tip", zone)

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
        self._event("calibrate", cal.zone)
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
        record_changed = new.storage.record_sessions != self.cfg.storage.record_sessions
        self.cfg = new
        if record_changed:
            if new.storage.record_sessions and self.recorder is None:
                self._start_recording()
            elif not new.storage.record_sessions and self.recorder is not None:
                self._stop_recording()
        self.zones = calibration.load_zones(new.zones)
        self.rules.rules = dict(new.rules)
        self.rules.alerts = new.alerts
        self.rules.reset()
        self.smoother = Smoother(new.camera.smoothing_s)
        self.notifier.enabled = new.alerts.notifications
        self.notifier.sound_posture = new.alerts.sound_posture
        self.notifier.sound_break = new.alerts.sound_break
        self.notifier.sound_style = new.alerts.sound_style
        self.notifier.sticky = new.alerts.sticky
        self.aggregator.period_s = new.storage.sample_period_s
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
        if not m.person_present:
            return "ไม่เห็นใครหน้าจอ"
        text = f"นั่งมาแล้ว {minutes} นาที"
        if self._phone_until is not None:
            left = max(1, round((self._phone_until - now) / 60))
            text += f" (พักเล่นโทรศัพท์ อีก {left} นาที)"
        if self.sitting.snoozed(now):
            text += " (เลื่อนเตือนลุกอยู่)"
        return text

    def _debug_lines(self, ev: Evaluation) -> list[str]:
        lines = [f"zone {ev.zone or '-'}   status {ev.status.name}"]
        bad = [f"{r}:{ev.states[r].name}" for r in RULE_ORDER if ev.states.get(r, State.OK)]
        if bad:
            lines.append(" ".join(bad))
        if self.recording:
            lines.append("REC metrics (numbers only)")
        if self._cal is not None:
            now = time.monotonic()
            if now < self._cal.start_at:
                lines.append(f"calibrate {self._cal.zone} in {self._cal.start_at - now:.0f}s")
            else:
                lines.append(f"calibrating {self._cal.zone}... hold still")
        return lines
