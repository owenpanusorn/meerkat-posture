"""Posture rules: metrics + time -> status + alert events (PLAN.md section 8). Pure.

Each rule turns the metrics into a *severity*: 0 = same as baseline, 1 = exactly at
the threshold. Per rule state machine:

    OK --(severity > 1)--> WARN --(held hold_s)--> ALERT
    WARN --(severity < hysteresis)--> OK
    ALERT --(severity < hysteresis for recover_s)--> OK

An ALERT sends one notification per episode, subject to the per-rule and global cooldowns.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import IntEnum

from meerkat.calibration import nearest_zone
from meerkat.config import AlertConfig, RuleConfig
from meerkat.metrics import PostureMetrics

RULE_ORDER = (
    "head_down",
    "head_up",
    "yaw_out",
    "roll",
    "lean_in",
    "shoulder_tilt",
    "twist",
    "slouch",
)


class State(IntEnum):
    OK = 0
    WARN = 1
    ALERT = 2


def _diff(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def _ratio(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None or b == 0 else a / b


def severity(rule: str, m: PostureMetrics, base: PostureMetrics, threshold: float) -> float | None:
    """How far past baseline, as a fraction of the threshold. None if unmeasurable."""
    match rule:
        case "head_down":  # pitch is negative when looking down
            d = _diff(m.head_pitch, base.head_pitch)
            return None if d is None else -d / threshold
        case "head_up":
            d = _diff(m.head_pitch, base.head_pitch)
            return None if d is None else d / threshold
        case "yaw_out":
            d = _diff(m.head_yaw, base.head_yaw)
            return None if d is None else abs(d) / threshold
        case "roll":
            d = _diff(m.head_roll, base.head_roll)
            return None if d is None else abs(d) / threshold
        case "shoulder_tilt":
            d = _diff(m.shoulder_tilt, base.shoulder_tilt)
            return None if d is None else abs(d) / threshold
        case "lean_in":  # face grows: ratio above threshold (e.g. 1.15)
            r = _ratio(m.face_scale, base.face_scale)
            return None if r is None else (r - 1.0) / (threshold - 1.0)
        case "twist":  # shoulders look narrower: ratio below threshold (e.g. 0.85)
            r = _ratio(m.shoulder_width, base.shoulder_width)
            return None if r is None else (1.0 - r) / (1.0 - threshold)
        case "slouch":  # ear drops toward shoulders
            r = _ratio(m.neck_drop, base.neck_drop)
            return None if r is None else (1.0 - r) / (1.0 - threshold)
    raise ValueError(f"unknown rule {rule!r}")


@dataclass
class _Track:
    state: State = State.OK
    warn_since: float = 0.0
    good_since: float | None = None
    notified: bool = False
    last_notified: float = -math.inf


@dataclass(frozen=True)
class Evaluation:
    status: State
    zone: str | None = None
    states: dict[str, State] = field(default_factory=dict)
    alerts: tuple[str, ...] = ()


class RulesEngine:
    def __init__(self, rules: Mapping[str, RuleConfig], alerts: AlertConfig) -> None:
        self.rules = dict(rules)
        self.alerts = alerts
        self._tracks = {name: _Track() for name in RULE_ORDER}
        self._last_global = -math.inf

    def reset(self) -> None:
        """Forget current episodes (keeps cooldown history)."""
        for tr in self._tracks.values():
            tr.state, tr.good_since, tr.notified = State.OK, None, False

    def update(
        self, t: float, m: PostureMetrics, zones: Mapping[str, PostureMetrics]
    ) -> Evaluation:
        if not m.present or not zones:
            self.reset()
            return Evaluation(State.OK)

        zone = nearest_zone(m, zones) or next(iter(zones))
        base = zones[zone]
        hyst = self.alerts.hysteresis
        alerts: list[str] = []

        for name in RULE_ORDER:
            cfg = self.rules.get(name)
            tr = self._tracks[name]
            if cfg is None or not cfg.enabled:
                tr.state = State.OK
                continue
            sev = severity(name, m, base, cfg.threshold)
            if sev is None:
                # Low-confidence / missing value: never count it as bad posture.
                if tr.state == State.WARN:
                    tr.state = State.OK
                continue

            if tr.state == State.OK and sev > 1.0:
                tr.state, tr.warn_since = State.WARN, t
            elif tr.state == State.WARN:
                if sev < hyst:
                    tr.state = State.OK
                elif t - tr.warn_since >= cfg.hold_s:
                    tr.state, tr.good_since, tr.notified = State.ALERT, None, False

            if tr.state == State.ALERT:
                if sev < hyst:
                    if tr.good_since is None:
                        tr.good_since = t
                    if t - tr.good_since >= self.alerts.recover_s:
                        tr.state, tr.good_since = State.OK, None
                        continue
                else:
                    tr.good_since = None
                if (
                    not tr.notified
                    and t - tr.last_notified >= self.alerts.rule_cooldown_s
                    and t - self._last_global >= self.alerts.global_cooldown_s
                ):
                    tr.notified, tr.last_notified, self._last_global = True, t, t
                    alerts.append(name)

        states = {name: tr.state for name, tr in self._tracks.items()}
        status = max(states.values(), default=State.OK)
        return Evaluation(status, zone, states, tuple(alerts))
