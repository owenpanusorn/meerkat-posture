"""Calibrated baselines for multiple zones (PLAN.md section 7). Pure functions.

A baseline is just a ``PostureMetrics`` averaged over a few seconds of good posture.
Zones are stored in the config as ``{zone: {metric: value}}``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict

from meerkat.metrics import PostureMetrics

MAIN = "main"
SECOND = "second"
ZONE_LABELS = {MAIN: "จอหลัก", SECOND: "จอที่สอง"}

CAPTURE_S = 3.0
MIN_PRESENT_FRACTION = 0.5


def average(samples: Iterable[PostureMetrics]) -> PostureMetrics | None:
    """Average the present samples field by field. None if nothing usable."""
    present = [s for s in samples if s.present]
    if not present:
        return None
    out: dict[str, float | None] = {}
    for name in asdict(present[0]):
        if name == "present":
            continue
        vals = [getattr(s, name) for s in present if getattr(s, name) is not None]
        out[name] = sum(vals) / len(vals) if vals else None
    if out.get("head_yaw") is None or out.get("head_pitch") is None:
        return None
    return PostureMetrics(present=True, **out)


def capture_ok(samples: list[PostureMetrics]) -> bool:
    if not samples:
        return False
    present = sum(1 for s in samples if s.present)
    return present >= 3 and present / len(samples) >= MIN_PRESENT_FRACTION


def to_config(baseline: PostureMetrics) -> dict[str, float]:
    return {k: v for k, v in asdict(baseline).items() if k != "present" and v is not None}


def from_config(values: Mapping[str, float]) -> PostureMetrics:
    known = set(asdict(PostureMetrics(present=True))) - {"present"}
    return PostureMetrics(present=True, **{k: float(v) for k, v in values.items() if k in known})


def load_zones(zones: Mapping[str, Mapping[str, float]]) -> dict[str, PostureMetrics]:
    return {name: from_config(values) for name, values in zones.items()}


def nearest_zone(m: PostureMetrics, zones: Mapping[str, PostureMetrics]) -> str | None:
    """Zone whose head yaw/pitch is closest to the current head direction."""
    if m.head_yaw is None or m.head_pitch is None:
        return None
    best, best_d = None, math.inf
    for name, base in zones.items():
        if base.head_yaw is None or base.head_pitch is None:
            continue
        d = math.hypot(m.head_yaw - base.head_yaw, m.head_pitch - base.head_pitch)
        if d < best_d:
            best, best_d = name, d
    return best
