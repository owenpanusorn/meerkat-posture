from dataclasses import replace

import pytest

from meerkat.config import AlertConfig, default_rules
from meerkat.metrics import PostureMetrics
from meerkat.rules import RulesEngine, State, severity

FPS = 5
BASE = PostureMetrics(
    present=True,
    head_yaw=0.0,
    head_pitch=-5.0,
    head_roll=0.0,
    face_scale=0.12,
    shoulder_tilt=0.0,
    shoulder_width=0.4,
    neck_drop=0.6,
)
SECOND = replace(BASE, head_yaw=40.0)
ONE_ZONE = {"main": BASE}
TWO_ZONES = {"main": BASE, "second": SECOND}

GOOD = BASE
HEAD_DOWN = replace(BASE, head_pitch=-25.0)  # 20 deg below baseline
AWAY = PostureMetrics(present=False)


class Sim:
    """Feed a timeline into the engine at FPS and collect alert events."""

    def __init__(self, zones=ONE_ZONE, **alert_overrides):
        self.engine = RulesEngine(default_rules(), AlertConfig(**alert_overrides))
        self.zones = zones
        self.t = 0.0
        self.alerts: list[tuple[float, str]] = []
        self.last = None

    def hold(self, metrics: PostureMetrics, seconds: float) -> "Sim":
        for _ in range(round(seconds * FPS)):
            self.t += 1 / FPS
            self.last = self.engine.update(self.t, metrics, self.zones)
            self.alerts += [(self.t, a) for a in self.last.alerts]
        return self

    def names(self):
        return [a for _, a in self.alerts]


def test_head_down_31s_alerts_once():
    sim = Sim().hold(GOOD, 5).hold(HEAD_DOWN, 31)
    assert sim.names() == ["head_down"]
    assert sim.last.status == State.ALERT


def test_head_down_29s_does_not_alert():
    sim = Sim().hold(GOOD, 5).hold(HEAD_DOWN, 29)
    assert sim.names() == []
    assert sim.last.status == State.WARN


def test_looking_at_second_screen_5min_no_alert():
    sim = Sim(TWO_ZONES).hold(GOOD, 5).hold(replace(SECOND, head_yaw=42.0), 300)
    assert sim.names() == []
    assert sim.last.status == State.OK
    assert sim.last.zone == "second"


def test_same_head_turn_with_one_zone_alerts():
    sim = Sim(ONE_ZONE).hold(GOOD, 5).hold(replace(SECOND, head_yaw=42.0), 300)
    assert "yaw_out" in sim.names()


def test_alert_not_repeated_while_held():
    sim = Sim().hold(HEAD_DOWN, 600)
    assert sim.names() == ["head_down"]


def test_rule_cooldown_blocks_second_episode_within_5_min():
    sim = Sim().hold(HEAD_DOWN, 31).hold(GOOD, 5).hold(HEAD_DOWN, 31)
    assert sim.names() == ["head_down"]
    # After the cooldown has passed, a new episode alerts again.
    sim.hold(GOOD, 300).hold(HEAD_DOWN, 31)
    assert sim.names() == ["head_down", "head_down"]


def test_cooldown_blocked_alert_fires_once_cooldown_ends_if_still_bad():
    sim = Sim().hold(HEAD_DOWN, 31).hold(GOOD, 5).hold(HEAD_DOWN, 400)
    assert sim.names() == ["head_down", "head_down"]
    first, second = (t for t, _ in sim.alerts)
    assert second - first == pytest.approx(300, abs=0.3)


def test_global_cooldown_between_different_rules():
    both = replace(HEAD_DOWN, head_roll=20.0)
    sim = Sim().hold(both, 40)
    # head_down fires at 30 s; roll is also due but waits for the 60 s global cooldown.
    assert sim.names() == ["head_down"]
    sim.hold(both, 60)
    assert sim.names() == ["head_down", "roll"]


def test_recovery_needs_3s_of_good_posture():
    sim = Sim().hold(HEAD_DOWN, 31)
    sim.hold(GOOD, 2)
    assert sim.last.states["head_down"] == State.ALERT
    sim.hold(GOOD, 1.2)
    assert sim.last.states["head_down"] == State.OK


def test_hysteresis_keeps_warn_just_under_threshold():
    sim = Sim().hold(HEAD_DOWN, 10)
    # 13 deg down is under the 15 deg threshold but above 80% (12 deg): stay WARN.
    sim.hold(replace(BASE, head_pitch=-18.0), 25)
    assert sim.last.states["head_down"] == State.ALERT


def test_back_under_hysteresis_resets_warn():
    sim = Sim().hold(HEAD_DOWN, 20).hold(GOOD, 1).hold(HEAD_DOWN, 20)
    assert sim.names() == []


