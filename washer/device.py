"""The TLS listener the washer connects to.

Cloud off: answer the login (101/102/103) with recorded replies, echo the
heartbeat (902), decode the status (901). Nothing leaves the house.

Cloud on: pipe every frame to the real cloud and back, unchanged. Decode the
status on the way, and record the cloud's login replies for cloud-off use.
If the cloud cannot be reached, answer locally instead.

The mode is fixed per connection. A mode change drops the washer, and the
washer logs in again under the new mode.

The port is open to the LAN, so a connection counts only after a valid hello:
the right peer address (option washer_ip) and the washer id recorded at the
cloud login. Until then it cannot read the login replies, send a status, or
push the real washer off.
"""
from __future__ import annotations

import asyncio
import logging
import ssl
import struct
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
MAX_BUFFER = 16384  # a status frame is about 450 bytes
EXPIRY_CHECK_S = 30
CLOUD_CONNECT_TIMEOUT_S = 10
CLOUD_ERRORS = (OSError, ValueError, struct.error, IndexError, asyncio.TimeoutError)


class _Closed(Exception):
    """Close this washer connection."""


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
        self.cloud_error: str | None = None
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
        loop = asyncio.get_running_loop()
        ctx = await loop.run_in_executor(None, self._ssl_context)  # may run openssl once
        self.server = await asyncio.start_server(self._handle, host, port, ssl=ctx)
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
        """Close the washer connection now. The washer logs in again within a minute.

        Abort, do not wait for the TLS close: a washer that left the Wi-Fi never
        answers it."""
        writer = self.current
        if writer is not None:
            _abort(writer)

    async def check_cloud_expiry(self) -> None:
        if self.cloud.expired():
            log.info("The cloud time limit ended: cloud off")
            self.cloud.turn_off()
            try:
                await self.cloud.notify()
            except Exception:
                log.exception("Could not drop the washer after the cloud time limit")

    async def _expiry_loop(self) -> None:
        while True:
            await asyncio.sleep(EXPIRY_CHECK_S)
            try:
                await self.check_cloud_expiry()
            except Exception:  # the time limit is a security rule: never stop the loop
                log.exception("Cloud expiry check failed")

    # -- connections ------------------------------------------------------

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        peer_ip = peer[0] if peer else None
        if self.config.washer_ip and peer_ip != self.config.washer_ip:
            log.warning("Refused a connection from %s: not the washer", peer_ip)
            _abort(writer)
            return
        try:
            upstream = None
            if self.cloud.mode == "on":
                upstream = await self._open_cloud()
            if upstream:
                await self._serve_cloud(reader, writer, *upstream)
            else:
                await self._serve_local(reader, writer)
        except _Closed:
            pass
        except (ConnectionError, ssl.SSLError, asyncio.IncompleteReadError, TimeoutError) as e:
            log.info("Washer connection error: %s", e)
        except Exception:
            log.exception("Washer connection failed")
        finally:
            _abort(writer)
            if self.current is writer:
                self.current = None
                self.state.on_disconnect(time.time())
                self.on_change()
                log.info("Washer disconnected")

    def _accept(self, writer, wid: str | None) -> None:
        """A valid hello: this connection is now the washer."""
        stored = self.store.load_wid()
        if stored and wid != stored:
            log.warning("Refused a login with an unknown washer id")
            raise _Closed()
        if self.current is not None and self.current is not writer:
            log.info("A new washer login replaces the old connection")
            _abort(self.current)
        if self.current is not writer:
            self.current = writer
            self.state.on_connect(time.time())
            self.on_change()
            log.info("Washer logged in (cloud %s)", self.cloud.mode)

    @staticmethod
    async def _frames(reader):
        """Yield raw frames. Close on a frame that never ends."""
        buf = b""
        while data := await reader.read(READ_SIZE):
            frames, buf = split_frames(buf + data)
            if len(buf) > MAX_BUFFER:
                log.warning("Closed a connection: frame too long")
                raise _Closed()
            for raw in frames:
                yield raw

    async def _serve_local(self, reader, writer) -> None:
        async for raw in self._frames(reader):
            frame = parse_frame(raw)
            if self.current is not writer:
                if frame.id != 101:
                    continue  # nothing counts before a valid hello
                replies = self.store.load_login()
                if not replies or 101 not in replies:
                    log.warning("No recorded login replies: the washer needs one cloud login. "
                                "Turn the cloud on once on the admin page.")
                    raise _Closed()
                self._accept(writer, (frame.body or {}).get("wid"))
            self.state.on_frame(time.time())
            await self._answer_locally(frame, writer)

    async def _answer_locally(self, frame: Frame, writer) -> None:
        if frame.id in LOGIN_IDS:
            replies = self.store.load_login() or {}
            if frame.id not in replies:
                raise _Closed()
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

    async def _open_cloud(self):
        """Connect to the real cloud, or return None (then we answer locally)."""
        try:
            address = await asyncio.wait_for(
                resolve_cloud(self.config.cloud_host, self.config.cloud_resolver,
                              self.config.cloud_address), CLOUD_CONNECT_TIMEOUT_S)
        except CLOUD_ERRORS as e:
            return self._cloud_failed(f"DNS lookup of {self.config.cloud_host} via "
                                      f"{self.config.cloud_resolver} failed: {e or type(e).__name__}")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # the cloud certificate does not match; see the design
        try:
            upstream = await asyncio.wait_for(
                asyncio.open_connection(address, self.config.cloud_port, ssl=ctx,
                                        server_hostname=""),
                CLOUD_CONNECT_TIMEOUT_S)
        except CLOUD_ERRORS as e:
            return self._cloud_failed(f"Cloud {address}:{self.config.cloud_port} unreachable: "
                                      f"{e or type(e).__name__}")
        if self.cloud_error:
            log.info("Cloud reachable again")
        self.cloud_error = None
        log.info("Cloud on: forwarding to %s:%s", address, self.config.cloud_port)
        return upstream

    def _cloud_failed(self, message: str):
        if message != self.cloud_error:
            log.warning("%s. Answering the washer locally.", message)
        self.cloud_error = message
        return None

    async def _serve_cloud(self, reader, writer, up_reader, up_writer) -> None:
        recorded: dict[int, bytes] = {}
        seen_wid: list[str | None] = [None]

        async def washer_to_cloud():
            async for raw in self._frames(reader):
                frame = parse_frame(raw)
                if frame.id == 101 and self.current is not writer:
                    seen_wid[0] = (frame.body or {}).get("wid")
                    if self.store.load_wid():
                        self._accept(writer, seen_wid[0])
                if self.current is writer:
                    self.state.on_frame(time.time())
                    if frame.id == 901:
                        self.handle_status(frame)
                up_writer.write(raw)
                await up_writer.drain()

        async def cloud_to_washer():
            async for raw in self._frames(up_reader):
                frame = parse_frame(raw)
                if frame.id in LOGIN_IDS:
                    if (frame.body or {}).get("err") == 0:
                        recorded[frame.id] = raw
                    else:
                        log.warning("The cloud refused login step %s", frame.id)
                        recorded.clear()
                    if len(recorded) == len(LOGIN_IDS):
                        self.store.save_login(dict(recorded), time.time(), wid=seen_wid[0])
                        log.info("Recorded the cloud login replies")
                        recorded.clear()
                        if self.current is not writer:
                            self._accept(writer, seen_wid[0])
                writer.write(raw)
                await writer.drain()

        tasks = [asyncio.create_task(washer_to_cloud()), asyncio.create_task(cloud_to_washer())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                if not t.cancelled() and t.exception() and not isinstance(t.exception(), _Closed):
                    log.info("Cloud pipe ended: %s", t.exception())
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            _abort(up_writer)

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


def _abort(writer: asyncio.StreamWriter) -> None:
    try:
        writer.transport.abort()
    except Exception:
        pass
