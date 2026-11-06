"""Settings from environment variables (WASHER_*). run.sh sets them in the app."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def parse_bind(bind: str) -> tuple[str, int]:
    host, _, port = bind.rpartition(":")
    return host or "0.0.0.0", int(port)


@dataclass
class Config:
    data_dir: Path = Path("/data")
    device_bind: str = "0.0.0.0:4444"
    web_bind: str = "0.0.0.0:8080"
    mqtt_url: str | None = None
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    cloud_max_hours: float = 2.0
    cloud_resolver: str = "1.1.1.1"
    cloud_address: str | None = None
    cloud_host: str = "wash-eu-link.hijuconn.com"
    cloud_port: int = 443
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Config":
        env = os.environ if env is None else env

        def get(name, default=None):
            value = env.get("WASHER_" + name.upper())
            return value if value not in (None, "") else default

        d = cls()
        return cls(
            data_dir=Path(get("data_dir", d.data_dir)),
            device_bind=get("device_bind", d.device_bind),
            web_bind=get("web_bind", d.web_bind),
            mqtt_url=get("mqtt_url"),
            mqtt_username=get("mqtt_username"),
            mqtt_password=get("mqtt_password"),
            cloud_max_hours=float(get("cloud_max_hours", d.cloud_max_hours)),
            cloud_resolver=get("cloud_resolver", d.cloud_resolver),
            cloud_address=get("cloud_address"),
            cloud_host=get("cloud_host", d.cloud_host),
            cloud_port=int(get("cloud_port", d.cloud_port)),
            log_level=get("log_level", d.log_level).upper(),
        )
