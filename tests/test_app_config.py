"""Rules across the app files: config.yaml, run.sh and the Dockerfile."""
import re
import unittest
from pathlib import Path

import yaml

APP = Path(__file__).resolve().parent.parent / "ha-app"


class AppConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = yaml.safe_load((APP / "config.yaml").read_text())
        cls.run_sh = (APP / "run.sh").read_text()

    def test_options_match_schema(self):
        self.assertEqual(set(self.config["options"]), set(self.config["schema"]))

    def test_secure_defaults(self):
        self.assertEqual(self.config["options"]["notify_targets"], [])
        self.assertTrue(self.config["panel_admin"])
        self.assertTrue(self.config["ingress"])
        self.assertIsNone(self.config["ports"].get("8080/tcp"))

    def test_cloud_limit(self):
        self.assertEqual(self.config["options"]["cloud_max_hours"], 2)

    def test_every_option_reaches_the_server(self):
        handled_elsewhere = {"mqtt", "notify", "notify_targets"}  # run.sh and notify.py use them
        for option in set(self.config["options"]) - handled_elsewhere:
            self.assertRegex(self.run_sh, rf"bashio::config '{option}'", option)
        for option in handled_elsewhere - {"notify_targets"}:
            self.assertIn(f"bashio::config.true '{option}'", self.run_sh)

    def test_device_port_matches(self):
        port = self.config["options"]["device_port"]
        self.assertIn(f"{port}/tcp", self.config["ports"])

    def test_image_name(self):
        self.assertEqual(self.config["image"], "ghcr.io/urosgruber/hisense-washer-ha-{arch}")

    def test_version_is_quoted_semver(self):
        text = (APP / "config.yaml").read_text()
        self.assertRegex(text, r'(?m)^version: "\d+\.\d+\.\d+"$')

    def test_changelog_has_the_version(self):
        changelog = (APP / "CHANGELOG.md").read_text()
        self.assertIn(f"## {self.config['version']}", changelog)

    def test_dockerfile_copies_the_parts(self):
        docker = (APP / "Dockerfile").read_text()
        for part in ("washer", "dist/hisense-washer-card.js", "ha-app/notify.py",
                     "ha-app/register_card.py", "ha-app/run.sh"):
            self.assertIn(part, docker)
        self.assertTrue(re.search(r"python3-paho-mqtt", docker))


if __name__ == "__main__":
    unittest.main()
