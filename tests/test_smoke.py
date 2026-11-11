from meerkat.__main__ import main, parse_args


def test_parse_debug_flag():
    assert parse_args(["--debug"]).debug is True
    assert parse_args([]).debug is False


def test_main_returns_zero():
    assert main([]) == 0
