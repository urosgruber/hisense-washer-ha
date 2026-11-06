"""Cloud mode: off by default. Only the admin page turns it on, for a limited time."""
from __future__ import annotations

import time
from typing import Awaitable, Callable


class CloudControl:
    def __init__(self, max_hours: float, clock: Callable[[], float] = time.time):
        self.max_hours = max_hours
        self.clock = clock
        self.until: float | None = None
        self.on_change: Callable[[], Awaitable[None]] | None = None

    @property
    def mode(self) -> str:
        return "on" if self.until is not None else "off"
