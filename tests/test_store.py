import tempfile
import unittest
from pathlib import Path

from washer.cycle import Cycle
from washer.store import Store, Totals


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.store = Store(self.dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_login_roundtrip(self):
        self.assertIsNone(self.store.load_login())
        self.assertIsNone(self.store.login_recorded_at())
        replies = {101: b'HS{"id":101}\r\n', 102: b'HS{"id":102}\r\n', 103: b'HS{"id":103}\r\n'}
        self.store.save_login(replies, 123.0)
        self.assertEqual(Store(self.dir).load_login(), replies)
        self.assertEqual(Store(self.dir).login_recorded_at(), 123.0)

    def test_totals_roundtrip(self):
        self.assertEqual(self.store.load_totals(), Totals())
        self.store.save_totals(Totals(1.5, 100.25, 3))
        self.assertEqual(Store(self.dir).load_totals(), Totals(1.5, 100.25, 3))

    def test_cycles_recent(self):
        for i in range(5):
            self.store.append_cycle(Cycle(i, i + 1, 0.1, 1.0, None, True))
        self.assertEqual([c.started for c in self.store.recent_cycles(2)], [3, 4])

    def test_open_cycle_roundtrip(self):
        c = Cycle(10, None, 0.2, 3.0, 26, None)
        self.store.save_open_cycle(c)
        self.assertEqual(Store(self.dir).load_open_cycle(), c)
        self.store.save_open_cycle(None)
        self.assertIsNone(self.store.load_open_cycle())

    def test_atomic_write_leaves_no_tmp(self):
        self.store.save_totals(Totals(1, 2, 3))
        self.assertEqual([p.name for p in self.dir.iterdir() if p.name.endswith(".tmp")], [])

    def test_tls_paths_created_once(self):
        cert, key = self.store.tls_paths()
        self.assertTrue(cert.exists() and key.exists())
        before = cert.read_bytes()
        self.assertEqual(self.store.tls_paths()[0].read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
