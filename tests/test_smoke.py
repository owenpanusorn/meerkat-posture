import pytest

from meerkat.__main__ import main, parse_args


def test_parse_args():
    args = parse_args(["--debug", "--camera", "1", "--fps", "3"])
    assert args.debug is True and args.camera == 1 and args.fps == 3
    assert parse_args([]).debug is False


def test_version_exits_zero():
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0


def test_app_modules_import():
    import meerkat.app  # noqa: F401
    import meerkat.notifier  # noqa: F401
    import meerkat.tray  # noqa: F401


def test_icons_draw_all_states():
    from meerkat.tray import ICON_STATES, draw_icon

    for state in ICON_STATES:
        img = draw_icon(state)
        assert img.size == (64, 64) and img.mode == "RGBA"
