import wave

import pytest

from meerkat import notifier as nmod
from meerkat.notifier import BREAK, POSTURE, Notifier, sound_path


@pytest.fixture
def captured(monkeypatch):
    """A Notifier whose background thread is replaced by a list of what would be sent."""
    monkeypatch.setattr(Notifier, "_run", lambda self: None)
    sent = []

    def make(**kwargs):
        n = Notifier(**kwargs)
        n.send = lambda title, message, sound=None, sticky=False: sent.append(
            (title, sound, sticky)
        )
        return n

    return make, sent


def test_posture_and_break_have_distinct_sounds(captured):
    make, sent = captured
    n = make()
    n.alert("head_down")
    n.break_reminder(30)
    assert [(s, k) for _, s, k in sent] == [(POSTURE, True), (BREAK, True)]


def test_sound_can_be_turned_off_per_kind(captured):
    make, sent = captured
    n = make(sound_posture=False, sound_break=True)
    n.alert("head_down")
    n.break_reminder(30)
    assert [s for _, s, _ in sent] == [None, BREAK]


def test_info_messages_are_silent(monkeypatch):
    monkeypatch.setattr(Notifier, "_run", lambda self: None)
    n = Notifier()
    n.send("x", "y")
    assert n._q.get_nowait() == ("x", "y", None, False)


@pytest.mark.parametrize("kind", [POSTURE, BREAK])
def test_sound_files_exist_and_are_short(kind):
    path = sound_path(kind)
    assert path.exists(), "run: uv run python scripts/make_sounds.py"
    with wave.open(str(path)) as w:
        seconds = w.getnframes() / w.getframerate()
    assert 0.1 < seconds < 1.0


def test_every_rule_has_a_message():
    from meerkat.rules import RULE_ORDER

    assert set(RULE_ORDER) <= set(nmod.RULE_MESSAGES)
