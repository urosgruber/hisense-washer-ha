"""The TLS listener the washer connects to.

Cloud off: answer the login (101/102/103) with recorded replies, echo the
heartbeat (902), decode the status (901). Nothing leaves the house.

Cloud on: pipe every frame to the real cloud and back, unchanged. Decode the
status on the way, and record the cloud's login replies for cloud-off use.
The mode is fixed per connection. A mode change drops the washer, and the
washer logs in again under the new mode.
"""
from __future__ import annotations

import asyncio
import logging
import ssl
import time
from typing import Callable

from .cloud import CloudControl, resolve_cloud
from .config import Config, parse_bind
from .cycle import CycleTracker
from .frame import HEARTBEAT, Frame, parse_frame, split_frames
from .state import WasherState
from .status import status_from_frame
from .store import Cycle, Store

log = logging.getLogger(__name__)

LOGIN_IDS = (101, 102, 103)
READ_SIZE = 4096
EXPIRY_CHECK_S = 30


class DeviceServer:
    def __init__(self, config: Config, store: Store, state: WasherState, tracker: CycleTracker,
                 cloud: CloudControl, on_change: Callable[[], None],
                 on_cycle: Callable[[Cycle], None]):
        self.config = config
        self.store = store
        self.state = state
        self.tracker = tracker
        self.cloud = cloud
        self.on_change = on_change
        self.on_cycle = on_cycle
        self.server: asyncio.base_events.Server | None = None
        self.current: asyncio.StreamWriter | None = None
        self.port: int | None = None
        self._expiry_task: asyncio.Task | None = None
        cloud.on_change = self.drop_washer

    @property
    def login_ready(self) -> bool:
        return self.store.load_login() is not None

    def _ssl_context(self) -> ssl.SSLContext:
        cert, key = self.store.tls_paths()
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(cert, key)
        return ctx

    async def start(self) -> None:
        host, port = parse_bind(self.config.device_bind)
        self.server = await asyncio.start_server(self._handle, host, port, ssl=self._ssl_context())
        self.port = self.server.sockets[0].getsockname()[1]
        log.info("Washer listener on %s:%s", host, self.port)
        self._expiry_task = asyncio.create_task(self._expiry_loop())

    async def stop(self) -> None:
        if self._expiry_task:
            self._expiry_task.cancel()
        await self.drop_washer()
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    async def drop_washer(self) -> None:
        """Close the washer connection. The washer logs in again within a minute."""
        writer = self.current
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, ssl.SSLError):
                pass

    async def check_cloud_expiry(self) -> None:
        if self.cloud.expired():
            log.info("The cloud time limit ended: cloud off")
            self.cloud.turn_off()
            await self.cloud.notify()

    async def _expiry_loop(self) -> None:
        while True:
            await asyncio.sleep(EXPIRY_CHECK_S)
            await self.check_cloud_expiry()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        if self.current is not None:
            log.info("New washer connection from %s replaces the old one", peer)
            await self.drop_washer()
        self.current = writer
        self.state.on_connect(time.time())
        self.on_change()
        log.info("Washer connected from %s (cloud %s)", peer, self.cloud.mode)
        try:
            if self.cloud.mode == "on":
                await self._serve_cloud(reader, writer)
            else:
                await self._serve_local(reader, writer)
        except (ConnectionError, ssl.SSLError, asyncio.IncompleteReadError) as e:
            log.info("Washer connection error: %s", e)
        finally:
            if self.current is writer:
                self.current = None
                self.state.on_disconnect(time.time())
                self.on_change()
                log.info("Washer disconnected")
            writer.close()

    async def _serve_local(self, reader, writer) -> None:
        buf = b""
        while True:
            data = await reader.read(READ_SIZE)
            if not data:
                return
            frames, buf = split_frames(buf + data)
            for raw in frames:
                frame = parse_frame(raw)
                self.state.on_frame(time.time())
                if not await self._answer_locally(frame, writer):
                    return

    async def _serve_cloud(self, reader, writer) -> None:
        address = await resolve_cloud(self.config.cloud_host, self.config.cloud_resolver,
                                      self.config.cloud_address)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # the cloud certificate does not match; see the design
        log.info("Cloud on: forwarding to %s:%s", address, self.config.cloud_port)
        up_reader, up_writer = await asyncio.open_connection(
            address, self.config.cloud_port, ssl=ctx, server_hostname="")
        recorded: dict[int, bytes] = {}

        async def washer_to_cloud():
            buf = b""
            while data := await reader.read(READ_SIZE):
                up_writer.write(data)
                await up_writer.drain()
                frames, buf = split_frames(buf + data)
                for raw in frames:
                    self.state.on_frame(time.time())
                    frame = parse_frame(raw)
                    if frame.id == 901:
                        self.handle_status(frame)

        async def cloud_to_washer():
            buf = b""
            while data := await up_reader.read(READ_SIZE):
                writer.write(data)
                await writer.drain()
                frames, buf = split_frames(buf + data)
                for raw in frames:
                    fid = parse_frame(raw).id
                    if fid in LOGIN_IDS:
                        recorded[fid] = raw
                        if len(recorded) == len(LOGIN_IDS):
                            self.store.save_login(dict(recorded), time.time())
                            log.info("Recorded the cloud login replies")
                            recorded.clear()

        tasks = [asyncio.create_task(washer_to_cloud()), asyncio.create_task(cloud_to_washer())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()
            up_writer.close()

    async def _answer_locally(self, frame: Frame, writer) -> bool:
        """Answer one frame. Return False to close the connection."""
        if frame.id in LOGIN_IDS:
            replies = self.store.load_login()
            if not replies or frame.id not in replies:
                log.warning("No recorded login replies: the washer needs one cloud login. "
                            "Turn the cloud on once on the admin page.")
                return False
            writer.write(replies[frame.id])
            await writer.drain()
            log.debug("Login %s answered from the recording", frame.id)
        elif frame.id == 902:
            writer.write(HEARTBEAT)
            await writer.drain()
        elif frame.id == 901:
            self.handle_status(frame)
        else:
            log.debug("Ignored frame id %s", frame.id)
        return True

    def handle_status(self, frame: Frame) -> None:
        status = status_from_frame(frame)
        if status is None:
            return
        now = time.time()
        self.state.on_status(status, now)
        closed = self.tracker.update(status, now)
        if closed is not None:
            self.state.last_cycle = closed
            self.on_cycle(closed)
        self.on_change()
        log.debug("Status: phase %s, %s min left", status.phase, status.minutes_left)
