import json
import unittest
from pathlib import Path

from washer.mqtt import (AVAILABILITY_TOPIC, CYCLE_TOPIC, STATE_TOPIC, cloud_text,
                         cycle_payload, discovery_payloads, state_payload)
from washer.store import Cycle, Totals

SNAPSHOT = Path(__file__).parent / "fixtures" / "mqtt-discovery.json"

ENTITY_IDS = {
    "sensor.hisense_washer_phase", "sensor.hisense_washer_minutes_left",
    "sensor.hisense_washer_end_time", "binary_sensor.hisense_washer_door_locked",
    "sensor.hisense_washer_spin_speed", "sensor.hisense_washer_cycle_energy",
    "sensor.hisense_washer_cycle_water", "sensor.hisense_washer_total_energy",
    "sensor.hisense_washer_total_water", "sensor.hisense_washer_cycles",
    "binary_sensor.hisense_washer_connected", "sensor.hisense_washer_cloud",
    "event.hisense_washer_cycle",
    "sensor.hisense_washer_program", "sensor.hisense_washer_temperature",
    "sensor.hisense_washer_quicker", "sensor.hisense_washer_rinses",
    "binary_sensor.hisense_washer_steam", "binary_sensor.hisense_washer_extra_rinse",
    "binary_sensor.hisense_washer_pre_wash", "binary_sensor.hisense_washer_anti_crease",
    "binary_sensor.hisense_washer_cold_wash",
}

VIEW = {"phase": "washing", "phase_raw": "0x44", "minutes_left": 37, "end_time": 1793990734.0,
        "spin_rpm": 1200, "door_locked": True, "cycle_energy_kwh": 0.2, "cycle_water_l": 7.84,
        "connected": True, "stale": False, "last_status": 1793988514.0,
        "last_cycle_end": None, "last_cycle_energy_kwh": None, "last_cycle_water_l": None,
        "last_cycle_confirmed": None, "program": "Synthetics", "temperature_c": 40,
        "steam": False, "extra_rinse": True, "quicker": 2, "rinses": 3, "delay_hours": 0,
        "pre_wash": True, "anti_crease": False, "cold_wash": True}


class DiscoveryTest(unittest.TestCase):
    def test_entity_ids(self):
        ids = {p["default_entity_id"] for p in discovery_payloads().values()}
        self.assertEqual(ids, ENTITY_IDS)

    def test_discovery_snapshot(self):
        text = json.dumps(discovery_payloads(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        self.assertEqual(text, SNAPSHOT.read_text())

    def test_totals_for_energy_dashboard(self):
        p = discovery_payloads()
        energy = p["homeassistant/sensor/hisense_washer/total_energy/config"]
        water = p["homeassistant/sensor/hisense_washer/total_water/config"]
        self.assertEqual((energy["state_class"], energy["device_class"], energy["unit_of_measurement"]),
                         ("total_increasing", "energy", "kWh"))
        self.assertEqual((water["state_class"], water["device_class"], water["unit_of_measurement"]),
                         ("total_increasing", "water", "L"))

    def test_door_enabled_now_confirmed(self):
        door = discovery_payloads()["homeassistant/binary_sensor/hisense_washer/door_locked/config"]
        self.assertNotIn("enabled_by_default", door)
        self.assertIn("'None'", door["value_template"])   # unknown before the first status

    def test_program_options(self):
        from washer.status import PROGRAMS
        program = discovery_payloads()["homeassistant/sensor/hisense_washer/program/config"]
        self.assertEqual(program["device_class"], "enum")
        self.assertEqual(set(program["options"]), set(PROGRAMS.values()))
        quicker = discovery_payloads()["homeassistant/sensor/hisense_washer/quicker/config"]
        self.assertEqual(quicker["options"], ["off", "1", "2"])

    def test_no_secrets_in_payloads(self):
        text = json.dumps(discovery_payloads()).lower()
        for word in ('"token"', '"wid"', '"key"'):
            self.assertNotIn(word, text)


class PayloadTest(unittest.TestCase):
    def test_state_payload_keys(self):
        p = state_payload(VIEW, Totals(1.0, 100.0, 2), {"mode": "off", "until": None, "login_ready": True})
        self.assertEqual(p["phase"], "washing")
        self.assertEqual(p["minutes_left"], 37)
        self.assertTrue(p["end_time"].startswith("2026-11-06T"))
        self.assertEqual((p["total_energy_kwh"], p["total_water_l"], p["cycles"]), (1.0, 100.0, 2))
        self.assertEqual(p["cloud"], "off")
        self.assertNotIn("token", p)
        self.assertEqual((p["program"], p["temperature_c"], p["quicker"], p["extra_rinse"]),
                         ("Synthetics", 40, 2, True))

    def test_state_payload_no_end_time(self):
        p = state_payload(dict(VIEW, end_time=None), Totals(), {"mode": "off", "until": None,
                                                                 "login_ready": True})
        self.assertIsNone(p["end_time"])

    def test_cloud_text(self):
        self.assertEqual(cloud_text({"mode": "off", "until": None, "login_ready": True}), "off")
        self.assertEqual(cloud_text({"mode": "off", "until": None, "login_ready": False}), "needs login")
        self.assertRegex(cloud_text({"mode": "on", "until": 1793990734.0, "login_ready": True}),
                         r"^on until \d\d:\d\d$")

    def test_cycle_payload(self):
        c = Cycle(started=1793985451.0, ended=1793990734.0, energy_kwh=0.45, water_l=54.76,
                  program_raw=26, confirmed=True)
        self.assertEqual(cycle_payload(c), {"event_type": "done", "confirmed": True,
                                            "energy_kwh": 0.45, "water_l": 54.76,
                                            "duration_min": 88})

    def test_topics(self):
        self.assertEqual((STATE_TOPIC, AVAILABILITY_TOPIC, CYCLE_TOPIC),
                         ("hisense_washer/state", "hisense_washer/availability", "hisense_washer/cycle"))


if __name__ == "__main__":
    unittest.main()
