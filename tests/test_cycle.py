import tempfile
import unittest
from pathlib import Path

from tests.helpers import fixture_statuses, make_status
from washer.cycle import CycleTracker
from washer.store import Store


class CycleTrackerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))
        self.tracker = CycleTracker(self.store)
        self.t = 0.0

    def tearDown(self):
        self.tmp.cleanup()

    def feed(self, *statuses, tracker=None):
        closed = []
        for s in statuses:
            self.t += 60
            c = (tracker or self.tracker).update(s, self.t)
            if c:
                closed.append(c)
        return closed

    def test_full_wash_fixture(self):
        closed = [c for t, s in fixture_statuses("wash-2026-11-06.jsonl")
                  if (c := self.tracker.update(s, t))]
        self.assertEqual(len(closed), 1)
        c = closed[0]
        self.assertEqual(c.started, 1793985451.120919)
        self.assertEqual(c.ended, 1793990734.748638)
        self.assertEqual(c.energy_kwh, 0.45)
        self.assertEqual(c.water_l, 54.76)
        self.assertIs(c.confirmed, True)
        totals = self.store.load_totals()
        self.assertEqual((totals.energy_kwh, totals.water_l, totals.cycles), (0.45, 54.76, 1))
        self.assertEqual(len(self.store.recent_cycles(10)), 1)

    def test_unknown_phase_mid_cycle(self):
        closed = self.feed(make_status("idle"), make_status("washing"), make_status("unknown"),
                           make_status("washing"), make_status("done", energy=0.4, water=50))
        self.assertEqual(len(closed), 1)

    def test_missed_done(self):
        closed = self.feed(make_status("washing", energy=0.30, water=20), make_status("off"))
        self.assertEqual(len(closed), 1)
        self.assertIs(closed[0].confirmed, False)
        self.assertEqual(self.store.load_totals().energy_kwh, 0.30)

    def test_off_after_reset_keeps_last_values(self):
        # Energy and water reset to 0 in standby. The cycle keeps the last real values.
        closed = self.feed(make_status("spinning", energy=0.45, water=54.76), make_status("off"))
        self.assertEqual((closed[0].energy_kwh, closed[0].water_l), (0.45, 54.76))

    def test_done_twice(self):
        closed = self.feed(make_status("washing"), make_status("done", energy=0.4),
                           make_status("done", energy=0.4))
        self.assertEqual(len(closed), 1)
        self.assertEqual(self.store.load_totals().cycles, 1)

    def test_delay_then_wash(self):
        closed = self.feed(make_status("delayed"), make_status("washing"), make_status("done"))
        self.assertEqual(len(closed), 1)
        self.assertIs(closed[0].confirmed, True)

    def test_no_cycle_without_running(self):
        self.assertEqual(self.feed(make_status("idle"), make_status("done"), make_status("off")), [])

    def test_reconnect_same_cycle(self):
        self.feed(make_status("washing", energy=0.1))
        second = CycleTracker(self.store)  # a reconnect or an app restart
        closed = self.feed(make_status("washing", energy=0.2), make_status("done", energy=0.3),
                           tracker=second)
        self.assertEqual(len(closed), 1)
        self.assertEqual(len(self.store.recent_cycles(10)), 1)

    def test_tracker_restores_open_cycle(self):
        self.feed(make_status("washing"))
        started = self.t
        second = CycleTracker(self.store)
        closed = self.feed(make_status("done", energy=0.3), tracker=second)
        self.assertEqual(closed[0].started, started)
        self.assertIsNone(self.store.load_open_cycle())


    def crash_then_done_again(self, method):
        """The app dies inside the close (in `method`), restarts, and sees "done" again."""
        self.feed(make_status("washing", energy=0.3, water=40.0))
        real = getattr(self.store, method)

        def crash(*args):
            if method != "save_open_cycle" or args[0] is None:
                raise OSError("power cut")
            return real(*args)

        setattr(self.store, method, crash)
        with self.assertRaises(OSError):
            self.feed(make_status("done", energy=0.45, water=54.76))
        setattr(self.store, method, real)
        restarted = CycleTracker(self.store)
        self.feed(make_status("done", energy=0.45, water=54.76), tracker=restarted)
        totals = self.store.load_totals()
        self.assertEqual((totals.energy_kwh, totals.water_l, totals.cycles), (0.45, 54.76, 1))
        self.assertEqual(len(self.store.recent_cycles(10)), 1)
        self.assertIsNone(restarted.open)

    def test_crash_after_totals_counts_once(self):
        self.crash_then_done_again("append_cycle")

    def test_crash_while_saving_totals_counts_once(self):
        self.crash_then_done_again("save_totals")

    def test_crash_before_open_cycle_removed_counts_once(self):
        self.crash_then_done_again("save_open_cycle")

    def test_two_cycles_both_count(self):
        self.feed(make_status("washing", energy=0.2, water=10.0), make_status("done", energy=0.2, water=10.0),
                  make_status("off"), make_status("washing", energy=0.3, water=20.0),
                  make_status("done", energy=0.3, water=20.0))
        self.assertEqual(self.store.load_totals().cycles, 2)


if __name__ == "__main__":
    unittest.main()
