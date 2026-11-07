"""Home Assistant entities over MQTT discovery.

One retained JSON state on STATE_TOPIC feeds all entities. The process
availability (with a last will) is on AVAILABILITY_TOPIC. The "done" event goes
to CYCLE_TOPIC. Nothing secret goes to MQTT.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlparse

from .status import PROGRAMS
from .store import Cycle, Totals

log = logging.getLogger(__name__)

NODE = "hisense_washer"
STATE_TOPIC = f"{NODE}/state"
AVAILABILITY_TOPIC = f"{NODE}/availability"
CYCLE_TOPIC = f"{NODE}/cycle"
HA_STATUS_TOPIC = "homeassistant/status"
PHASE_OPTIONS = ["off", "idle", "delayed", "washing", "rinsing", "spinning", "done", "unknown"]

DEVICE = {"identifiers": [NODE], "manufacturer": "Hisense", "model": "Washer (ConnectLife)",
          "name": "Hisense Washer"}

# Live values are unavailable once the grace period after a drop is over.
LIVE_AVAILABILITY = {
    "topic": STATE_TOPIC,
    "value_template": "{{ 'online' if value_json.get('connected') or value_json.get('stale') "
                      "else 'offline' }}",
}


def _entity(component: str, key: str, name: str, live: bool = False, **extra) -> tuple[str, dict]:
    availability = [{"topic": AVAILABILITY_TOPIC}] + ([LIVE_AVAILABILITY] if live else [])
    payload = {
        "name": name,
        "unique_id": f"{NODE}_{key}",
        "default_entity_id": f"{component}.{NODE}_{key}",
        "has_entity_name": True,
        "device": DEVICE,
        "availability": availability,
        "availability_mode": "all",
    }
    if component != "event":
        payload["state_topic"] = STATE_TOPIC
    payload.update(extra)
    return f"homeassistant/{component}/{NODE}/{key}/config", payload


def _value(field: str) -> str:
    return "{{ value_json.get('%s') }}" % field


def _flag(field: str) -> str:
    """ON, OFF, or None (unknown) before the first status."""
    return ("{%% set v = value_json.get('%s') %%}"
            "{{ 'None' if v is none else ('ON' if v else 'OFF') }}" % field)


def discovery_payloads(node_id: str = NODE) -> dict[str, dict]:
    diagnostic = {"entity_category": "diagnostic"}
    entities = [
        _entity("sensor", "phase", "Phase", value_template=_value("phase"),
                device_class="enum", options=PHASE_OPTIONS, icon="mdi:washing-machine",
                json_attributes_topic=STATE_TOPIC,
                json_attributes_template="{{ {'phase_raw': value_json.get('phase_raw')} | tojson }}"),
        _entity("sensor", "minutes_left", "Minutes left", live=True,
                value_template=_value("minutes_left"), unit_of_measurement="min",
                device_class="duration", icon="mdi:timer-sand"),
        _entity("sensor", "end_time", "End time", live=True, value_template=_value("end_time"),
                device_class="timestamp"),
        _entity("binary_sensor", "door_locked", "Door locked", live=True,
                value_template=_flag("door_locked"), icon="mdi:lock"),
        _entity("sensor", "program", "Program", live=True, value_template=_value("program"),
                device_class="enum", options=sorted(PROGRAMS.values()), icon="mdi:tune-variant"),
        _entity("sensor", "temperature", "Temperature", live=True,
                value_template=_value("temperature_c"), unit_of_measurement="°C",
                device_class="temperature", icon="mdi:thermometer-water"),
        _entity("binary_sensor", "steam", "Steam", live=True, value_template=_flag("steam"),
                icon="mdi:weather-fog"),
        _entity("binary_sensor", "extra_rinse", "Extra rinse", live=True,
                value_template=_flag("extra_rinse"), icon="mdi:water-plus"),
        _entity("sensor", "quicker", "Quicker", live=True, device_class="enum",
                options=["off", "1", "2"], icon="mdi:clock-fast",
                value_template="{% set q = value_json.get('quicker') %}"
                               "{{ None if q is none else ('off' if q == 0 else q) }}"),
        _entity("sensor", "rinses", "Rinses", live=True, value_template=_value("rinses"),
                icon="mdi:water-sync"),
        _entity("sensor", "spin_speed", "Spin speed", live=True, value_template=_value("spin_rpm"),
                unit_of_measurement="rpm", icon="mdi:rotate-right"),
        _entity("sensor", "cycle_energy", "Cycle energy", live=True,
                value_template=_value("cycle_energy_kwh"), unit_of_measurement="kWh",
                device_class="energy"),
        _entity("sensor", "cycle_water", "Cycle water", live=True,
                value_template=_value("cycle_water_l"), unit_of_measurement="L",
                device_class="water"),
        _entity("sensor", "total_energy", "Total energy", value_template=_value("total_energy_kwh"),
                unit_of_measurement="kWh", device_class="energy", state_class="total_increasing"),
        _entity("sensor", "total_water", "Total water", value_template=_value("total_water_l"),
                unit_of_measurement="L", device_class="water", state_class="total_increasing"),
        _entity("sensor", "cycles", "Cycles", value_template=_value("cycles"),
                state_class="total_increasing", icon="mdi:counter"),
        _entity("binary_sensor", "connected", "Connected",
                value_template="{{ 'ON' if value_json.get('connected') else 'OFF' }}",
                device_class="connectivity", **diagnostic),
        _entity("sensor", "cloud", "Cloud", value_template=_value("cloud"), icon="mdi:cloud-lock",
                **diagnostic),
        _entity("event", "cycle", "Cycle", state_topic=CYCLE_TOPIC, event_types=["done"],
                icon="mdi:washing-machine-alert"),
    ]
    return dict(entities)


def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def cloud_text(cloud: dict) -> str:
    if cloud.get("mode") == "on" and cloud.get("until"):
        return "on until " + time.strftime("%H:%M", time.localtime(cloud["until"]))
    if not cloud.get("login_ready"):
        return "needs login"
    return "off"


def state_payload(view: dict, totals: Totals, cloud: dict) -> dict:
    p = dict(view)
    p["end_time"] = _iso(view.get("end_time"))
    p["last_status"] = _iso(view.get("last_status"))
    p["last_cycle_end"] = _iso(view.get("last_cycle_end"))
    p["total_energy_kwh"] = totals.energy_kwh
    p["total_water_l"] = totals.water_l
    p["cycles"] = totals.cycles
    p["cloud"] = cloud_text(cloud)
    return p


def cycle_payload(c: Cycle) -> dict:
    duration = round(((c.ended or c.started) - c.started) / 60)
    return {"event_type": "done", "confirmed": c.confirmed, "energy_kwh": c.energy_kwh,
            "water_l": c.water_l, "duration_min": duration}


class Publisher:
    """paho-mqtt 1.6 client in its own thread. Safe to call from asyncio."""

    def __init__(self, url: str, username: str | None, password: str | None,
                 on_connect_publish: Callable[[], None]):
        import paho.mqtt.client as mqtt  # imported here: tests do not need a broker

        self.url = urlparse(url)
        self.on_connect_publish = on_connect_publish
        self.client = mqtt.Client(client_id=NODE, clean_session=True)
        if username:
            self.client.username_pw_set(username, password)
        self.client.will_set(AVAILABILITY_TOPIC, "offline", qos=1, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(1, 60)

    def start(self) -> None:
        self.client.connect_async(self.url.hostname, self.url.port or 1883, keepalive=60)
        self.client.loop_start()

    def stop(self) -> None:
        self.client.publish(AVAILABILITY_TOPIC, "offline", qos=1, retain=True)
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            log.warning("MQTT login failed (code %s)", rc)
            return
        log.info("MQTT connected")
        client.subscribe(HA_STATUS_TOPIC)
        self._announce()

    def _on_message(self, client, userdata, msg):
        if msg.topic == HA_STATUS_TOPIC and msg.payload == b"online":
            self._announce()  # Home Assistant restarted

    def _announce(self) -> None:
        for topic, payload in discovery_payloads().items():
            self.client.publish(topic, json.dumps(payload), qos=1, retain=True)
        self.client.publish(AVAILABILITY_TOPIC, "online", qos=1, retain=True)
        self.on_connect_publish()

    def publish_state(self, view: dict, totals: Totals, cloud: dict) -> None:
        self.client.publish(STATE_TOPIC, json.dumps(state_payload(view, totals, cloud)),
                            qos=1, retain=True)

    def publish_cycle(self, c: Cycle) -> None:
        self.client.publish(CYCLE_TOPIC, json.dumps(cycle_payload(c)), qos=1)
