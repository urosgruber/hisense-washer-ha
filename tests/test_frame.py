import unittest

from washer.frame import HEARTBEAT, parse_frame, split_frames


class SplitFramesTest(unittest.TestCase):
    def test_split_frames_two_in_one(self):
        frames, rest = split_frames(HEARTBEAT + HEARTBEAT[:5])
        self.assertEqual(frames, [HEARTBEAT])
        self.assertEqual(rest, HEARTBEAT[:5])

    def test_split_frames_partial(self):
        self.assertEqual(split_frames(b'HS{"id"'), ([], b'HS{"id"'))

    def test_split_frames_many(self):
        frames, rest = split_frames(HEARTBEAT * 3)
        self.assertEqual(frames, [HEARTBEAT] * 3)
        self.assertEqual(rest, b"")


class ParseFrameTest(unittest.TestCase):
    def test_parse_signed(self):
        raw = b'HS{"id":101,"token":"t","err":0}' + b"a" * 64 + b"\r\n"
        f = parse_frame(raw)
        self.assertEqual(f.id, 101)
        self.assertEqual(f.body["token"], "t")
        self.assertEqual(f.raw, raw)

    def test_parse_heartbeat(self):
        self.assertEqual(parse_frame(HEARTBEAT).id, 902)

    def test_parse_garbage(self):
        f = parse_frame(b"HSxx\r\n")
        self.assertIsNone(f.id)
        self.assertIsNone(f.body)


if __name__ == "__main__":
    unittest.main()
