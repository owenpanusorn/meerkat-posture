from dataclasses import replace
from datetime import datetime

import pytest

from meerkat.config import Config
from meerkat.metrics import PostureMetrics
from meerkat.replay import replay, report
from meerkat.storage import (
    Aggregator,
    DayStats,
    SessionRecorder,
    Storage,
    Summary,
    day_bounds,
    format_stats,
    read_session,
)

GOOD = PostureMetrics(
    present=True,
    head_yaw=0.0,
    head_pitch=-5.0,
    head_roll=0.0,
    face_scale=0.12,
    shoulder_tilt=0.0,
    shoulder_width=0.4,
    neck_drop=0.6,
)
AWAY = PostureMetrics(False)


def test_aggregator_emits_every_period():
    agg = Aggregator(period_s=10)
    out = [agg.add(t * 0.5, GOOD, "main", 0) for t in range(25)]  # 0 .. 12 s
    summaries = [s for s in out if s is not None]
    assert len(summaries) == 1
    s = summaries[0]
    assert s.ts == 0 and s.duration_s == pytest.approx(10)
    assert s.present_frac == 1.0 and s.zone == "main"
    assert s.metrics.head_pitch == pytest.approx(-5.0)


def test_aggregator_mixed_presence_zone_and_status():
    agg = Aggregator(period_s=4)
    agg.add(0, GOOD, "main", 0)
    agg.add(1, replace(GOOD, head_yaw=40.0), "second", 1)
    agg.add(2, replace(GOOD, head_yaw=40.0), "second", 2)
    agg.add(3, AWAY, None, 0)
    s = agg.add(4, AWAY, None, 0)  # closes the 0-4 s window; this sample starts the next
    assert s.duration_s == 4
    assert s.present_frac == pytest.approx(3 / 4)
    assert s.zone == "second"
    assert s.status == 2
    assert s.metrics.head_yaw == pytest.approx(80 / 3)


def test_aggregator_all_absent():
    agg = Aggregator(period_s=1)
    agg.add(0, AWAY, None, 0)
    s = agg.add(1, AWAY, None, 0)
    assert s.present_frac == 0 and not s.metrics.present and s.metrics.head_yaw is None


def test_aggregator_does_not_count_a_pause_gap():
    agg = Aggregator(period_s=10)
    for t in range(5):
        agg.add(t, GOOD, "main", 0)
    s = agg.add(600, GOOD, "main", 0)  # camera was off for ~10 min
    assert s.duration_s == pytest.approx(4 + Aggregator.MAX_GAP_S)


def test_windows_are_contiguous():
    agg = Aggregator(period_s=10)
    total = 0.0
    for i in range(3600 * 5):
        if (s := agg.add(i / 5, GOOD, "main", 0)) is not None:
            total += s.duration_s
    assert total == pytest.approx(3600 - 10, abs=0.5)  # last open window not flushed


def _fill(db: Storage, t0: float):
    agg = Aggregator(period_s=10)
    # 20 min in main zone, 10 min looking at the second screen, 5 min away.
    t = t0
    for metrics, zone, minutes in ((GOOD, "main", 20), (GOOD, "second", 10), (AWAY, None, 5)):
        for _ in range(minutes * 60):
            t += 1
            if (s := agg.add(t, metrics, zone, 0)) is not None:
                db.add_sample(s)
    db.add_event("alert", "head_down", ts=t0 + 100)
    db.add_event("alert", "head_down", ts=t0 + 900)
    db.add_event("alert", "slouch", ts=t0 + 1000)
    db.add_event("stood_up", ts=t0 + 2000)
    db.add_event("break_reminder", ts=t0 + 1800)
    db.add_event("alert", "roll", ts=t0 - 86400)  # yesterday


def test_day_stats():
    db = Storage(":memory:")
    t0 = datetime(2026, 11, 11, 9, 0).timestamp()
    _fill(db, t0)
    stats = db.day_stats(*day_bounds(t0))
    assert stats.sitting_s == pytest.approx(30 * 60, abs=15)
    assert stats.alerts == {"head_down": 2, "slouch": 1}
    assert stats.stand_ups == 1 and stats.break_reminders == 1
    assert stats.zone_share["main"] == pytest.approx(2 / 3, abs=0.01)
    assert stats.zone_share["second"] == pytest.approx(1 / 3, abs=0.01)


