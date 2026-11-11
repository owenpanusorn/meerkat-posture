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
from dataclasses import dataclass, field, replace
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


# Reported instead of "head_down" when the head-down episode looks like phone use.
PHONE = "phone"


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
        self._last_face: PostureMetrics | None = None
        self._last_face_t = -math.inf
        self._phone_episode = False
        self.muted_until = -math.inf

    def reset(self) -> None:
        """Forget current episodes (keeps cooldown history)."""
        for tr in self._tracks.values():
            tr.state, tr.good_since, tr.notified = State.OK, None, False
        self._last_face = None
        self._phone_episode = False

    def mute(self, until: float) -> None:
        """No posture judgement before ``until`` (e.g. a phone break the user asked for)."""
        self.muted_until = until
        self.reset()

    def unmute(self) -> None:
        self.muted_until = -math.inf

    def update(
        self, t: float, m: PostureMetrics, zones: Mapping[str, PostureMetrics]
    ) -> Evaluation:
        if not zones:
            self.reset()
            return Evaluation(State.OK)
        if t < self.muted_until:
            self.reset()
            return Evaluation(State.OK, nearest_zone(m, zones))
        face_hidden = False
        if m.present:
            self._last_face, self._last_face_t = m, t
        elif (
            m.body_visible
            and self._last_face is not None
            and t - self._last_face_t <= self.alerts.face_lost_hold_s
        ):
            # Face hidden but the person is still here, usually because the head is bowed
            # too far for face tracking. Keep judging with the last head angles seen.
            m = replace(
                self._last_face,
                shoulder_tilt=m.shoulder_tilt,
                shoulder_width=m.shoulder_width,
                neck_drop=m.neck_drop,
            )
            face_hidden = True
        else:
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
                    if name == "head_down" and self._phone_episode:
                        alerts.append(PHONE)
                    else:
                        alerts.append(name)

        self._update_phone_episode(m, base, face_hidden)
        states = {name: tr.state for name, tr in self._tracks.items()}
        status = max(states.values(), default=State.OK)
        return Evaluation(status, zone, states, tuple(alerts))

    def _update_phone_episode(
        self, m: PostureMetrics, base: PostureMetrics, face_hidden: bool
    ) -> None:
        """A head-down episode looks like phone use if the head went very low or so far
        down that the face disappeared. Then the head_down alert is reported as ``phone``.
        Note: no object detection; this is a posture heuristic."""
        if self._tracks["head_down"].state == State.OK:
            self._phone_episode = False
            return
        d = _diff(m.head_pitch, base.head_pitch)
        if face_hidden or (d is not None and -d >= self.alerts.phone_pitch_deg):
            self._phone_episode = True
