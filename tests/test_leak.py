"""The repository is public. No tracked file may hold home details or
device secrets.

The rules are generic, so this file names no real value:
- no 36-digit hex run (the shape of a washer id), except all zeros;
- no IPv4 address, except a short list of public or documentation ones;
- no real-looking token or session key in JSON;
- no word from the untracked file ~/.config/hisense-washer/leak-words
  (one word per line: home host names, IP prefixes). CI has no such file.
"""
import os
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL_WORDS = Path(os.environ.get("WASHER_LEAK_WORDS",
                                  Path.home() / ".config" / "hisense-washer" / "leak-words"))

DEVICE_ID = re.compile(r"(?<![0-9a-fA-F])(?!0{36})[0-9a-fA-F]{36}(?![0-9a-fA-F])")
IPV4 = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
SAFE_IPS = {"0.0.0.0", "127.0.0.1", "1.1.1.1", "172.30.32.2"}
SAFE_IP_PREFIXES = ("203.0.113.",)  # RFC 5737 documentation range
TOKEN = re.compile(r'"token"\s*:\s*"(?!0+")[0-9a-f]{32}"')
KEY = re.compile(r'"key"\s*:\s*"[A-Za-z0-9+/=]{40,}"')
BINARY = {".png", ".jpg", ".ico"}


def local_words():
    if not LOCAL_WORDS.exists():
        return []
    return [w.strip() for w in LOCAL_WORDS.read_text().splitlines() if w.strip()]


def problems_in(name, text, words):
    found = []
    if DEVICE_ID.search(text):
        found.append(f"{name}: a 36-digit hex id")
    for ip in IPV4.findall(text):
        if ip not in SAFE_IPS and not ip.startswith(SAFE_IP_PREFIXES):
            found.append(f"{name}: IP address {ip}")
    if TOKEN.search(text):
        found.append(f"{name}: real-looking token")
    if KEY.search(text):
        found.append(f"{name}: real-looking key")
    for word in words:
        if word in text:
            found.append(f"{name}: a word from the local leak list")
    return found


class LeakTest(unittest.TestCase):
    def test_no_home_details(self):
        files = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.split()
        words = local_words()
        problems = []
        for name in files:
            path = ROOT / name
            if not path.is_file() or path.suffix in BINARY:
                continue
            problems += problems_in(name, path.read_bytes().decode("utf-8", "replace"), words)
        self.assertEqual(problems, [])

    def test_rules_catch_a_device_id(self):
        fake = "8" + "1" * 35
        self.assertTrue(problems_in("x", f'"wid":"{fake}"', []))
        self.assertFalse(problems_in("x", '"wid":"' + "0" * 36 + '"', []))

    def test_rules_catch_a_home_ip(self):
        self.assertTrue(problems_in("x", "host " + ".".join(["10", "1", "2", "3"]), []))
        self.assertFalse(problems_in("x", "resolver 1.1.1.1", []))

    def test_rules_catch_a_local_word(self):
        self.assertTrue(problems_in("x", "ssh myhost", ["myhost"]))


if __name__ == "__main__":
    unittest.main()