def _samples(db: Storage, t0: float, pattern):
    """pattern: list of (minutes, present_frac). Writes contiguous 10 s samples."""
    t = t0
    for minutes, frac in pattern:
        for _ in range(int(minutes * 6)):
            m = GOOD if frac > 0 else AWAY
            db.add_sample(Summary(t, 10.0, frac, "main" if frac else None, 0, m))
            t += 10
    return t


def test_session_continues_after_quick_restart():
    db = Storage(":memory:")
    end = _samples(db, 1000.0, [(25, 1.0)])
    start = db.current_session_start(end + 30, away_s=60)  # app was off 30 s
    assert start == 1000.0


def test_session_not_restored_after_long_gap():
    db = Storage(":memory:")
    end = _samples(db, 1000.0, [(25, 1.0)])
    assert db.current_session_start(end + 600, away_s=60) is None


def test_session_starts_after_last_time_away():
    db = Storage(":memory:")
    # sat 20 min, away 2 min (stood up), sat 15 min
    end = _samples(db, 1000.0, [(20, 1.0), (2, 0.0), (15, 1.0)])
    start = db.current_session_start(end + 10, away_s=60)
    assert start == pytest.approx(end - 15 * 60)


def test_short_absence_does_not_split_session():
    db = Storage(":memory:")
    end = _samples(db, 1000.0, [(20, 1.0), (0.5, 0.0), (10, 1.0)])
    assert db.current_session_start(end + 10, away_s=60) == 1000.0


def test_restart_gap_inside_history_splits_at_long_gap():
    db = Storage(":memory:")
    end1 = _samples(db, 1000.0, [(20, 1.0)])
    end2 = _samples(db, end1 + 900, [(10, 1.0)])  # app off 15 min in between
    assert db.current_session_start(end2 + 10, away_s=60) == end1 + 900


def test_format_stats():
    lines = format_stats(
        DayStats(
            sitting_s=95 * 60,
            stand_ups=2,
            break_reminders=1,
            alerts={"head_down": 3, "slouch": 1},
            zone_share={"main": 0.7, "second": 0.3},
        )
    )
    assert lines[0] == "นั่งรวม 1 ชม. 35 นาที"
    assert "ก้ม 3" in lines[2] and lines[2].index("ก้ม") < lines[2].index("ค่อม")
    assert "จอหลัก 70%" in lines[3]
    assert format_stats(DayStats())[2] == "ยังไม่มีเตือนเรื่องท่าวันนี้"


def test_session_roundtrip(tmp_path):
    path = tmp_path / "s.csv"
    rec = SessionRecorder(path)
    rec.write(100.0, GOOD)
    rec.write(100.5, replace(GOOD, neck_drop=None))
    rec.write(101.0, AWAY)
    rec.close()
    rows = read_session(path)
    assert [t for t, _ in rows] == [0.0, 0.5, 1.0]
    assert rows[0][1] == GOOD
    assert rows[1][1].neck_drop is None
    assert rows[2][1] == AWAY


def test_replay_finds_head_down_alert(tmp_path):
    cfg = Config()
    cfg.zones["main"] = {k: v for k, v in GOOD.__dict__.items() if k != "present"}
    head_down = replace(GOOD, head_pitch=-25.0)
    samples = [(i / 5, GOOD) for i in range(25)]
    samples += [(5 + i / 5, head_down) for i in range(40 * 5)]
    samples += [(45 + i / 5, AWAY) for i in range(70 * 5)]
    events = replay(samples, cfg)
    kinds = [(e.kind, e.detail) for e in events]
    assert kinds == [("alert", "head_down"), ("stood_up", None)]
    assert events[0].t == pytest.approx(5 + 30 + 1, abs=1.5)  # + smoothing lag
    assert "head_down=1" in report(events)
