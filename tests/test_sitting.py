from meerkat.sitting import SittingTimer

STEP = 1.0  # one sample per second is enough here


def run(timer: SittingTimer, t0: float, seconds: float, present: bool) -> list[float]:
    """Return the times at which a reminder fired."""
    fired = []
    t = t0
    for _ in range(int(seconds / STEP)):
        t += STEP
        if timer.update(t, present):
            fired.append(t)
    return fired


def test_reminds_after_30_minutes():
    timer = SittingTimer()
    fired = run(timer, 0, 29 * 60, True)
    assert fired == []
    fired = run(timer, 29 * 60, 2 * 60, True)
    assert len(fired) == 1
    assert fired[0] >= 30 * 60


def test_repeats_every_10_minutes_if_still_sitting():
    timer = SittingTimer()
    fired = run(timer, 0, 51 * 60, True)
    assert len(fired) == 3  # 30, 40, 50 min


def test_short_absence_does_not_reset():
    timer = SittingTimer()
    run(timer, 0, 20 * 60, True)
    run(timer, 20 * 60, 50, False)  # gone 50 s < 60 s
    assert timer.sitting_s(20 * 60 + 50) >= 20 * 60
    fired = run(timer, 20 * 60 + 50, 11 * 60, True)
    assert len(fired) == 1


def test_standing_up_for_60s_resets():
    timer = SittingTimer()
    run(timer, 0, 25 * 60, True)
    run(timer, 25 * 60, 60, False)
    assert timer.sitting_s(26 * 60) == 0
    fired = run(timer, 26 * 60, 25 * 60, True)
    assert fired == []


def test_snooze_delays_reminder():
    timer = SittingTimer()
    run(timer, 0, 29 * 60, True)
    timer.snooze(29 * 60, 10 * 60)
    fired = run(timer, 29 * 60, 9 * 60, True)
    assert fired == []
    fired = run(timer, 38 * 60, 2 * 60, True)
    assert len(fired) == 1
    assert fired[0] >= 39 * 60


def test_no_reminder_while_away():
    timer = SittingTimer()
    run(timer, 0, 29 * 60 + 30, True)
    fired = run(timer, 29 * 60 + 30, 59, False)
    assert fired == []
