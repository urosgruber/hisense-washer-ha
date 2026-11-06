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


if __name__ == "__main__":
    unittest.main()
