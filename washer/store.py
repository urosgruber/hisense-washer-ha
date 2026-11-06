"""Files in the data directory (/data in the app). Device secrets live only here."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Totals:
    energy_kwh: float = 0.0
    water_l: float = 0.0
    cycles: int = 0


@dataclass
class Cycle:
    started: float
    ended: float | None
    energy_kwh: float
    water_l: float
    program_raw: int | None
    confirmed: bool | None


class Store:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    # -- helpers --------------------------------------------------------
    def _write(self, name: str, text: str) -> None:
        tmp = self.dir / (name + ".tmp")
        tmp.write_text(text)
        os.replace(tmp, self.dir / name)

    def _read_json(self, name: str):
        path = self.dir / name
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except ValueError:
            return None

    # -- login replies (secrets) ------------------------------------------
    def load_login(self) -> dict[int, bytes] | None:
        data = self._read_json("login.json")
        if not data:
            return None
        return {int(k): bytes.fromhex(v) for k, v in data["replies"].items()}

    def save_login(self, replies: dict[int, bytes], at: float) -> None:
        data = {"recorded_at": at, "replies": {str(k): v.hex() for k, v in replies.items()}}
        self._write("login.json", json.dumps(data))
        os.chmod(self.dir / "login.json", 0o600)

    def login_recorded_at(self) -> float | None:
        data = self._read_json("login.json")
        return data.get("recorded_at") if data else None

    # -- totals and cycles ------------------------------------------------
    def load_totals(self) -> Totals:
        data = self._read_json("totals.json")
        return Totals(**data) if data else Totals()

    def save_totals(self, totals: Totals) -> None:
        self._write("totals.json", json.dumps(asdict(totals)))

    def append_cycle(self, cycle: Cycle) -> None:
        with open(self.dir / "cycles.jsonl", "a") as f:
            f.write(json.dumps(asdict(cycle)) + "\n")

    def recent_cycles(self, n: int) -> list[Cycle]:
        path = self.dir / "cycles.jsonl"
        if not path.exists():
            return []
        lines = [line for line in path.read_text().splitlines() if line.strip()]
        return [Cycle(**json.loads(line)) for line in lines[-n:]]

    def load_open_cycle(self) -> Cycle | None:
        data = self._read_json("open_cycle.json")
        return Cycle(**data) if data else None

    def save_open_cycle(self, cycle: Cycle | None) -> None:
        if cycle is None:
            (self.dir / "open_cycle.json").unlink(missing_ok=True)
        else:
            self._write("open_cycle.json", json.dumps(asdict(cycle)))

    # -- TLS ----------------------------------------------------------------
    def tls_paths(self) -> tuple[Path, Path]:
        """The self-signed certificate for the washer listener. Created once."""
        cert, key = self.dir / "cert.pem", self.dir / "key.pem"
        if not (cert.exists() and key.exists()):
            subprocess.run(
                ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                 "-keyout", str(key), "-out", str(cert), "-days", "3650",
                 "-subj", "/CN=washer-local"],
                check=True, capture_output=True,
            )
            os.chmod(key, 0o600)
        return cert, key
