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

# Byte 18. The high half is the state: 0 off, 2 ready, 4 running. While
# ready, the low half is the program's first step (Spin shows 0x28, a
# program with pre-wash 0x23), and 0x2C is a delayed start.
RUNNING_STEPS = {0x44: "washing", 0x45: "rinsing", 0x48: "spinning", 0x4B: "done"}
PHASES = {0x04: "off", 0x24: "idle", 0x2C: "delayed", **RUNNING_STEPS}
RUNNING = {"washing", "rinsing", "spinning"}

B_PROGRAM = 20
B_TEMP = 21
B_SPIN = 22
B_OPTIONS = 24          # 0x80 steam
B_DELAY_HOURS = 25
B_FLAGS = 28            # 0x20 door locked, 0x80 extra rinse
B_MINUTES_HI = 30       # minutes left: 16 bits, each byte - 1
B_MINUTES = 31
B_RINSES = 88
B_QUICKER = 107         # 0x20 Quicker level 1, 0x40 level 2
B_ENERGY = 66
B_WATER_L = 67
B_WATER_CL = 68
DOOR_BIT = 0x20
EXTRA_RINSE_BIT = 0x80
STEAM_BIT = 0x80

# Byte 20, as decoded (the knob session of 2026-11-07, Hisense 5S series).
PROGRAMS = {
    0x05: "Refresh", 0x06: "Allergy Care", 0x07: "Drum Clean", 0x08: "Cotton",
    0x09: "Synthetics", 0x0A: "Eco 40-60", 0x0B: "Wool", 0x0C: "Quick 15'",
    0x0F: "Spin", 0x11: "Baby Care", 0x15: "Additional Cycles", 0x1A: "Power 49'/30'",
    0x1B: "Auto", 0x1C: "Bedding",
}
STATUS_MSGTYPE = 102


def decode_result(b64: str) -> bytes:
    raw = base64.b64decode(b64).replace(b"\xf4\xf4", b"\xf4")
    return bytes(x ^ 0xFF for x in raw)


def _value(d: bytes, i: int) -> int | None:
    if i >= len(d) or d[i] == 0:
        return None
    return d[i] - 1


def _bit(d: bytes, i: int, mask: int) -> bool | None:
    return None if i >= len(d) else bool(d[i] & mask)


def _phase(raw: int, delay_hours: int | None) -> str:
    state = raw & 0xF0
    if state == 0x00:
        return "off"
    if state == 0x20:
        return "delayed" if raw == 0x2C or (delay_hours or 0) > 0 else "idle"
    return RUNNING_STEPS.get(raw, "unknown")


def _minutes(d: bytes) -> int | None:
    lo = _value(d, B_MINUTES)
    if lo is None:
        return None
    hi = _value(d, B_MINUTES_HI) or 0
    return hi * 256 + lo


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
    program: str | None = None
    temperature_c: int | None = None
    steam: bool | None = None
    extra_rinse: bool | None = None
    quicker: int | None = None
    rinses: int | None = None
    delay_hours: int | None = None
    # The decoded 115 bytes, for the admin page. Not part of equality.
    raw: bytes = field(default=b"", compare=False, repr=False)

    @classmethod
    def from_bytes(cls, d: bytes) -> "Status":
        spin = _value(d, B_SPIN)
        energy = _value(d, B_ENERGY)
        litres = _value(d, B_WATER_L)
        centi = _value(d, B_WATER_CL)
        flags = d[B_FLAGS] if B_FLAGS < len(d) else None
        temp = _value(d, B_TEMP)
        delay = _value(d, B_DELAY_HOURS)
        quicker = d[B_QUICKER] if B_QUICKER < len(d) else None
        return cls(
            phase=_phase(d[18], delay),
            phase_raw=d[18],
            minutes_left=_minutes(d),
            spin_rpm=None if spin is None else spin * 100,
            energy_kwh=round((energy or 0) / 100, 2),
            water_l=round((litres or 0) + (centi or 0) / 100, 2),
            door_locked=None if flags is None else bool(flags & DOOR_BIT),
            program_raw=_value(d, B_PROGRAM),
            program=PROGRAMS.get(d[B_PROGRAM]) if B_PROGRAM < len(d) else None,
            temperature_c=None if temp is None else temp * 10,
            steam=_bit(d, B_OPTIONS, STEAM_BIT),
            extra_rinse=None if flags is None else bool(flags & EXTRA_RINSE_BIT),
            quicker=None if quicker is None else (2 if quicker & 0x40 else 1 if quicker & 0x20 else 0),
            rinses=_value(d, B_RINSES),
            delay_hours=delay,
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
