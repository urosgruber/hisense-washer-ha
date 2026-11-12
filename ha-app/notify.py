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
URL = "ws://supervisor/core/websocket"
# Every wait on Home Assistant has a limit. Without one, a connection that
# Core accepts during its start but never answers blocks forever: the
# process does not end, so run.sh does not start it again.
CONNECT_TIMEOUT = 30
# With no message for this long, ask Home Assistant for a pong. No pong
# within the same time: the connection is dead and the process ends.
IDLE_TIMEOUT = 60


def log(msg):
    print(f"[notify] {msg}", flush=True)


def is_timeout(error):
    return isinstance(error, TimeoutError) or type(error).__name__ == "WebSocketTimeoutException"


class Hass:
    """One websocket: replies by ID, events in between kept for later."""

    def __init__(self, ws, token):
        self.ws = ws
        self.next_id = 0
        self.pending = []
        self.ws.settimeout(CONNECT_TIMEOUT)
        if self._recv().get("type") != "auth_required":
            raise RuntimeError("Home Assistant did not ask for a login")
        self.ws.send(json.dumps({"type": "auth", "access_token": token}))
        if self._recv().get("type") != "auth_ok":
            raise RuntimeError("Home Assistant refused the login")

    @classmethod
    def connect(cls):
        import websocket

        ws = websocket.create_connection(URL, timeout=CONNECT_TIMEOUT)
        return cls(ws, os.environ["SUPERVISOR_TOKEN"])

    def _recv(self):
        raw = self.ws.recv()
        if not raw:
            raise ConnectionError("Home Assistant closed the connection")
        return json.loads(raw)

    def send(self, payload):
        self.next_id += 1
        payload["id"] = self.next_id
        self.ws.send(json.dumps(payload))
        return self.next_id

    def call(self, payload):
        msg_id = self.send(payload)
        while True:
            msg = self._recv()
            if msg.get("id") == msg_id and msg.get("type") == "result":
                return msg
            self.pending.append(msg)

    def ping(self):
        """Wait for the pong; a timeout here ends the process."""
        msg_id = self.send({"type": "ping"})
        while True:
            msg = self._recv()
            if msg.get("id") == msg_id and msg.get("type") == "pong":
                return
            self.pending.append(msg)

    def receive(self):
        """The next message. A quiet connection is checked with a ping."""
        self.ws.settimeout(IDLE_TIMEOUT)
        while not self.pending:
            try:
                return self._recv()
            except Exception as e:
                if not is_timeout(e):
                    raise
            self.ping()
        return self.pending.pop(0)


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
    hass = Hass.connect()
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
