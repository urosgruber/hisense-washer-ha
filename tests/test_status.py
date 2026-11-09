import base64
import json
import unittest
from pathlib import Path

from washer.frame import parse_frame
from washer.status import RUNNING, Status, decode_result, status_from_frame

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return [json.loads(line) for line in (FIXTURES / name).read_text().splitlines() if line]


def status_of(line):
    return Status.from_bytes(decode_result(line["result"]))


WASH = load("wash-2026-11-06.jsonl")


class WashFixtureTest(unittest.TestCase):
    def test_wash_end_values(self):
        line = next(x for x in WASH if x["t"] == 1793990734.748638)
        s = status_of(line)
        self.assertEqual(s.phase, "done")
        self.assertEqual(s.minutes_left, 0)
        self.assertEqual(s.energy_kwh, 0.45)
        self.assertEqual(s.water_l, 54.76)
        self.assertEqual(s.spin_rpm, 1200)

    def test_wash_snapshot_19h(self):
        # The ConnectLife app showed 0.34 kWh and 7.84 L from its 19:00 snapshot.
        line = [x for x in WASH if x["t"] < 1793988000][-1]
        s = status_of(line)
        self.assertEqual(s.energy_kwh, 0.34)
        self.assertEqual(s.water_l, 7.84)

    def test_minutes_at_1818(self):
        line = next(x for x in WASH if x["t"] > 1793985519 and status_of(x).phase == "washing")
        self.assertEqual(status_of(line).minutes_left, 88)

    def test_unstuff_shifted_fields(self):
        line = next(x for x in WASH if abs(x["t"] - 1793990215.38) < 0.01)
        self.assertEqual(len(base64.b64decode(line["result"])), 118)
        s = status_of(line)
        self.assertEqual(s.phase, "spinning")
        self.assertEqual(s.minutes_left, 10)
        self.assertEqual(s.water_l, 51.91)

    def test_delay_phase(self):
        phases = {status_of(x).phase for x in load("delay-2026-11-05.jsonl")}
        self.assertIn("delayed", phases)


class StatusFieldsTest(unittest.TestCase):
    def test_unknown_phase(self):
        d = bytearray([0x01] * 115)
        d[18] = 0x42
        s = Status.from_bytes(bytes(d))
        self.assertEqual(s.phase, "unknown")
        self.assertEqual(s.phase_raw, 0x42)

    def test_byte_01_is_zero(self):
        d = bytearray([0x01] * 115)
        d[18] = 0x24
        s = Status.from_bytes(bytes(d))
        self.assertEqual(s.phase, "idle")
        self.assertEqual(s.minutes_left, 0)
        self.assertEqual(s.spin_rpm, 0)
        self.assertEqual(s.energy_kwh, 0.0)
        self.assertEqual(s.water_l, 0.0)

    def test_running_set(self):
        self.assertEqual(RUNNING, {"prewashing", "washing", "rinsing", "spinning"})

    def test_prewashing_step(self):
        # Inferred: a ready washer shows 0x23 with pre-wash (0x24 without),
        # so the running pre-wash is 0x43, like 0x44 washing.
        s = session_status(b18=0x43, b24=0x11)
        self.assertEqual(s.phase, "prewashing")

    def test_status_from_frame(self):
        result = WASH[0]["result"]
        body = {"id": 901, "status": [{"msgtype": 30, "result": "gAAAAhUAAAA="},
                                      {"msgtype": 102, "result": result}]}
        raw = b"HS" + json.dumps(body).encode() + b"0" * 64 + b"\r\n"
        s = status_from_frame(parse_frame(raw))
        self.assertEqual(s, status_of(WASH[0]))

    def test_status_from_frame_without_102(self):
        raw = b'HS{"id":901,"status":[]}' + b"0" * 64 + b"\r\n"
        self.assertIsNone(status_from_frame(parse_frame(raw)))


