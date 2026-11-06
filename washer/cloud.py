"""Cloud mode: off by default. Only the admin page turns it on, for a limited time.

The state lives in memory only, so a restart always comes back with the cloud off.
"""
from __future__ import annotations

import asyncio
import random
import socket
import struct
import time
from typing import Awaitable, Callable

DNS_TIMEOUT_S = 3.0


class CloudControl:
    def __init__(self, max_hours: float, clock: Callable[[], float] = time.time):
        self.max_hours = max_hours
        self.clock = clock
        self.until: float | None = None
        self.on_change: Callable[[], Awaitable[None]] | None = None

    @property
    def mode(self) -> str:
        return "on" if self.until is not None else "off"

    def turn_on(self, hours: float | None = None) -> None:
        hours = self.max_hours if hours is None else max(0.0, min(float(hours), self.max_hours))
        self.until = self.clock() + hours * 3600

    def turn_off(self) -> None:
        self.until = None

    def expired(self) -> bool:
        return self.until is not None and self.clock() >= self.until

    def info(self, login_ready: bool) -> dict:
        return {"mode": self.mode, "until": self.until, "login_ready": login_ready}

    async def notify(self) -> None:
        """Tell the device server that the mode changed."""
        if self.on_change is not None:
            await self.on_change()


def build_dns_query(host: str, qid: int) -> bytes:
    header = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)  # recursion desired
    qname = b"".join(bytes([len(p)]) + p.encode() for p in host.split(".")) + b"\x00"
    return header + qname + struct.pack(">HH", 1, 1)  # type A, class IN


def _skip_name(msg: bytes, i: int) -> int:
    while True:
        length = msg[i]
        if length == 0:
            return i + 1
        if length & 0xC0 == 0xC0:
            return i + 2
        i += 1 + length


def parse_dns_answer(msg: bytes, qid: int) -> str:
    rid, flags, qd, an = struct.unpack(">HHHH", msg[:8])
    if rid != qid or not flags & 0x8000 or flags & 0x000F:
        raise ValueError("bad DNS answer")
    i = 12
    for _ in range(qd):
        i = _skip_name(msg, i) + 4
    for _ in range(an):
        i = _skip_name(msg, i)
        rtype, _cls, _ttl, rdlen = struct.unpack(">HHIH", msg[i:i + 10])
        i += 10
        if rtype == 1 and rdlen == 4:
            return socket.inet_ntoa(msg[i:i + 4])
        i += rdlen
    raise ValueError("no A record in the DNS answer")


def _query(host: str, resolver: str) -> str:
    qid = random.randrange(1 << 16)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(DNS_TIMEOUT_S)
        s.sendto(build_dns_query(host, qid), (resolver, 53))
        return parse_dns_answer(s.recv(512), qid)


async def resolve_cloud(host: str, resolver: str, address: str | None) -> str:
    """The real cloud address. The home DNS points the host to us, so ask a
    public resolver, or use the fixed address from the options."""
    if address:
        return address
    return await asyncio.get_running_loop().run_in_executor(None, _query, host, resolver)
