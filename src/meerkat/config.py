"""Load/save ``config.toml`` with defaults from PLAN.md sections 8-9.

The config file lives in the user's config folder (not the repo). Unknown keys are
ignored and missing keys fall back to defaults, so old files keep working.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

import tomli_w

APP_NAME = "meerkat"


def user_config_dir() -> Path:
    override = os.environ.get("MEERKAT_HOME")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME


def default_config_path() -> Path:
    return user_config_dir() / "config.toml"


@dataclass
class CameraConfig:
    index: int = 0
    fps: float = 5.0
    smoothing_s: float = 1.5
    # Frames darker than this mean gray level (0-255) are skipped, not judged.
    min_brightness: float = 40.0
    # MediaPipe detection/presence confidence; higher = fewer shaky detections.
    min_confidence: float = 0.6


@dataclass
class StorageConfig:
    enabled: bool = True  # numbers only: metrics summaries + events in SQLite
    sample_period_s: float = 10.0
    record_sessions: bool = False  # per-frame metrics to CSV for replay (no images)


@dataclass
class AlertConfig:
    rule_cooldown_s: float = 300.0  # same rule won't alert again within 5 min
    global_cooldown_s: float = 60.0  # min gap between any two alerts
    recover_s: float = 3.0  # good posture this long to clear an ALERT
    hysteresis: float = 0.8  # must drop below 80% of the threshold to count as good
    # Face lost but shoulders still visible (head bowed / turned away): keep judging with
    # the last head angles for up to this long before treating it as unknown.
    face_lost_hold_s: float = 120.0
    notifications: bool = True
    sound_posture: bool = True  # play the system notification sound for posture alerts
    sound_break: bool = True  # ... and for stand-up reminders
    sound_style: str = "meerkat"  # "meerkat" (own chirps) or "system" (OS default sound)
    sticky: bool = True  # alerts stay on screen until you close them (Windows)


@dataclass
class SittingConfig:
    break_after_min: float = 30.0
    repeat_min: float = 15.0
    away_s: float = 60.0
    snooze_min: float = 10.0


@dataclass
class RuleConfig:
    threshold: float
    hold_s: float
    enabled: bool = True


def default_rules() -> dict[str, RuleConfig]:
    # Thresholds use the units in PLAN.md section 8:
    # degrees for angles, ratio vs baseline for lean_in / twist / slouch.
    return {
        "head_down": RuleConfig(15.0, 30.0),
        "head_up": RuleConfig(10.0, 30.0),
        "yaw_out": RuleConfig(15.0, 20.0),
        "roll": RuleConfig(10.0, 30.0),
        "lean_in": RuleConfig(1.15, 45.0),
        "shoulder_tilt": RuleConfig(7.0, 60.0),
        "twist": RuleConfig(0.85, 60.0),
        "slouch": RuleConfig(0.85, 60.0),
    }


@dataclass
class Config:
    camera: CameraConfig = field(default_factory=CameraConfig)
    alerts: AlertConfig = field(default_factory=AlertConfig)
    sitting: SittingConfig = field(default_factory=SittingConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    rules: dict[str, RuleConfig] = field(default_factory=default_rules)
    # Calibrated baselines: zone name -> metric name -> value.
    zones: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Config:
        cfg = cls()
        _merge(cfg.camera, data.get("camera", {}))
        _merge(cfg.alerts, data.get("alerts", {}))
        _merge(cfg.sitting, data.get("sitting", {}))
        _merge(cfg.storage, data.get("storage", {}))
        for name, values in data.get("rules", {}).items():
            if name in cfg.rules and isinstance(values, dict):
                _merge(cfg.rules[name], values)
        for zone, values in data.get("zones", {}).items():
            if isinstance(values, dict):
                cfg.zones[str(zone)] = {
                    k: float(v) for k, v in values.items() if isinstance(v, int | float)
                }
        return cfg


def _merge(target: object, values: dict) -> None:
    if not isinstance(values, dict):
        return
    for key, value in values.items():
        if not hasattr(target, key):
            continue
        current = getattr(target, key)
        try:
            if isinstance(current, bool):
                value = bool(value)
            elif isinstance(current, int):
                value = int(value)
            elif isinstance(current, float):
                value = float(value)
        except (TypeError, ValueError):
            continue
        setattr(target, key, value)


def load(path: Path | None = None) -> Config:
    path = path or default_config_path()
    if not path.exists():
        return Config()
    # utf-8-sig: tolerate the BOM some Windows editors add.
    return Config.from_dict(tomllib.loads(path.read_text(encoding="utf-8-sig")))


def save(cfg: Config, path: Path | None = None) -> Path:
    path = path or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as f:
        tomli_w.dump(cfg.to_dict(), f)
    tmp.replace(path)
    return path
