"""Copy the cloud's login replies from a capture into a data directory.

The capture is messages.jsonl from the mitmproxy addon. The script takes the
101/102/103 replies of the last complete cloud login. With them, the server
can log the washer in with the cloud off.

The replies are device secrets. They go only to <data_dir>/login.json.

Usage: python3 -m scripts.import_login <messages.jsonl> <data_dir>
"""
import json
import sys
import time
from pathlib import Path

from washer.frame import parse_frame
from washer.store import Store

LOGIN_IDS = (101, 102, 103)


def import_login(src: Path, data_dir: Path) -> None:
    found, current = None, {}
    for line in Path(src).read_text().splitlines():
        rec = json.loads(line)
        if rec.get("ev") == "start":
            current = {}
        if rec.get("ev") != "msg" or rec.get("dir") != "cloud->washer":
            continue
        raw = bytes.fromhex(rec["hex"])
        fid = parse_frame(raw).id
        if fid in LOGIN_IDS:
            current[fid] = raw
            if len(current) == len(LOGIN_IDS):
                found = dict(current)
    if not found:
        raise SystemExit("No complete cloud login in the capture")
    Store(Path(data_dir)).save_login(found, time.time())


if __name__ == "__main__":
    import_login(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"Saved the login replies to {Path(sys.argv[2]) / 'login.json'}")
