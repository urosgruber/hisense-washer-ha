#!/usr/bin/env python3
"""Send "wash done" to the phones in the app option notify_targets.

Watches the "Cycle" event entity (event.hisense_washer_cycle). Each new
event goes to every notify service in notify_targets. An empty list sends
nothing: nobody gets a message that nobody chose.

Runs for as long as the app runs; run.sh starts it again if it ends.
"""
import json
import os
import sys
from pathlib import Path

EVENT_ENTITY = "event.hisense_washer_cycle"
OPTIONS = Path("/data/options.json")
TITLE = "Washer"


def log(msg):
    print(f"[notify] {msg}", flush=True)


class Hass:
    """One websocket: replies by ID, events in between kept for later."""

    def __init__(self):
        import websocket

        self.ws = websocket.create_connection("ws://supervisor/core/websocket", timeout=None)
        self.ws.recv()  # auth_required
        self.ws.send(json.dumps({"type": "auth", "access_token": os.environ["SUPERVISOR_TOKEN"]}))
        if json.loads(self.ws.recv()).get("type") != "auth_ok":
            raise RuntimeError("Home Assistant refused the login")
        self.next_id = 0
        self.pending = []

    def send(self, payload):
        self.next_id += 1
        payload["id"] = self.next_id
        self.ws.send(json.dumps(payload))
        return self.next_id

    def call(self, payload):
        msg_id = self.send(payload)
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == msg_id and msg.get("type") == "result":
                return msg
            self.pending.append(msg)

    def receive(self):
        if self.pending:
            return self.pending.pop(0)
        return json.loads(self.ws.recv())


def targets_from_options(path=OPTIONS):
    """The notify services from the app options, without the "notify." prefix."""
    try:
        raw = json.loads(Path(path).read_text()).get("notify_targets") or []
    except (OSError, ValueError):
        return []
    out = []
    for name in raw:
        name = str(name).strip()
        if name.startswith("notify."):
            name = name[len("notify."):]
        if name:
            out.append(name)
    return out


def build_message(attrs):
    """(title, text) for a cycle event."""
    if attrs.get("confirmed") is False:
        return TITLE, "The wash has probably ended."
    energy = float(attrs.get("energy_kwh") or 0)
    water = float(attrs.get("water_l") or 0)
    return TITLE, f"The wash is done. It used {energy:.2f} kWh and {water:.0f} L of water."


def handle(hass, msg, targets):
    """Notify for one websocket message; return the services it went to."""
    if msg.get("type") != "event":
        return []
    trigger = (msg.get("event") or {}).get("variables", {}).get("trigger") or {}
    old, new = trigger.get("from_state"), trigger.get("to_state")
    # A new event changes the state (its time). Skip the entity becoming
    # available or unavailable. "unknown" before the first event is fine.
    if not old or not new or old.get("state") == "unavailable" \
            or new.get("state") in ("unavailable", "unknown"):
        return []
    title, body = build_message(new.get("attributes") or {})
    sent = []
    for service in targets:
        reply = hass.call({
            "type": "call_service", "domain": "notify", "service": service,
            "service_data": {"title": title, "message": body, "data": {"group": "hisense-washer"}},
        })
        log(f"done -> {service}: {'sent' if reply.get('success') else reply}")
        sent.append(service)
    return sent


def main():
    targets = targets_from_options()
    if not targets:
        log("notify_targets is empty: no notifications")
    hass = Hass()
    hass.call({"type": "subscribe_trigger",
               "trigger": {"platform": "state", "entity_id": EVENT_ENTITY}})
    log(f"watching the washer's cycles; targets: {', '.join(targets) or 'none'}")
    while True:
        handle(hass, hass.receive(), targets)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # run.sh starts it again
        log(f"stopped: {e}")
        sys.exit(1)