def test_leaving_frame_resets():
    sim = Sim().hold(HEAD_DOWN, 20).hold(AWAY, 5).hold(HEAD_DOWN, 20)
    assert sim.names() == []
    assert sim.last.status == State.WARN


FACE_LOST_BODY_SEEN = PostureMetrics(
    present=False, shoulder_tilt=0.0, shoulder_width=0.4, neck_drop=0.6
)


def test_head_bowed_until_face_is_lost_still_alerts():
    # Real case: head goes down, then the face disappears but the shoulders stay in view.
    # Reported as "phone" because the face got lost while bowed (see phone tests below).
    sim = Sim().hold(GOOD, 5).hold(HEAD_DOWN, 10).hold(FACE_LOST_BODY_SEEN, 25)
    assert len(sim.names()) == 1


def test_face_and_body_gone_resets():
    sim = Sim().hold(HEAD_DOWN, 20).hold(AWAY, 1).hold(HEAD_DOWN, 20)
    assert sim.names() == []


def test_face_lost_hold_expires():
    sim = Sim(face_lost_hold_s=5).hold(HEAD_DOWN, 10).hold(FACE_LOST_BODY_SEEN, 30)
    assert sim.names() == []
    assert sim.last.status == State.OK


def test_face_lost_without_any_face_first_is_ok():
    sim = Sim().hold(FACE_LOST_BODY_SEEN, 120)
    assert sim.names() == []


PHONE_DOWN = replace(BASE, head_pitch=-35.0)  # 30 deg below baseline


def test_deep_head_down_is_reported_as_phone():
    sim = Sim().hold(GOOD, 5).hold(PHONE_DOWN, 31)
    assert sim.names() == ["phone"]


def test_moderate_head_down_stays_head_down():
    sim = Sim().hold(GOOD, 5).hold(HEAD_DOWN, 31)  # 20 deg: e.g. keyboard / notes
    assert sim.names() == ["head_down"]


def test_bowed_until_face_lost_is_phone():
    sim = Sim().hold(GOOD, 5).hold(HEAD_DOWN, 10).hold(FACE_LOST_BODY_SEEN, 25)
    assert sim.names() == ["phone"]


def test_phone_flag_resets_between_episodes():
    sim = Sim(rule_cooldown_s=0, global_cooldown_s=0)
    sim.hold(PHONE_DOWN, 31).hold(GOOD, 5).hold(HEAD_DOWN, 31)
    assert sim.names() == ["phone", "head_down"]


def test_phone_break_mutes_posture_alerts():
    sim = Sim()
    sim.engine.mute(until=sim.t + 600)
    sim.hold(PHONE_DOWN, 300)
    assert sim.names() == []
    assert sim.last.status == State.OK


def test_after_phone_break_alerts_resume():
    sim = Sim()
    sim.engine.mute(until=sim.t + 60)
    sim.hold(PHONE_DOWN, 60)
    assert sim.names() == []
    sim.hold(PHONE_DOWN, 31)  # timer starts fresh after the break
    assert sim.names() == ["phone"]


def test_unmute_ends_break_early():
    sim = Sim()
    sim.engine.mute(until=sim.t + 600)
    sim.hold(PHONE_DOWN, 10)
    sim.engine.unmute()
    sim.hold(PHONE_DOWN, 31)
    assert sim.names() == ["phone"]


def test_missing_values_never_count_as_bad():
    no_shoulders = replace(GOOD, shoulder_tilt=None, shoulder_width=None, neck_drop=None)
    sim = Sim().hold(no_shoulders, 120)
    assert sim.names() == []
    assert sim.last.status == State.OK


def test_uncalibrated_never_alerts():
    sim = Sim(zones={}).hold(HEAD_DOWN, 120)
    assert sim.names() == []


def test_disabled_rule():
    sim = Sim()
    sim.engine.rules["head_down"].enabled = False
    sim.hold(HEAD_DOWN, 60)
    assert sim.names() == []


@pytest.mark.parametrize(
    ("rule", "metrics", "expected"),
    [
        ("head_down", replace(BASE, head_pitch=-20.0), 1.0),
        ("head_up", replace(BASE, head_pitch=5.0), 1.0),
        ("yaw_out", replace(BASE, head_yaw=-15.0), 1.0),
        ("roll", replace(BASE, head_roll=5.0), 0.5),
        ("lean_in", replace(BASE, face_scale=0.12 * 1.15), 1.0),
        ("shoulder_tilt", replace(BASE, shoulder_tilt=-7.0), 1.0),
        ("twist", replace(BASE, shoulder_width=0.4 * 0.85), 1.0),
        ("slouch", replace(BASE, neck_drop=0.6 * 0.85), 1.0),
        ("slouch", replace(BASE, neck_drop=None), None),
    ],
)
def test_severity(rule, metrics, expected):
    threshold = default_rules()[rule].threshold
    got = severity(rule, metrics, BASE, threshold)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)