class RawBytesTest(unittest.TestCase):
    def test_status_keeps_raw_bytes(self):
        from tests.helpers import fixture_statuses
        _, s = next(iter(fixture_statuses("wash-2026-11-06.jsonl")))
        self.assertEqual(len(s.raw), 115)
        self.assertEqual(s.raw[18], s.phase_raw)

    def test_raw_does_not_change_equality(self):
        a = Status.from_bytes(bytes([1] * 115))
        b = Status.from_bytes(bytes([1] * 114 + [2]))
        self.assertEqual(a, b)



def session_status(**bytes_at):
    """A status built from the bytes seen in the knob session (2026-11-07)."""
    d = bytearray([1] * 115)
    d[18], d[20], d[21], d[22], d[88], d[107] = 0x24, 0x1b, 0x05, 0x0d, 0x03, 0x0b
    d[31] = d[33] = d[35] = 0x3b
    for name, value in bytes_at.items():
        d[int(name[1:])] = value
    return Status.from_bytes(bytes(d))


class SessionFieldsTest(unittest.TestCase):
    def test_auto_program(self):
        s = session_status()
        self.assertEqual((s.program, s.temperature_c, s.spin_rpm, s.minutes_left),
                         ("Auto", 40, 1200, 58))
        self.assertEqual((s.steam, s.extra_rinse, s.quicker, s.rinses, s.delay_hours),
                         (False, False, 0, 2, 0))

    def test_program_names(self):
        names = {0x0a: "Eco 40-60", 0x08: "Cotton", 0x09: "Synthetics", 0x0b: "Wool",
                 0x1a: "Power 49'/30'", 0x0c: "Quick 15'", 0x15: "Additional Cycles",
                 0x07: "Drum Clean", 0x1c: "Bedding", 0x0f: "Spin", 0x11: "Baby Care",
                 0x06: "Allergy Care", 0x05: "Refresh", 0x1b: "Auto"}
        for code, name in names.items():
            self.assertEqual(session_status(b20=code).program, name)
        self.assertIsNone(session_status(b20=0x30).program)

    def test_temperature(self):
        self.assertEqual(session_status(b21=0x01).temperature_c, 0)     # cold
        self.assertEqual(session_status(b21=0x0a).temperature_c, 90)    # Drum Clean

    def test_no_spin(self):
        self.assertEqual(session_status(b22=0x01).spin_rpm, 0)

    def test_minutes_are_16_bit(self):
        s = session_status(b18=0x2c, b25=0x06, b30=0x02, b31=0x2d)    # end in 5 h
        self.assertEqual((s.phase, s.minutes_left, s.delay_hours), ("delayed", 300, 5))

    def test_steam_extra_rinse_quicker(self):
        self.assertTrue(session_status(b24=0x81).steam)
        self.assertTrue(session_status(b28=0x99, b88=0x04).extra_rinse)
        self.assertEqual(session_status(b28=0x99, b88=0x04).rinses, 3)
        self.assertEqual(session_status(b107=0x2b).quicker, 1)
        self.assertEqual(session_status(b107=0x4b).quicker, 2)

    def test_pre_wash_anti_crease_cold_wash(self):
        # The test session of 2026-11-09: Steam held 3 s, and the Option button.
        s = session_status(b18=0x23, b24=0x11)
        self.assertEqual((s.pre_wash, s.anti_crease, s.cold_wash), (True, False, False))
        self.assertEqual(session_status(b24=0x41).anti_crease, True)
        self.assertEqual(session_status(b100=0x02).cold_wash, True)
        s = session_status(b24=0x41, b100=0x02)
        self.assertEqual((s.pre_wash, s.anti_crease, s.cold_wash), (False, True, True))
        s = session_status(b24=0x05)   # Extra Rinse held 3 s: sound off, not an option
        self.assertEqual((s.pre_wash, s.anti_crease, s.cold_wash, s.steam),
                         (False, False, False, False))

    def test_idle_phase_variants(self):
        for raw in (0x23, 0x24, 0x25, 0x28):
            self.assertEqual(session_status(b18=raw).phase, "idle", hex(raw))
        self.assertEqual(session_status(b18=0x23, b25=0x03).phase, "delayed")
        self.assertEqual(session_status(b18=0x42).phase, "unknown")   # start: not a known step


if __name__ == "__main__":
    unittest.main()
