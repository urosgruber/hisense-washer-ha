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
        self.assertEqual(RUNNING, {"washing", "rinsing", "spinning"})

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


if __name__ == "__main__":
    unittest.main()
