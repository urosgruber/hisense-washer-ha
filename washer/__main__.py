"""Start the washer server: python3 -m washer"""
from __future__ import annotations

import asyncio
import logging
import time

from .cloud import CloudControl
from .config import Config, parse_bind
from .cycle import CycleTracker
from .device import DeviceServer
from .state import WasherState
from .store import Store

log = logging.getLogger("washer")

PUBLISH_EVERY_S = 60


async def main() -> None:
    config = Config.from_env()
    logging.basicConfig(level=config.log_level,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    store = Store(config.data_dir)
    state = WasherState()
    recent = store.recent_cycles(1)
    state.last_cycle = recent[-1] if recent else None
    cloud = CloudControl(config.cloud_max_hours)
    publisher = None
    device: DeviceServer | None = None

    def publish_state() -> None:
        if publisher is not None and device is not None:
            publisher.publish_state(state.view(time.time()), store.load_totals(),
                                    cloud.info(device.login_ready))

    last_logged = None

    def on_change() -> None:
        nonlocal last_logged
        v = state.view(time.time())
        summary = (v["phase"], v["minutes_left"], v["connected"])
        if summary != last_logged:
            log.info("State: %s, %s min left, connected %s", *summary)
            last_logged = summary
        publish_state()

    def on_cycle(cycle) -> None:
        log.info("Cycle ended (confirmed %s): %.2f kWh, %.2f L",
                 cycle.confirmed, cycle.energy_kwh, cycle.water_l)
        if publisher is not None:
            publisher.publish_cycle(cycle)

    if config.mqtt_url:
        from .mqtt import Publisher
        publisher = Publisher(config.mqtt_url, config.mqtt_username, config.mqtt_password,
                              on_connect_publish=publish_state)
        publisher.start()
    else:
        log.info("MQTT off: no WASHER_MQTT_URL")

    device = DeviceServer(config, store, state, CycleTracker(store), cloud,
                          on_change=on_change, on_cycle=on_cycle)
    await device.start()
    if not device.login_ready:
        log.warning("No recorded login replies yet. Turn the cloud on once on the admin page.")

    from .web import start_web
    host, port = parse_bind(config.web_bind)
    await start_web(state, cloud, store, device, host, port, on_change=publish_state)

    try:
        while True:  # the grace period and liveness change the view with time
            await asyncio.sleep(PUBLISH_EVERY_S)
            on_change()
    finally:
        if publisher is not None:
            publisher.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
