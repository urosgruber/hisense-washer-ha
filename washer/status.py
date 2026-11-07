"""Decode the washer status (message 901, entry msgtype 102).

Decoding steps:
1. Base64-decode the result.
2. Un-stuff: raw f4 is the frame start marker, so the washer doubles a data
   byte f4. Replace every raw f4 f4 with one f4.
3. XOR every byte with 0xFF.
4. A field value is byte - 1. So 0x01 is the value 0 (it also fills unused bytes).
The phase (byte 18) is the decoded byte itself, with no "- 1".
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field

from .frame import Frame

PHASES = {
    0x04: "off",
    0x24: "idle",
    0x2C: "delayed",
    0x44: "washing",
    0x45: "rinsing",
    0x48: "spinning",
    0x4B: "done",
}
RUNNING = {"washing", "rinsing", "spinning"}

B_PROGRAM = 20
B_SPIN = 22
B_FLAGS = 28
B_MINUTES = 31
B_ENERGY = 66
B_WATER_L = 67
B_WATER_CL = 68
DOOR_BIT = 0x20
STATUS_MSGTYPE = 102


def decode_result(b64: str) -> bytes:
    raw = base64.b64decode(b64).replace(b"\xf4\xf4", b"\xf4")
    return bytes(x ^ 0xFF for x in raw)


def _value(d: bytes, i: int) -> int | None:
    if i >= len(d) or d[i] == 0:
        return None
    return d[i] - 1


@dataclass(frozen=True)
class Status:
    phase: str
    phase_raw: int
    minutes_left: int | None
    spin_rpm: int | None
    energy_kwh: float
    water_l: float
    door_locked: bool | None
    program_raw: int | None
    # The decoded 115 bytes, for the admin page. Not part of equality.
    raw: bytes = field(default=b"", compare=False, repr=False)

    @classmethod
    def from_bytes(cls, d: bytes) -> "Status":
        spin = _value(d, B_SPIN)
        energy = _value(d, B_ENERGY)
        litres = _value(d, B_WATER_L)
        centi = _value(d, B_WATER_CL)
        flags = d[B_FLAGS] if B_FLAGS < len(d) else None
        return cls(
            phase=PHASES.get(d[18], "unknown"),
            phase_raw=d[18],
            minutes_left=_value(d, B_MINUTES),
            spin_rpm=None if spin is None else spin * 100,
            energy_kwh=round((energy or 0) / 100, 2),
            water_l=round((litres or 0) + (centi or 0) / 100, 2),
            door_locked=None if flags is None else bool(flags & DOOR_BIT),
            program_raw=_value(d, B_PROGRAM),
            raw=bytes(d),
        )


def status_from_frame(f: Frame) -> Status | None:
    if not f.body:
        return None
    for entry in f.body.get("status") or []:
        if isinstance(entry, dict) and entry.get("msgtype") == STATUS_MSGTYPE:
            try:
                return Status.from_bytes(decode_result(entry["result"]))
            except (KeyError, ValueError, IndexError, TypeError):
                return None
    return None
