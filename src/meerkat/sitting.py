"""Sitting timer (PLAN.md section 9). Pure: feed it (time, present) samples.

- Starts counting when a face is seen.
- No face for ``away_s`` seconds in a row means the user stood up: reset.
- After ``break_after_s`` of sitting, remind; repeat every ``repeat_s`` until they stand.
- ``snooze`` holds reminders back for a while (meetings).
"""

from __future__ import annotations


class SittingTimer:
    def __init__(
        self, break_after_s: float = 1800.0, repeat_s: float = 600.0, away_s: float = 60.0
    ) -> None:
        self.break_after_s = break_after_s
        self.repeat_s = repeat_s
        self.away_s = away_s
        self.reset()

    def reset(self) -> None:
        self._start: float | None = None
        self._last_seen: float | None = None
        self._last_reminder: float | None = None
        self._snooze_until = 0.0

    def sitting_s(self, t: float) -> float:
        return 0.0 if self._start is None else t - self._start

    def snooze(self, t: float, duration_s: float) -> None:
        self._snooze_until = t + duration_s

    def snoozed(self, t: float) -> bool:
        return t < self._snooze_until

    def update(self, t: float, present: bool) -> bool:
        """Return True when a "time to stand up" reminder should be shown now."""
        if present:
            if self._start is None:
                self._start = t
            self._last_seen = t
        elif self._last_seen is not None and t - self._last_seen >= self.away_s:
            snooze = self._snooze_until
            self.reset()
            self._snooze_until = snooze
            return False

        if not present or self._start is None or self.snoozed(t):
            return False
        if t - self._start < self.break_after_s:
            return False
        if self._last_reminder is not None and t - self._last_reminder < self.repeat_s:
            return False
        self._last_reminder = t
        return True
