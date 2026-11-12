import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "notify", Path(__file__).resolve().parent.parent / "ha-app" / "notify.py")
notify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(notify)


class FakeHass:
    def __init__(self):
        self.calls = []

    def call(self, payload):
        self.calls.append(payload)
        return {"success": True}


def event_msg(old="2026-11-06T17:00:00+00:00", new="2026-11-06T18:45:34+00:00", **attrs):
    attributes = {"event_type": "done", "confirmed": True, "energy_kwh": 0.45, "water_l": 54.76}
    attributes.update(attrs)
    trigger = {"from_state": None if old is None else {"state": old},
               "to_state": {"state": new, "attributes": attributes}}
    return {"type": "event", "event": {"variables": {"trigger": trigger}}}


class MessageTest(unittest.TestCase):
    def test_message_confirmed(self):
        self.assertEqual(notify.build_message({"confirmed": True, "energy_kwh": 0.45, "water_l": 54.76}),
                         ("Washer", "The wash is done. It used 0.45 kWh and 55 L of water."))

    def test_message_unconfirmed(self):
        self.assertEqual(notify.build_message({"confirmed": False, "energy_kwh": 0.3, "water_l": 20}),
                         ("Washer", "The wash has probably ended."))


class TargetsTest(unittest.TestCase):
    def test_targets_from_options(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "options.json"
            path.write_text(json.dumps({"notify_targets": ["mobile_app_a", "notify.mobile_app_b", " "]}))
            self.assertEqual(notify.targets_from_options(path), ["mobile_app_a", "mobile_app_b"])

    def test_missing_options_is_nobody(self):
        self.assertEqual(notify.targets_from_options(Path("/nonexistent/options.json")), [])


class HandleTest(unittest.TestCase):
    def test_empty_targets_sends_nothing(self):
        hass = FakeHass()
        self.assertEqual(notify.handle(hass, event_msg(), []), [])
        self.assertEqual(hass.calls, [])

    def test_sends_to_each_target(self):
        hass = FakeHass()
        sent = notify.handle(hass, event_msg(), ["mobile_app_a", "mobile_app_b"])
        self.assertEqual(sent, ["mobile_app_a", "mobile_app_b"])
        self.assertEqual([c["service"] for c in hass.calls], ["mobile_app_a", "mobile_app_b"])
        self.assertEqual(hass.calls[0]["service_data"]["title"], "Washer")

    def test_first_event_ever_is_sent(self):
        # The event entity is "unknown" until its first event.
        self.assertEqual(notify.handle(FakeHass(), event_msg(old="unknown"), ["mobile_app_a"]),
                         ["mobile_app_a"])

    def test_availability_change_is_quiet(self):
        self.assertEqual(notify.handle(FakeHass(), event_msg(old="unavailable"), ["a"]), [])
        self.assertEqual(notify.handle(FakeHass(), event_msg(new="unavailable"), ["a"]), [])


class FakeWS:
    """Plays a script: a string is a received frame, an exception is raised."""

    def __init__(self, script):
        self.script = list(script)
        self.sent = []
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)

    def send(self, data):
        self.sent.append(json.loads(data))

    def recv(self):
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


AUTH = [json.dumps({"type": "auth_required"}), json.dumps({"type": "auth_ok"})]


class ConnectionTest(unittest.TestCase):
    def test_login_has_a_time_limit(self):
        ws = FakeWS(AUTH)
        notify.Hass(ws, "token")
        self.assertEqual(ws.timeouts[0], notify.CONNECT_TIMEOUT)
        self.assertEqual(ws.sent[0], {"type": "auth", "access_token": "token"})

    def test_silent_core_at_login_ends_the_process(self):
        # Core accepts the connection during its start and sends nothing.
        with self.assertRaises(TimeoutError):
            notify.Hass(FakeWS([TimeoutError()]), "token")

    def test_closed_connection_is_a_clear_error(self):
        # websocket-client returns "" when the server closes the socket.
        hass = notify.Hass(FakeWS(AUTH + [""]), "token")
        with self.assertRaisesRegex(ConnectionError, "closed"):
            hass.receive()

    def test_quiet_connection_is_checked_with_a_ping(self):
        event = {"type": "event", "id": 1}
        hass = notify.Hass(FakeWS(AUTH + [TimeoutError(), json.dumps({"type": "pong", "id": 1}),
                                          json.dumps(event)]), "token")
        self.assertEqual(hass.receive(), event)
        self.assertEqual(hass.ws.sent[-1], {"type": "ping", "id": 1})
        self.assertIn(notify.IDLE_TIMEOUT, hass.ws.timeouts)

    def test_no_pong_ends_the_process(self):
        hass = notify.Hass(FakeWS(AUTH + [TimeoutError(), TimeoutError()]), "token")
        with self.assertRaises(TimeoutError):
            hass.receive()

    def test_event_during_ping_is_kept(self):
        event = {"type": "event", "id": 7}
        hass = notify.Hass(FakeWS(AUTH + [TimeoutError(), json.dumps(event),
                                          json.dumps({"type": "pong", "id": 1})]), "token")
        self.assertEqual(hass.receive(), event)

    def test_websocket_client_timeout_is_a_timeout(self):
        WebSocketTimeoutException = type("WebSocketTimeoutException", (Exception,), {})
        self.assertTrue(notify.is_timeout(WebSocketTimeoutException()))
        self.assertFalse(notify.is_timeout(ValueError()))


if __name__ == "__main__":
    unittest.main()
