"""Find where a wash cycle starts and ends, and keep the totals."""
from __future__ import annotations

from dataclasses import replace

from .status import RUNNING, Status
from .store import Cycle, Store

__all__ = ["Cycle", "CycleTracker"]

# Phases that end an open cycle without a "done": the washer went back to
# idle, to standby, or to a new delay before we saw "done".
UNCONFIRMED_END = {"idle", "off", "delayed"}


class CycleTracker:
    def __init__(self, store: Store):
        self.store = store
        self.open: Cycle | None = store.load_open_cycle()

    def update(self, status: Status, now: float) -> Cycle | None:
        """Feed one status. Return the cycle that ended with it, if any."""
        phase = status.phase
        if self.open is None:
            if phase in RUNNING:
                self.open = Cycle(started=now, ended=None, energy_kwh=status.energy_kwh,
                                  water_l=status.water_l, program_raw=status.program_raw,
                                  confirmed=None)
                self.store.save_open_cycle(self.open)
            return None

        if phase in RUNNING or phase == "done":
            # Energy and water only grow during a cycle; a reset to 0 is standby.
            self.open = replace(self.open,
                                energy_kwh=max(self.open.energy_kwh, status.energy_kwh),
                                water_l=max(self.open.water_l, status.water_l))
        if phase == "done":
            return self._close(now, confirmed=True)
        if phase in UNCONFIRMED_END:
            return self._close(now, confirmed=False)
        if phase in RUNNING:
            self.store.save_open_cycle(self.open)
        return None  # "unknown" changes nothing

    def _close(self, now: float, confirmed: bool) -> Cycle:
        """Count the cycle once, even when a crash interrupts this and the
        restarted app closes the same open cycle again. Each step checks
        whether it already ran; the open cycle goes last."""
        cycle = replace(self.open, ended=now, confirmed=confirmed)
        totals = self.store.load_totals()
        if totals.last_started != cycle.started:
            totals.energy_kwh = round(totals.energy_kwh + cycle.energy_kwh, 2)
            totals.water_l = round(totals.water_l + cycle.water_l, 2)
            totals.cycles += 1
            totals.last_started = cycle.started
            self.store.save_totals(totals)
        last = self.store.recent_cycles(1)
        if not last or last[0].started != cycle.started:
            self.store.append_cycle(cycle)
        self.store.save_open_cycle(None)
        self.open = None
        return cycle
