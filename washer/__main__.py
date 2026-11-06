"""Start the washer server: python3 -m washer"""
from __future__ import annotations

import asyncio
import logging
import time

from .cloud import CloudControl
from .config import Config
from .cycle import CycleTracker
from .device import DeviceServer
from .state import WasherState
from .store import Store

log = logging.getLogger("washer")


async def main() -> None:
    config = Config.from_env()
    logging.basicConfig(level=config.log_level,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    store = Store(config.data_dir)
    state = WasherState()
    recent = store.recent_cycles(1)
    state.last_cycle = recent[-1] if recent else None
    cloud = CloudControl(config.cloud_max_hours)

    def on_change():
        v = state.view(time.time())
        log.info("State: %s, %s min left, connected %s", v["phase"], v["minutes_left"],
                 v["connected"])

    def on_cycle(cycle):
        log.info("Cycle ended (confirmed %s): %.2f kWh, %.2f L",
                 cycle.confirmed, cycle.energy_kwh, cycle.water_l)

    device = DeviceServer(config, store, state, CycleTracker(store), cloud,
                          on_change=on_change, on_cycle=on_cycle)
    await device.start()
    if not device.login_ready:
        log.warning("No recorded login replies yet. Turn the cloud on once.")
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
