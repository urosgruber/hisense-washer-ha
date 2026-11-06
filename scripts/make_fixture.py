"""Turn a capture (messages.jsonl from the mitmproxy addon) into a test fixture.

The fixture keeps only the time and the base64 status of each 901 frame. It
drops tokens, the washer id and everything else, so it is safe to commit.

Usage: python3 scripts/make_fixture.py <messages.jsonl> <from_epoch> <to_epoch> <out>
"""
import json
import sys

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])
from washer.frame import parse_frame  # noqa: E402


def main(src, start, end, out):
    start, end = float(start), float(end)
    lines = []
    for line in open(src):
        rec = json.loads(line)
        if rec.get("ev") != "msg" or not start <= rec["t"] <= end:
            continue
        frame = parse_frame(bytes.fromhex(rec["hex"]))
        if frame.id != 901:
            continue
        for entry in frame.body.get("status", []):
            if entry.get("msgtype") == 102:
                lines.append(json.dumps({"t": rec["t"], "result": entry["result"]}))
    with open(out, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"{out}: {len(lines)} status frames")


if __name__ == "__main__":
    main(*sys.argv[1:5])
