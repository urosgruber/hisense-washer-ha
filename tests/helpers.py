"""Test helpers shared by several test files."""
import json
from pathlib import Path

from washer.status import Status, decode_result

FIXTURES = Path(__file__).parent / "fixtures"

PHASE_RAW = {"off": 0x04, "idle": 0x24, "delayed": 0x2C, "washing": 0x44,
             "rinsing": 0x45, "spinning": 0x48, "done": 0x4B, "unknown": 0x42}


def make_status(phase, minutes=0, energy=0.0, water=0.0):
    return Status(phase=phase, phase_raw=PHASE_RAW[phase], minutes_left=minutes,
                  spin_rpm=1200, energy_kwh=energy, water_l=water,
                  door_locked=phase in ("washing", "rinsing", "spinning"),
                  program_raw=26)


def fixture_statuses(name):
    """Yield (time, Status) for each line of a fixture file."""
    for line in (FIXTURES / name).read_text().splitlines():
        if line:
            rec = json.loads(line)
            yield rec["t"], Status.from_bytes(decode_result(rec["result"]))
