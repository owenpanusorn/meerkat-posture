import pytest

from meerkat.buddy import KEY, MEERKAT_H, MEERKAT_W, MESSAGES, Nudge, draw_meerkat


def test_nudge_levels():
    n = Nudge(escalate_after_s=300, center_after_s=600)
    assert n.level(0) == 0 and not n.active
    n.start(100)
    assert n.level(100) == 1
    assert n.level(399) == 1
    assert n.level(400) == 2
    assert n.level(700) == 3


def test_nudge_without_center_stays_at_2():
    n = Nudge(300, 600, center=False)
    n.start(0)
    assert n.level(10_000) == 2


def test_nudge_start_is_idempotent_and_stop_resets():
    n = Nudge(300, 600)
    n.start(0)
    n.start(250)  # a repeated reminder must not restart the escalation
    assert n.level(310) == 2
    n.stop()
    assert n.level(310) == 0
    n.start(400)
    assert n.level(410) == 1


@pytest.mark.parametrize("pose", ["stand", "wave", "happy"])
@pytest.mark.parametrize("scale", [1.0, 1.5])
def test_draw_meerkat(pose, scale):
    img = draw_meerkat(pose, scale)
    assert img.size == (round(MEERKAT_W * scale), round(MEERKAT_H * scale))
    assert img.getpixel((0, 0)) == KEY  # transparent background
    colors = {c for _, c in img.getcolors(maxcolors=4096)}
    assert len(colors) > 4  # actually drew something


def test_drawing_never_uses_the_transparent_color_inside():
    # The center of the body must not be see-through.
    img = draw_meerkat("stand")
    assert img.getpixel((MEERKAT_W // 2, 160)) != KEY


def test_messages_for_every_level():
    for key in (1, 2, 3, "celebrate"):
        title, line = MESSAGES[key]
        assert title and line
    assert "{minutes}" in MESSAGES[1][0]
