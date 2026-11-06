import asyncio
import ssl
import tempfile
import unittest
from pathlib import Path

from tests.test_device import HELLO, LOGIN, SIG, client_ctx, washer_frame
from washer.cloud import CloudControl, build_dns_query, parse_dns_answer, resolve_cloud
from washer.config import Config
from washer.cycle import CycleTracker
from washer.device import DeviceServer
from washer.frame import HEARTBEAT, split_frames
from washer.state import WasherState
from washer.store import Store

CLOUD_LOGIN = {i: f.replace(b'"err":0', b'"err":0,"cloud":1') for i, f in LOGIN.items()}


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class CloudControlTest(unittest.IsolatedAsyncioTestCase):
    async def test_cloud_off_after_restart(self):
        self.assertEqual(CloudControl(max_hours=2).mode, "off")

    async def test_turn_on_clamped(self):
        clock = Clock()
        cloud = CloudControl(max_hours=2, clock=clock)
        cloud.turn_on(10)
        self.assertEqual(cloud.mode, "on")
        self.assertEqual(cloud.until, 1000.0 + 7200)

    async def test_turn_on_default_is_max(self):
        cloud = CloudControl(max_hours=1.5, clock=Clock())
        cloud.turn_on()
        self.assertEqual(cloud.until, 1000.0 + 5400)

    async def test_expiry(self):
        clock = Clock()
        cloud = CloudControl(max_hours=2, clock=clock)
        cloud.turn_on(1)
        self.assertFalse(cloud.expired())
        clock.t += 3601
        self.assertTrue(cloud.expired())

    async def test_turn_off(self):
        cloud = CloudControl(max_hours=2, clock=Clock())
        cloud.turn_on(1)
        cloud.turn_off()
        self.assertEqual(cloud.mode, "off")
        self.assertIsNone(cloud.until)

    async def test_notify_calls_hook(self):
        cloud = CloudControl(max_hours=2)
        calls = []

        async def hook():
            calls.append(1)

        cloud.on_change = hook
        await cloud.notify()
        self.assertEqual(calls, [1])

    async def test_info(self):
        cloud = CloudControl(max_hours=2, clock=Clock())
        self.assertEqual(cloud.info(login_ready=False),
                         {"mode": "off", "until": None, "login_ready": False})
        cloud.turn_on(1)
        self.assertEqual(cloud.info(login_ready=True),
                         {"mode": "on", "until": 4600.0, "login_ready": True})

    async def test_resolve_uses_address(self):
        self.assertEqual(await resolve_cloud("example.invalid", "203.0.113.1", "203.0.113.5"),
                         "203.0.113.5")


class DnsTest(unittest.TestCase):
    def test_query_and_answer(self):
        q = build_dns_query("wash.example.com", 0x1234)
        self.assertEqual(q[:2], b"\x12\x34")
        # An answer: the query, one A record that points back to the name.
        answer = bytearray(q)
        answer[2:4] = b"\x81\x80"  # response, no error
        answer[6:8] = b"\x00\x01"  # one answer
        answer += b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04" + bytes([203, 0, 113, 7])
        self.assertEqual(parse_dns_answer(bytes(answer), 0x1234), "203.0.113.7")

    def test_answer_wrong_id(self):
        q = build_dns_query("wash.example.com", 1)
        with self.assertRaises(ValueError):
            parse_dns_answer(q, 2)


class FakeCloud:
    """A TLS server that answers like the ConnectLife cloud."""

    def __init__(self, cert_dir: Path):
        self.received = []
        self.store = Store(cert_dir)

    async def start(self):
        cert, key = self.store.tls_paths()
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0, ssl=ctx)
        self.port = self.server.sockets[0].getsockname()[1]

    async def handle(self, reader, writer):
        buf = b""
        while data := await reader.read(4096):
            frames, buf = split_frames(buf + data)
            for raw in frames:
                self.received.append(raw)
                for fid, reply in CLOUD_LOGIN.items():
                    if raw.startswith(b'HS{"id":%d' % fid):
                        writer.write(reply)
                if raw == HEARTBEAT:
                    writer.write(HEARTBEAT)
            await writer.drain()

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()


class CloudModeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.cloud_server = FakeCloud(base / "cloud")
        await self.cloud_server.start()
        self.store = Store(base / "data")
        self.store.save_login(LOGIN, 1.0)
        config = Config(data_dir=base / "data", device_bind="127.0.0.1:0",
                        cloud_address="127.0.0.1", cloud_port=self.cloud_server.port)
        self.cloud = CloudControl(max_hours=2)
        self.server = DeviceServer(config, self.store, WasherState(), CycleTracker(self.store),
                                   self.cloud, on_change=lambda: None, on_cycle=lambda c: None)
        await self.server.start()

    async def asyncTearDown(self):
        await self.server.stop()
        await self.cloud_server.stop()
        self.tmp.cleanup()

    async def connect(self):
        return await asyncio.open_connection("127.0.0.1", self.server.port, ssl=client_ctx())

    async def read(self, r):
        return await asyncio.wait_for(r.readuntil(b"\r\n"), 3)

    async def test_cloud_pipe_records_login(self):
        self.cloud.turn_on(1)
        r, w = await self.connect()
        for fid, frame in ((101, HELLO), (102, washer_frame(102)), (103, washer_frame(103))):
            w.write(frame)
            await w.drain()
            self.assertEqual(await self.read(r), CLOUD_LOGIN[fid])
        await asyncio.sleep(0.1)
        self.assertEqual(self.store.load_login(), CLOUD_LOGIN)
        self.assertIn(HELLO, self.cloud_server.received)
        w.close()

    async def test_cloud_off_sends_nothing_upstream(self):
        r, w = await self.connect()
        w.write(HELLO)
        await w.drain()
        self.assertEqual(await self.read(r), LOGIN[101])
        self.assertEqual(self.cloud_server.received, [])
        w.close()

    async def test_mode_change_drops_washer(self):
        r, w = await self.connect()
        w.write(HEARTBEAT)
        await self.read(r)
        self.cloud.turn_on(1)
        await self.cloud.notify()
        self.assertEqual(await asyncio.wait_for(r.read(), 3), b"")
        w.close()

    async def test_expiry_turns_cloud_off(self):
        clock = Clock()
        self.cloud.clock = clock
        self.cloud.turn_on(1)
        clock.t += 3601
        await self.server.check_cloud_expiry()
        self.assertEqual(self.cloud.mode, "off")


if __name__ == "__main__":
    unittest.main()
