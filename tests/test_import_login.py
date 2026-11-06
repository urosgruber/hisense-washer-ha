import json
import tempfile
import unittest
from pathlib import Path

from scripts.import_login import import_login
from washer.store import Store


def rec(ev, direction=None, raw=b""):
    r = {"t": 1.0, "ev": ev}
    if ev == "msg":
        r.update(dir=direction, hex=raw.hex())
    return json.dumps(r)


class ImportLoginTest(unittest.TestCase):
    def test_takes_last_complete_login(self):
        old = {i: b'HS{"id":%d,"old":1}\r\n' % i for i in (101, 102, 103)}
        new = {i: b'HS{"id":%d,"new":1}\r\n' % i for i in (101, 102, 103)}
        lines = [rec("start")] + [rec("msg", "cloud->washer", old[i]) for i in old]
        lines += [rec("start")] + [rec("msg", "cloud->washer", new[i]) for i in new]
        lines += [rec("start"), rec("msg", "cloud->washer", new[101])]  # incomplete
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "messages.jsonl"
            src.write_text("\n".join(lines) + "\n")
            import_login(src, Path(d) / "data")
            self.assertEqual(Store(Path(d) / "data").load_login(), new)


if __name__ == "__main__":
    unittest.main()
