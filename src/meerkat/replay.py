"""Re-run smoothing + rules + sitting timer on a recorded session (no camera, no images).

    uv run python -m meerkat --replay path/to/session.csv [--config other.toml]

Use it to see how a change to the thresholds in config.toml would have behaved.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from meerkat import calibration
from meerkat.config import Config
from meerkat.metrics import PostureMetrics, Smoother
from meerkat.rules import RulesEngine
from meerkat.sitting import SittingTimer


@dataclass(frozen=True)
class ReplayEvent:
    t: float
    kind: str  # alert | break_reminder | stood_up
    detail: str | None = None


def replay(
    samples: Iterable[tuple[float, PostureMetrics]],
    cfg: Config,
    zones: Mapping[str, PostureMetrics] | None = None,
) -> list[ReplayEvent]:
    zones = calibration.load_zones(cfg.zones) if zones is None else zones
    smoother = Smoother(cfg.camera.smoothing_s)
    rules = RulesEngine(cfg.rules, cfg.alerts)
    s = cfg.sitting
    sitting = SittingTimer(s.break_after_min * 60, s.repeat_min * 60, s.away_s)

    events: list[ReplayEvent] = []
    for t, raw in samples:
        m = smoother.update(t, raw)
        ev = rules.update(t, m, zones)
        events += [ReplayEvent(t, "alert", rule) for rule in ev.alerts]
        was_active = sitting.active
        if sitting.update(t, m.present):
            events.append(ReplayEvent(t, "break_reminder"))
        if was_active and not sitting.active:
            events.append(ReplayEvent(t, "stood_up"))
    return events


def report(events: list[ReplayEvent]) -> str:
    lines = []
    for e in events:
        mm, ss = divmod(int(e.t), 60)
        hh, mm = divmod(mm, 60)
        lines.append(f"{hh:02d}:{mm:02d}:{ss:02d}  {e.kind}{f'  {e.detail}' if e.detail else ''}")
    counts = Counter(e.detail or e.kind for e in events)
    lines.append("")
    lines.append("total: " + (", ".join(f"{k}={v}" for k, v in counts.most_common()) or "none"))
    return "\n".join(lines)
