"""Washer frames: b"HS" + JSON + optional 64-hex signature + b"\\r\\n"."""
from __future__ import annotations

import json
from dataclasses import dataclass

HEARTBEAT = b'HS{"id":902}\r\n'
END = b"\r\n"
SIGNATURE_LEN = 64


@dataclass(frozen=True)
class Frame:
    id: int | None
    body: dict | None
    raw: bytes


def split_frames(buf: bytes) -> tuple[list[bytes], bytes]:
    """Cut complete frames off the front of buf. Return them and the rest."""
    frames = []
    while True:
        end = buf.find(END)
        if end < 0:
            return frames, buf
        frames.append(buf[: end + len(END)])
        buf = buf[end + len(END):]


def parse_frame(raw: bytes) -> Frame:
    """Parse one raw frame. A frame that is not valid JSON gives id None."""
    body = raw[2:-len(END)] if raw.startswith(b"HS") and raw.endswith(END) else b""
    if not body.endswith(b"}"):
        body = body[:-SIGNATURE_LEN]
    try:
        obj = json.loads(body)
    except ValueError:
        return Frame(None, None, raw)
    if not isinstance(obj, dict):
        return Frame(None, None, raw)
    fid = obj.get("id")
    return Frame(fid if isinstance(fid, int) else None, obj, raw)
