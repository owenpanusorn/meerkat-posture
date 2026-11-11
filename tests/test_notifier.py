from meerkat.notifier import Notifier


class Captured(Notifier):
    """Notifier that records queued messages instead of showing them."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.sent = []

    def send(self, title, message, sound=False):
        self.sent.append((title, sound))


def make(**kwargs):
    n = Captured(**kwargs)
    n.close()  # stop the background thread; we only inspect what would be sent
    return n


def test_posture_and_break_have_sound_by_default():
    n = make()
    n.alert("head_down")
    n.break_reminder(30)
    assert [s for _, s in n.sent] == [True, True]


def test_sound_can_be_turned_off_per_kind():
    n = make(sound_posture=False, sound_break=True)
    n.alert("head_down")
    n.break_reminder(30)
    assert [s for _, s in n.sent] == [False, True]


def test_info_messages_are_silent():
    n = make()
    Notifier.send(n, "x", "y")  # default sound=False
    assert n._q.get_nowait() == ("x", "y", False)
