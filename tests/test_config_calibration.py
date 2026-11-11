import pytest

from meerkat import config
from meerkat.calibration import average, capture_ok, from_config, nearest_zone, to_config
from meerkat.metrics import PostureMetrics


def test_defaults_match_plan():
    cfg = config.Config()
    assert cfg.camera.fps == 5.0
    assert cfg.rules["head_down"].threshold == 15 and cfg.rules["head_down"].hold_s == 30
    assert cfg.rules["twist"].threshold == 0.85
    assert cfg.alerts.rule_cooldown_s == 300 and cfg.alerts.global_cooldown_s == 60
    assert cfg.sitting.break_after_min == 30 and cfg.sitting.away_s == 60


def test_save_load_roundtrip(tmp_path):
    path = tmp_path / "config.toml"
    cfg = config.Config()
    cfg.camera.index = 2
    cfg.rules["roll"].hold_s = 12.5
    cfg.zones["main"] = {"head_yaw": 1.5, "head_pitch": -4.0}
    config.save(cfg, path)
    loaded = config.load(path)
    assert loaded == cfg


def test_partial_file_uses_defaults_and_ignores_junk(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        "[camera]\nfps = 3\nbogus = 1\n[rules.head_down]\nthreshold = 20\n[rules.nope]\nx = 1\n"
        '[alerts]\nhysteresis = "oops"\n',
        encoding="utf-8",
    )
    cfg = config.load(path)
    assert cfg.camera.fps == 3.0 and isinstance(cfg.camera.fps, float)
    assert cfg.rules["head_down"].threshold == 20 and cfg.rules["head_down"].hold_s == 30
    assert "nope" not in cfg.rules
    assert cfg.alerts.hysteresis == 0.8


def test_missing_file_gives_defaults(tmp_path):
    assert config.load(tmp_path / "none.toml") == config.Config()


def test_average_ignores_absent_and_none():
    samples = [
        PostureMetrics(True, head_yaw=2.0, head_pitch=-4.0, shoulder_tilt=None),
        PostureMetrics(False),
        PostureMetrics(True, head_yaw=4.0, head_pitch=-6.0, shoulder_tilt=1.0),
    ]
    avg = average(samples)
    assert avg.head_yaw == pytest.approx(3.0)
    assert avg.head_pitch == pytest.approx(-5.0)
    assert avg.shoulder_tilt == pytest.approx(1.0)
    assert avg.neck_drop is None


def test_average_needs_a_face():
    assert average([PostureMetrics(False)] * 5) is None


def test_capture_ok():
    p, a = PostureMetrics(True), PostureMetrics(False)
    assert capture_ok([p] * 10)
    assert not capture_ok([p] * 4 + [a] * 6)
    assert not capture_ok([p, p])
    assert not capture_ok([])


def test_config_roundtrip_of_baseline():
    base = PostureMetrics(True, head_yaw=1.0, head_pitch=-3.0, face_scale=0.12)
    assert from_config(to_config(base)) == base
    assert "neck_drop" not in to_config(base)


def test_nearest_zone():
    zones = {
        "main": PostureMetrics(True, head_yaw=0.0, head_pitch=0.0),
        "second": PostureMetrics(True, head_yaw=40.0, head_pitch=0.0),
    }
    assert nearest_zone(PostureMetrics(True, head_yaw=5.0, head_pitch=-10.0), zones) == "main"
    assert nearest_zone(PostureMetrics(True, head_yaw=30.0, head_pitch=0.0), zones) == "second"
    assert nearest_zone(PostureMetrics(True), zones) is None
