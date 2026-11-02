"""Production kiosk profile setup must preserve existing preferences."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "scripts/launch-kiosk.sh").read_text(encoding="utf-8")
PROFILE = SCRIPT.split("<<'KIOSK_PROFILE'\n", 1)[1].split("\nKIOSK_PROFILE", 1)[0]


class TVDisplayProfileTests(unittest.TestCase):
    def test_fresh_profile_disables_translate_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([sys.executable, "-B", "-c", PROFILE, directory], check=True)
            data = json.loads((Path(directory) / "Default/Preferences").read_text())
            self.assertFalse(data["translate"]["enabled"])
            self.assertEqual(data["intl"]["accept_languages"], "uk,en")

    def test_existing_preferences_and_unrelated_keys_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Default/Preferences"
            path.parent.mkdir()
            path.write_text(json.dumps({"profile": {"name": "Keep"}, "intl": {"unrelated": 7}, "translate": {"enabled": True, "other": "keep"}}))
            subprocess.run([sys.executable, "-B", "-c", PROFILE, directory], check=True)
            data = json.loads(path.read_text())
            self.assertEqual(data["profile"]["name"], "Keep")
            self.assertEqual(data["intl"]["unrelated"], 7)
            self.assertEqual(data["translate"]["other"], "keep")
            self.assertFalse(data["translate"]["enabled"])

    def test_invalid_preferences_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Default/Preferences"
            path.parent.mkdir()
            for value in ('{broken', '[]'):
                path.write_text(value)
                result = subprocess.run([sys.executable, "-B", "-c", PROFILE, directory], capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(path.read_text(), value)
