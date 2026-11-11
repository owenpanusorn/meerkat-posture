"""SQLite storage of numbers only: metric summaries + events (PLAN.md section 2, rule 4).

Also the optional per-frame session recorder (CSV of metrics, never images) used by
``replay.py`` to re-run the rules offline while tuning thresholds.

All times stored here are wall-clock Unix seconds.
"""

from __future__ import annotations

import csv
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta
from pathlib import Path

from meerkat.config import user_config_dir
from meerkat.metrics import PostureMetrics

METRIC_FIELDS = [f.name for f in fields(PostureMetrics) if f.name != "present"]

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS samples (
    ts REAL NOT NULL,
    duration_s REAL NOT NULL,
    present_frac REAL NOT NULL,
    zone TEXT,
    status INTEGER NOT NULL,
    {", ".join(f"{name} REAL" for name in METRIC_FIELDS)}
);
CREATE INDEX IF NOT EXISTS samples_ts ON samples(ts);
CREATE TABLE IF NOT EXISTS events (
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
"""


def default_db_path() -> Path:
    return user_config_dir() / "meerkat.sqlite"


def sessions_dir() -> Path:
    return user_config_dir() / "sessions"


# ------------------------------------------------------------------ aggregation


@dataclass(frozen=True)
class Summary:
    ts: float
    duration_s: float
    present_frac: float
    zone: str | None
    status: int
    metrics: PostureMetrics


class Aggregator:
    """Collapse per-frame values into one summary row every ``period_s`` seconds."""

    # A gap longer than this (pause, camera trouble) is not counted as tracked time.
    MAX_GAP_S = 2.0

    def __init__(self, period_s: float = 10.0) -> None:
        self.period_s = period_s
        self._rows: list[tuple[PostureMetrics, str | None, int]] = []
        self._start: float | None = None
        self._last: float = 0.0

    def add(self, t: float, m: PostureMetrics, zone: str | None, status: int) -> Summary | None:
        """Windows are contiguous: a sample at/after the period end closes the window."""
        summary = None
        if self._start is not None and (
            t - self._start >= self.period_s or t - self._last > self.MAX_GAP_S
        ):
            summary = self.flush(t)
        if self._start is None:
            self._start = t
        self._rows.append((m, zone, int(status)))
        self._last = t
        return summary

    def flush(self, t: float) -> Summary | None:
        """Close the current window at time ``t`` (capped at MAX_GAP_S after the last sample)."""
        if self._start is None or not self._rows:
            return None
        rows, start = self._rows, self._start
        self._rows, self._start = [], None
        t = min(t, self._last + self.MAX_GAP_S)

        present = [m for m, _, _ in rows if m.present]
        avg: dict[str, float | None] = {}
        for name in METRIC_FIELDS:
            vals = [getattr(m, name) for m in present if getattr(m, name) is not None]
            avg[name] = sum(vals) / len(vals) if vals else None
        zones = Counter(z for m, z, _ in rows if m.present and z is not None)
        return Summary(
            ts=start,
            duration_s=max(t - start, 0.0),
            present_frac=len(present) / len(rows),
            zone=zones.most_common(1)[0][0] if zones else None,
            status=max(s for _, _, s in rows),
            metrics=PostureMetrics(present=bool(present), **avg),
        )


# ---------------------------------------------------------------------- stats


@dataclass(frozen=True)
class DayStats:
    sitting_s: float = 0.0
    stand_ups: int = 0
    break_reminders: int = 0
    alerts: dict[str, int] = field(default_factory=dict)
    zone_share: dict[str, float] = field(default_factory=dict)


RULE_LABELS = {
    "head_down": "ก้ม",
    "head_up": "เงย",
    "yaw_out": "หันนอกโซน",
    "roll": "เอียงคอ",
    "lean_in": "โน้มเข้าจอ",
    "shoulder_tilt": "ไหล่เอียง",
    "twist": "ตัวบิด",
    "slouch": "ค่อม",
}
ZONE_LABELS = {"main": "จอหลัก", "second": "จอที่สอง"}


def format_stats(s: DayStats) -> list[str]:
    h, m = divmod(int(s.sitting_s // 60), 60)
    lines = [f"นั่งรวม {h} ชม. {m} นาที" if h else f"นั่งรวม {m} นาที"]
    lines.append(f"ลุก {s.stand_ups} ครั้ง, เตือนลุก {s.break_reminders} ครั้ง")
    total = sum(s.alerts.values())
    if total:
        parts = [f"{RULE_LABELS.get(r, r)} {n}" for r, n in sorted(s.alerts.items(), key=_desc)]
        lines.append(f"เตือนท่า {total} ครั้ง: " + ", ".join(parts))
    else:
        lines.append("ยังไม่มีเตือนเรื่องท่าวันนี้")
    if s.zone_share:
        parts = [
            f"{ZONE_LABELS.get(z, z)} {share:.0%}"
            for z, share in sorted(s.zone_share.items(), key=_desc)
        ]
        lines.append("เวลาต่อโซน: " + ", ".join(parts))
    return lines


def _desc(item: tuple[str, float]) -> tuple[float, str]:
    return -item[1], item[0]


def day_bounds(now: float | None = None) -> tuple[float, float]:
    d = datetime.fromtimestamp(time.time() if now is None else now)
    start = d.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


# -------------------------------------------------------------------- storage


class Storage:
    """Owned by one thread (the worker). ``path=":memory:"`` for tests."""

    def __init__(self, path: Path | str | None = None) -> None:
        path = default_db_path() if path is None else path
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.executescript(SCHEMA)

    def add_sample(self, s: Summary) -> None:
        cols = ["ts", "duration_s", "present_frac", "zone", "status", *METRIC_FIELDS]
        vals = [s.ts, s.duration_s, s.present_frac, s.zone, s.status]
        vals += [getattr(s.metrics, name) for name in METRIC_FIELDS]
        self.conn.execute(
            f"INSERT INTO samples ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            vals,
        )
        self.conn.commit()

    def add_event(self, kind: str, detail: str | None = None, ts: float | None = None) -> None:
        self.conn.execute(
            "INSERT INTO events (ts, kind, detail) VALUES (?, ?, ?)",
            (time.time() if ts is None else ts, kind, detail),
        )
        self.conn.commit()

    def day_stats(self, start: float, end: float) -> DayStats:
        q = self.conn.execute
        (sitting,) = q(
            "SELECT COALESCE(SUM(duration_s * present_frac), 0) FROM samples"
            " WHERE ts >= ? AND ts < ?",
            (start, end),
        ).fetchone()
        counts = dict(
            q(
                "SELECT kind, COUNT(*) FROM events WHERE ts >= ? AND ts < ? GROUP BY kind",
                (start, end),
            ).fetchall()
        )
        alerts = dict(
            q(
                "SELECT detail, COUNT(*) FROM events WHERE kind = 'alert' AND ts >= ? AND ts < ?"
                " GROUP BY detail",
                (start, end),
            ).fetchall()
        )
        return DayStats(
            sitting_s=float(sitting),
            stand_ups=counts.get("stood_up", 0),
            break_reminders=counts.get("break_reminder", 0),
            alerts=alerts,
            zone_share=self.zone_share(start, end),
        )

    def zone_share(self, start: float, end: float) -> dict[str, float]:
        rows = self.conn.execute(
            "SELECT zone, SUM(duration_s * present_frac) FROM samples"
            " WHERE ts >= ? AND ts < ? AND zone IS NOT NULL GROUP BY zone",
            (start, end),
        ).fetchall()
        total = sum(v for _, v in rows)
        return {z: v / total for z, v in rows} if total > 0 else {}

    def present_seconds(self, start: float, end: float) -> float:
        (v,) = self.conn.execute(
            "SELECT COALESCE(SUM(duration_s * present_frac), 0) FROM samples"
            " WHERE ts >= ? AND ts < ?",
            (start, end),
        ).fetchone()
        return float(v)

    def close(self) -> None:
        self.conn.close()


# ---------------------------------------------------------- session recorder


class SessionRecorder:
    """Writes per-frame metrics to CSV: t (seconds since start), present, metrics.

    Numbers only. Use ``python -m meerkat --replay FILE`` to re-run the rules on it.
    """

    HEADER = ["t", "present", *METRIC_FIELDS]

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            path = sessions_dir() / time.strftime("session-%Y%m%d-%H%M%S.csv")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._f = path.open("w", newline="", encoding="utf-8")
        self._w = csv.writer(self._f)
        self._w.writerow(self.HEADER)
        self._t0: float | None = None

    def write(self, t: float, m: PostureMetrics) -> None:
        if self._t0 is None:
            self._t0 = t
        row = [f"{t - self._t0:.3f}", int(m.present)]
        row += ["" if (v := getattr(m, name)) is None else f"{v:.5f}" for name in METRIC_FIELDS]
        self._w.writerow(row)

    def close(self) -> None:
        self._f.close()


def read_session(path: Path) -> list[tuple[float, PostureMetrics]]:
    out = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not {"t", "present"} <= set(reader.fieldnames):
            raise ValueError(f"{path} is not a Meerkat session file")
        for row in reader:
            values = {name: float(row[name]) if row.get(name) else None for name in METRIC_FIELDS}
            out.append((float(row["t"]), PostureMetrics(present=row["present"] == "1", **values)))
    return out
