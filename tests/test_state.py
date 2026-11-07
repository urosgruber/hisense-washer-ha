from washer.status import Status
import unittest

from tests.helpers import make_status
from washer.cycle import Cycle
from washer.state import GRACE_S, LIVENESS_S, RAW_HISTORY, WasherState


class WasherStateTest(unittest.TestCase):
    def running(self, now=1000.0, minutes=37):
        st = WasherState()
        st.on_connect(now)
        st.on_status(make_status("washing", minutes=minutes, energy=0.2, water=8.0), now)
        return st

    def test_end_time_running(self):
        v = self.running().view(1000.0)
        self.assertEqual(v["phase"], "washing")
        self.assertEqual(v["minutes_left"], 37)
        self.assertEqual(v["end_time"], 1000.0 + 2220)
        self.assertTrue(v["connected"])
        self.assertFalse(v["stale"])

    def test_end_time_idle_none(self):
        st = WasherState()
        st.on_connect(0)
        st.on_status(make_status("idle", minutes=218), 0)
        self.assertIsNone(st.view(0)["end_time"])

    def test_grace_period(self):
        st = self.running(now=0.0)
        st.on_disconnect(0.0)
        v = st.view(GRACE_S - 1)
        self.assertEqual(v["phase"], "washing")
        self.assertTrue(v["stale"])
        self.assertFalse(v["connected"])
        v = st.view(GRACE_S + 1)
        self.assertEqual(v["phase"], "off")
        self.assertIsNone(v["end_time"])
        self.assertIsNone(v["minutes_left"])

    def test_silent_connection_is_not_connected(self):
        st = self.running(now=0.0)
        v = st.view(LIVENESS_S + 1)
        self.assertFalse(v["connected"])
        self.assertTrue(v["stale"])

    def test_no_status_yet(self):
        v = WasherState().view(0)
        self.assertEqual(v["phase"], "off")
        self.assertFalse(v["connected"])

    def test_last_cycle_in_view(self):
        st = WasherState()
        st.last_cycle = Cycle(started=0, ended=3600, energy_kwh=0.45, water_l=54.76,
                              program_raw=26, confirmed=True)
        v = st.view(4000)
        self.assertEqual((v["last_cycle_end"], v["last_cycle_energy_kwh"], v["last_cycle_water_l"]),
                         (3600, 0.45, 54.76))


class RawHistoryTest(unittest.TestCase):
    def status(self, *changes):
        raw = bytearray([1] * 115)
        raw[18] = 0x24
        for i, v in changes:
            raw[i] = v
        return Status.from_bytes(bytes(raw))

    def test_keeps_distinct_snapshots(self):
        st = WasherState()
        st.on_status(self.status(), 1.0)
        st.on_status(self.status(), 2.0)          # same bytes: not kept again
        st.on_status(self.status((20, 9)), 3.0)
        self.assertEqual([t for t, _ in st.raw_history], [1.0, 3.0])

    def test_history_holds_a_long_test(self):
        self.assertGreaterEqual(RAW_HISTORY, 200)

    def test_history_is_bounded(self):
        st = WasherState()
        for i in range(RAW_HISTORY + 10):
            st.on_status(self.status((20, i % 250 + 2)), float(i))
        self.assertEqual(len(st.raw_history), RAW_HISTORY)
        self.assertEqual(st.raw_history[-1][0], float(RAW_HISTORY + 9))



class OptionsViewTest(unittest.TestCase):
    def test_view_has_program_and_options(self):
        from tests.test_status import session_status
        st = WasherState()
        st.on_connect(100.0)
        st.on_status(session_status(b20=0x09, b107=0x4b, b24=0x81), 100.0)
        v = st.view(100.0)
        self.assertEqual((v["program"], v["temperature_c"], v["quicker"], v["steam"]),
                         ("Synthetics", 40, 2, True))

    def test_delayed_has_end_time(self):
        from tests.test_status import session_status
        st = WasherState()
        st.on_connect(100.0)
        st.on_status(session_status(b18=0x2c, b25=0x06, b30=0x02, b31=0x2d), 100.0)
        self.assertEqual(st.view(100.0)["end_time"], 100.0 + 300 * 60)


if __name__ == "__main__":
    unittest.main()
