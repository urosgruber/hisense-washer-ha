import unittest

from tests.helpers import make_status
from washer.cycle import Cycle
from washer.state import GRACE_S, LIVENESS_S, WasherState


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


if __name__ == "__main__":
    unittest.main()
