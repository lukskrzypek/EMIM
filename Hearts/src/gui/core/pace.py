"""Game tempo shared by the UI thread (writes) and the runner thread (waits)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from gui.config import DEFAULT_DELAY_S

TRICK_HOLD_FACTOR = 0.8  # how long a finished trick stays on the table, relative to the delay
_SLICE = 0.05


class PaceControl:
    """Pause, single step, delay between bot moves (``0`` = full speed) and abort.

    Every wait is made of short slices on a ``Condition``, so a pause, a new
    speed or an abort takes effect within a few milliseconds.
    """

    def __init__(
        self,
        delay: float = DEFAULT_DELAY_S,
        *,
        paused: bool = False,
        pause_after_trick: bool = False,
        on_change: Callable[[bool], None] | None = None,
    ) -> None:
        self._cond = threading.Condition()
        self._delay = max(0.0, delay)
        self._paused = paused
        self._pause_after_trick = pause_after_trick
        self._steps = 0
        self._aborted = False
        self._stepping = False  # a single-step move is being played (pause flag still set)
        self._frozen_since: float | None = None  # clock stopped (paused, not stepping) since then
        self._frozen_total = 0.0  # seconds the clock was stopped before ``_frozen_since``
        self._update_clock()
        self.on_change = on_change  # called (outside the lock) when ``paused`` flips

    # ----------------------------------------------------------------- clock

    def _update_clock(self) -> None:
        """Start / stop the frozen interval after ``_paused`` or ``_stepping`` changed (lock held)."""
        frozen = self._paused and not self._stepping
        now = time.monotonic()
        if frozen and self._frozen_since is None:
            self._frozen_since = now
        elif not frozen and self._frozen_since is not None:
            self._frozen_total += now - self._frozen_since
            self._frozen_since = None

    def clock(self) -> float:
        """Like ``time.monotonic`` but standing still while the game is paused.

        The "bot is thinking" timers use it, so a pause stops them (a stepped move runs
        the clock for as long as that one move takes).
        """
        with self._cond:
            now = time.monotonic()
            frozen = self._frozen_total
            if self._frozen_since is not None:
                frozen += now - self._frozen_since
            return now - frozen

    # ---------------------------------------------------------------- state

    @property
    def delay(self) -> float:
        with self._cond:
            return self._delay

    @delay.setter
    def delay(self, seconds: float) -> None:
        with self._cond:
            self._delay = max(0.0, seconds)
            self._cond.notify_all()

    @property
    def paused(self) -> bool:
        with self._cond:
            return self._paused

    @property
    def pause_after_trick(self) -> bool:
        with self._cond:
            return self._pause_after_trick

    @pause_after_trick.setter
    def pause_after_trick(self, value: bool) -> None:
        with self._cond:
            self._pause_after_trick = value

    @property
    def aborted(self) -> bool:
        with self._cond:
            return self._aborted

    # -------------------------------------------------------------- commands

    def _set_paused(self, value: bool) -> None:
        with self._cond:
            changed = self._paused != value
            self._paused = value
            if not value:
                self._steps = 0
                self._stepping = False
            self._update_clock()
            self._cond.notify_all()
        if changed and self.on_change is not None:
            self.on_change(value)

    def pause(self) -> None:
        self._set_paused(True)

    def resume(self) -> None:
        self._set_paused(False)

    def toggle(self) -> bool:
        """Flip the pause flag and return the new value."""
        with self._cond:
            target = not self._paused
        self._set_paused(target)
        return target

    def step(self) -> None:
        """Let exactly one more move happen while paused (ignored when running)."""
        with self._cond:
            if self._paused and not self._aborted:
                self._steps += 1
                self._cond.notify_all()

    def abort(self) -> None:
        with self._cond:
            self._aborted = True
            self._cond.notify_all()

    # ------------------------------------------------------ runner-side waits

    def gate_before(self) -> bool | None:
        """Block while paused. Returns ``None`` on abort, else whether this move is a single step."""
        with self._cond:
            while True:
                if self._aborted:
                    return None
                if not self._paused:
                    return False
                if self._steps > 0:
                    self._steps -= 1
                    self._stepping = True  # the clock runs while this move is thought out
                    self._update_clock()
                    return True
                self._cond.wait(_SLICE)

    def gate_after(self, since: float, *, stepped: bool = False) -> bool:
        """Wait until ``delay`` has passed since ``since`` (``time.monotonic``). ``False`` on abort."""
        with self._cond:
            if stepped:  # the stepped move is decided: the clock stops again while paused
                self._stepping = False
                self._update_clock()
            while True:
                if self._aborted:
                    return False
                if stepped:
                    return True
                remaining = self._delay - (time.monotonic() - since)
                if remaining <= 0:
                    return True
                self._cond.wait(min(remaining, _SLICE))

    def trick_hold(self) -> bool:
        """Keep a finished trick visible for a moment. ``False`` on abort."""
        started = time.monotonic()
        with self._cond:
            while True:
                if self._aborted:
                    return False
                if self._paused:
                    return True
                remaining = self._delay * TRICK_HOLD_FACTOR - (time.monotonic() - started)
                if remaining <= 0:
                    return True
                self._cond.wait(min(remaining, _SLICE))

    def after_trick(self) -> None:
        """Pause when the user asked for a break after every trick."""
        with self._cond:
            should_pause = self._pause_after_trick and not self._paused and not self._aborted
        if should_pause:
            self.pause()
