import asyncio
import json
import ssl
import tempfile
import time
import unittest
from pathlib import Path

from tests.helpers import FIXTURES
from washer.cloud import CloudControl
from washer.config import Config
from washer.cycle import CycleTracker
from washer.device import MAX_BUFFER, DeviceServer
from washer.frame import HEARTBEAT
from washer.state import WasherState
from washer.store import Store

SIG = b"0" * 64
FAKE_TOKEN = "0" * 32
FAKE_WID = "fake-washer"
LOGIN = {
    101: b'HS{"id":101,"token":"' + FAKE_TOKEN.encode() + b'","err":0}' + SIG + b"\r\n",
    102: b'HS{"id":102,"key":"AAAA","err":0}' + SIG + b"\r\n",
    103: b'HS{"id":103,"args":[{"hb":180,"rp":360,"retry":60}],"err":0}' + SIG + b"\r\n",
}


def hello(wid=FAKE_WID):
    return b'HS{"id":101,"wid":"%s","ver":"x","ProtVer":"215"}' % wid.encode() + SIG + b"\r\n"


HELLO = hello()


def washer_frame(fid):
    return b'HS{"id":%d,"token":"%s"}' % (fid, FAKE_TOKEN.encode()) + SIG + b"\r\n"


def status_frame(result):
    body = {"id": 901, "token": FAKE_TOKEN, "err": 0,
            "status": [{"msgtype": 30, "msgsubtype": 0, "result": "gAAAAhUAAAA="},
                       {"msgtype": 102, "msgsubtype": 0, "result": result}]}
    return b"HS" + json.dumps(body).encode() + SIG + b"\r\n"


def client_ctx():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class DeviceServerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))
        self.store.tls_paths()
        self.state = WasherState()
        self.cycles = []
        self.changes = 0
        self.config = Config(data_dir=Path(self.tmp.name), device_bind="127.0.0.1:0")
        self.server = None

    async def asyncTearDown(self):
        if self.server:
            await self.server.stop()
        self.tmp.cleanup()

    async def start(self, login=True):
        if login:
            self.store.save_login(LOGIN, 1.0, wid=FAKE_WID)

        def changed():
            self.changes += 1

        self.server = DeviceServer(self.config, self.store, self.state, CycleTracker(self.store),
                                   CloudControl(max_hours=2), on_change=changed,
                                   on_cycle=self.cycles.append)
        await self.server.start()
        return await self.connect()

    async def connect(self):
        return await asyncio.open_connection("127.0.0.1", self.server.port, ssl=client_ctx())

    async def read_frame(self, r):
        return await asyncio.wait_for(r.readuntil(b"\r\n"), 2)

    async def login(self, r, w):
        w.write(HELLO)
        await w.drain()
        self.assertEqual(await self.read_frame(r), LOGIN[101])

    async def closed(self, r):
        return await asyncio.wait_for(r.read(), 3) == b""

    async def test_login_replay(self):
        r, w = await self.start()
        for fid, frame in ((101, HELLO), (102, washer_frame(102)), (103, washer_frame(103))):
            w.write(frame)
            await w.drain()
            self.assertEqual(await self.read_frame(r), LOGIN[fid])
        self.assertTrue(self.state.connected)
        w.close()

    async def test_heartbeat_echo(self):
        r, w = await self.start()
        await self.login(r, w)
        w.write(HEARTBEAT)
        await w.drain()
        self.assertEqual(await self.read_frame(r), HEARTBEAT)
        w.close()

    async def test_two_frames_in_one_write(self):
        r, w = await self.start()
        await self.login(r, w)
        w.write(HEARTBEAT * 2)
        await w.drain()
        self.assertEqual(await self.read_frame(r), HEARTBEAT)
        self.assertEqual(await self.read_frame(r), HEARTBEAT)
        w.close()

    async def test_frame_split_across_writes(self):
        r, w = await self.start()
        await self.login(r, w)
        w.write(HEARTBEAT[:6])
        await w.drain()
        await asyncio.sleep(0.05)
        w.write(HEARTBEAT[6:])
        await w.drain()
        self.assertEqual(await self.read_frame(r), HEARTBEAT)
        w.close()

    async def test_status_updates_state(self):
        r, w = await self.start()
        await self.login(r, w)
        line = json.loads((FIXTURES / "wash-2026-11-06.jsonl").read_text().splitlines()[-3])
        w.write(status_frame(line["result"]) + HEARTBEAT)
        await w.drain()
        await self.read_frame(r)  # the heartbeat echo: the status before it is handled
        self.assertIsNotNone(self.state.status)
        self.assertGreater(self.changes, 0)
        w.close()

    async def test_no_login_closes(self):
        r, w = await self.start(login=False)
        self.assertFalse(self.server.login_ready)
        w.write(HELLO)
        await w.drain()
        self.assertTrue(await self.closed(r))
        w.close()

    async def test_status_before_hello_is_ignored(self):
        r, w = await self.start()
        line = json.loads((FIXTURES / "wash-2026-11-06.jsonl").read_text().splitlines()[-3])
        w.write(status_frame(line["result"]))
        await w.drain()
        await self.login(r, w)
        self.assertIsNone(self.state.status)
        w.close()

    async def test_wrong_washer_id_closes(self):
        r, w = await self.start()
        w.write(hello("another-washer"))
        await w.drain()
        self.assertTrue(await self.closed(r))
        self.assertFalse(self.state.connected)
        w.close()

    async def test_peer_not_allowed_closes(self):
        self.config.washer_ip = "203.0.113.9"
        r, w = await self.start()
        self.assertTrue(await self.closed(r))
        w.close()

    async def test_endless_frame_closes(self):
        r, w = await self.start()
        w.write(b"HS" + b"x" * (MAX_BUFFER + 10))
        await w.drain()
        self.assertTrue(await self.closed(r))
        w.close()

    async def test_new_connection_replaces_old_after_hello(self):
        r1, w1 = await self.start()
        await self.login(r1, w1)
        r2, w2 = await self.connect()
        await self.login(r2, w2)
        self.assertTrue(await self.closed(r1))
        w2.write(HEARTBEAT)
        await w2.drain()
        self.assertEqual(await self.read_frame(r2), HEARTBEAT)
        w1.close()
        w2.close()

    async def test_connection_without_hello_keeps_old(self):
        r1, w1 = await self.start()
        await self.login(r1, w1)
        r2, w2 = await self.connect()  # a network scanner: connects, says nothing
        await asyncio.sleep(0.1)
        w1.write(HEARTBEAT)
        await w1.drain()
        self.assertEqual(await self.read_frame(r1), HEARTBEAT)
        w1.close()
        w2.close()

    async def test_drop_silent_peer_is_quick(self):
        r, w = await self.start()
        await self.login(r, w)
        w.transport.pause_reading()  # the peer never answers the TLS close
        started = time.monotonic()
        await asyncio.wait_for(self.server.drop_washer(), 10)
        self.assertLess(time.monotonic() - started, 5)
        w.close()

    async def test_disconnect_marks_state(self):
        r, w = await self.start()
        await self.login(r, w)
        w.close()
        await asyncio.sleep(0.1)
        self.assertFalse(self.state.connected)


if __name__ == "__main__":
    unittest.main()
