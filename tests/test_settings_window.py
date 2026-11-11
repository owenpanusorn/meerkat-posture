import pytest

from meerkat import config
from meerkat.settings_window import (
    FIELDS,
    RULE_NAMES,
    apply,
    defaults,
    parse,
    save_values,
    values_from,
)


def test_every_rule_has_three_fields():
    paths = {f.path for f in FIELDS}
    assert set(RULE_NAMES) == set(config.default_rules())
    for name in RULE_NAMES:
        for key in ("enabled", "threshold", "hold_s"):
            assert f"rules.{name}.{key}" in paths


def test_round_trip_keeps_the_defaults():
    cfg = apply(config.Config(), defaults())
    assert cfg == config.Config()


def test_ui_units():
    v = defaults()
    assert v["rules.lean_in.threshold"] == 15  # 1.15 -> 15 % larger
    assert v["rules.twist.threshold"] == 15  # 0.85 -> 15 % narrower
    assert v["alerts.rule_cooldown_s"] == 5  # 300 s shown as minutes
    assert v["sitting.break_after_min"] == 30


def test_apply_converts_back_and_keeps_types():
    v = defaults()
    v.update(
        {
            "rules.lean_in.threshold": 20,
            "rules.slouch.threshold": 10,
            "alerts.rule_cooldown_s": 2,
            "rules.head_down.threshold": "18",
            "buddy.center": False,
            "alerts.sound_style": "system",
        }
    )
    cfg = apply(config.Config(), v)
    assert cfg.rules["lean_in"].threshold == pytest.approx(1.20)
    assert cfg.rules["slouch"].threshold == pytest.approx(0.90)
    assert cfg.alerts.rule_cooldown_s == 120.0
    assert cfg.rules["head_down"].threshold == 18.0
    assert isinstance(cfg.rules["head_down"].threshold, float)
    assert cfg.buddy.center is False
    assert cfg.alerts.sound_style == "system"


def test_parse_clamps_and_rejects_text():
    f = next(f for f in FIELDS if f.path == "sitting.break_after_min")
    assert parse(f, "1000") == f.hi
    assert parse(f, "-5") == f.lo
    assert parse(f, " 45 ") == 45
    with pytest.raises(ValueError):
        parse(f, "abc")
    style = next(f for f in FIELDS if f.path == "alerts.sound_style")
    assert parse(style, "nonsense") == "meerkat"


def test_new_break_interval_is_added_to_the_tray_choices():
    v = defaults()
    v["sitting.break_after_min"] = 50
    cfg = apply(config.Config(), v)
    assert cfg.sitting.break_after_min == 50.0
    assert cfg.sitting.break_after_options_min == [30, 45, 50, 60]


def test_save_keeps_zones_and_other_keys(tmp_path):
    path = tmp_path / "config.toml"
    cfg = config.Config()
    cfg.zones["main"] = {"head_pitch": -3.5}
    cfg.camera.index = 2
    config.save(cfg, path)

    v = values_from(config.load(path))
    v["sitting.repeat_min"] = 12
    save_values(v, path)

    back = config.load(path)
    assert back.sitting.repeat_min == 12.0
    assert back.zones == {"main": {"head_pitch": -3.5}}
    assert back.camera.index == 2
