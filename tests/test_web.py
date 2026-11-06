import tempfile
import time
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from tests.helpers import make_status
from tests.test_device import LOGIN
from washer.cloud import CloudControl
from washer.state import WasherState
from washer.store import Cycle, Store
from washer.web import make_app


class FakeDevice:
    def __init__(self, store):
        self.store = store

    @property
    def login_ready(self):
        return self.store.load_login() is not None


class WebTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))
        self.store.save_login(LOGIN, 1793985000.0)
        self.store.append_cycle(Cycle(1793985451.0, 1793990734.0, 0.45, 54.76, 26, True))
        self.state = WasherState()
        now = time.time()
        self.state.on_connect(now)
        self.state.on_status(make_status("washing", minutes=37, energy=0.2, water=7.84), now)
        self.cloud = CloudControl(max_hours=2)
        self.dropped = 0

        async def drop():
            self.dropped += 1

        self.cloud.on_change = drop
        self.changes = 0

        def changed():
            self.changes += 1

        app = make_app(self.state, self.cloud, self.store, FakeDevice(self.store), on_change=changed)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def test_index_shows_phase(self):
        r = await self.client.get("/")
        text = await r.text()
        self.assertEqual(r.status, 200)
        self.assertIn("Washing", text)
        self.assertIn("0x44", text)
        self.assertIn("Login recorded: yes", text)
        self.assertIn("54.76", text)  # the last cycle

    async def test_cloud_on_off(self):
        r = await self.client.post("/cloud/on", data={"hours": "1"}, allow_redirects=False)
        self.assertEqual(r.status, 303)
        self.assertEqual(self.cloud.mode, "on")
        self.assertEqual(self.dropped, 1)
        self.assertGreater(self.changes, 0)
        await self.client.post("/cloud/off", allow_redirects=False)
        self.assertEqual(self.cloud.mode, "off")
        self.assertEqual(self.dropped, 2)

    async def test_cloud_on_clamped(self):
        await self.client.post("/cloud/on", data={"hours": "99"}, allow_redirects=False)
        self.assertLessEqual(self.cloud.until - self.cloud.clock(), 2 * 3600 + 1)

    async def test_cloud_on_bad_hours(self):
        r = await self.client.post("/cloud/on", data={"hours": "abc"}, allow_redirects=False)
        self.assertEqual(r.status, 400)
        self.assertEqual(self.cloud.mode, "off")

    async def test_cross_site_post_refused(self):
        r = await self.client.post("/cloud/on", data={"hours": "1"}, allow_redirects=False,
                                   headers={"Origin": "https://evil.example"})
        self.assertEqual(r.status, 403)
        self.assertEqual(self.cloud.mode, "off")

    async def test_ingress_base_path(self):
        r = await self.client.get("/", headers={"X-Ingress-Path": "/api/hassio_ingress/abc"})
        self.assertIn('<base href="/api/hassio_ingress/abc/">', await r.text())
        r = await self.client.post("/cloud/off", allow_redirects=False,
                                   headers={"X-Ingress-Path": "/api/hassio_ingress/abc"})
        self.assertEqual(r.headers["Location"], "/api/hassio_ingress/abc/")

    async def test_api_status(self):
        r = await self.client.get("/api/status")
        data = await r.json()
        self.assertEqual(data["phase"], "washing")
        self.assertEqual(data["cloud"], "off")
        self.assertEqual(data["cycles"], 0)

    async def test_no_secrets_on_page(self):
        text = await (await self.client.get("/")).text()
        text += await (await self.client.get("/api/status")).text()
        self.assertNotIn("0" * 32, text)  # the fake token
        self.assertNotIn("token", text.lower())
        self.assertNotIn("AAAA", text)  # the fake key


if __name__ == "__main__":
    unittest.main()
