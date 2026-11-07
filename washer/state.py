"""The live view of the washer that MQTT, the card and the admin page read."""
from __future__ import annotations

from collections import deque

from .status import RUNNING, Status
from .store import Cycle

# After the washer drops, keep the last state this long (a short Wi-Fi drop
# must not hide the end time).
GRACE_S = 600
# The washer sends a heartbeat about every 180 s. Two missed plus a margin.
LIVENESS_S = 420

LIVE_KEYS = ("minutes_left", "end_time", "spin_rpm", "door_locked",
             "cycle_energy_kwh", "cycle_water_l")

RAW_HISTORY = 40  # distinct status snapshots kept in memory


class WasherState:
    def __init__(self):
        # (time, raw bytes) of the last distinct statuses, for decoding new fields.
        self.raw_history: deque[tuple[float, bytes]] = deque(maxlen=RAW_HISTORY)
        self.status: Status | None = None
        self.status_at: float | None = None
        self.last_frame: float | None = None
        self.connected = False
        self.disconnected_at: float | None = None
        self.last_cycle: Cycle | None = None

    def on_connect(self, now: float) -> None:
        self.connected = True
        self.disconnected_at = None
        self.last_frame = now

    def on_frame(self, now: float) -> None:
        self.last_frame = now

    def on_status(self, s: Status, now: float) -> None:
        if s.raw and (not self.raw_history or self.raw_history[-1][1] != s.raw):
            self.raw_history.append((now, s.raw))
        self.status = s
        self.status_at = now
        self.last_frame = now

    def on_disconnect(self, now: float) -> None:
        self.connected = False
        self.disconnected_at = now

    def _lost_since(self, now: float) -> float | None:
        """When the washer was lost, or None while it is alive."""
        if not self.connected:
            return self.disconnected_at if self.disconnected_at is not None else float("-inf")
        if self.last_frame is not None and now - self.last_frame > LIVENESS_S:
            return self.last_frame + LIVENESS_S
        return None

    def view(self, now: float) -> dict:
        lost = self._lost_since(now)
        s = self.status
        v = {
            "phase": "off",
            "phase_raw": None,
            "minutes_left": None,
            "end_time": None,
            "spin_rpm": None,
            "door_locked": None,
            "cycle_energy_kwh": None,
            "cycle_water_l": None,
            "connected": lost is None,
            "stale": False,
            "last_status": self.status_at,
            "last_cycle_end": self.last_cycle.ended if self.last_cycle else None,
            "last_cycle_energy_kwh": self.last_cycle.energy_kwh if self.last_cycle else None,
            "last_cycle_water_l": self.last_cycle.water_l if self.last_cycle else None,
            "last_cycle_confirmed": self.last_cycle.confirmed if self.last_cycle else None,
        }
        if s is None or (lost is not None and now - lost > GRACE_S):
            return v
        v.update(
            phase=s.phase,
            phase_raw=f"0x{s.phase_raw:02x}",
            minutes_left=s.minutes_left,
            spin_rpm=s.spin_rpm,
            door_locked=s.door_locked,
            cycle_energy_kwh=s.energy_kwh,
            cycle_water_l=s.water_l,
            stale=lost is not None,
        )
        if s.phase in RUNNING and s.minutes_left is not None and self.status_at is not None:
            v["end_time"] = self.status_at + s.minutes_left * 60
        return v
