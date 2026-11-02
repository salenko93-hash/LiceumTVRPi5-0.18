"""Functional contracts exercised again inside the proposed Linux sandbox."""
from datetime import datetime
import io
import json
import os
import socket
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import engine
import schedule_engine
import sync_manager

ROOT = Path(__file__).resolve().parents[1]


class SystemdRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("LYCEUMTV_SANDBOX_TEST") == "1", "requires Linux systemd sandbox")
    def test_effective_sandbox_and_monitor_helpers(self):
        status = Path("/proc/self/status").read_text()
        for key in ("CapEff", "CapBnd", "CapAmb"):
            line = next(line for line in status.splitlines() if line.startswith(key + ":"))
            self.assertEqual(int(line.split()[1], 16), 0)
        self.assertIn("NoNewPrivs:\t1", status)
        self.assertIn("Seccomp:\t2", status)
        with self.assertRaises(OSError):
            socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
        # NSS may use netlink; monitoring still needs the local systemd bus.
        subprocess.run(["hostname", "-I"], check=True, capture_output=True, timeout=5)
        info = subprocess.run(["systemctl", "show", "--property=Version", "--value"],
                              check=True, capture_output=True, text=True, timeout=5)
        self.assertTrue(info.stdout.strip())

    def test_lesson_break_holiday_and_shelter(self):
        schedule = json.loads((ROOT / "tests/fixtures/public_schedule.json").read_text())
        bells = schedule["bellSchedule"]
        config = {"numerator_start_date": "2026-09-01"}
        def at(value):
            return datetime.fromisoformat("2026-09-07T" + value)
        with patch.object(schedule_engine, "read_json", return_value=schedule), patch.object(
            schedule_engine, "load_bells_override", return_value=bells
        ), patch.object(schedule_engine, "holiday_label", return_value=""), patch.object(
            schedule_engine, "read_content", return_value={}
        ):
            for shelter in (False, True):
                lesson = schedule_engine.build_schedule(at(bells[0]["start"]), config, shelter)
                self.assertEqual(lesson["phase"], "LESSON")
                self.assertTrue(any(row["entries"] for row in lesson["rows"]))
                end = at(bells[0]["end"])
                from datetime import timedelta
                rest = schedule_engine.build_schedule(end + timedelta(seconds=1), config, shelter)
                self.assertEqual(rest["phase"], "BREAK")
            with patch.object(schedule_engine, "holiday_label", return_value="Канікули"):
                holiday = schedule_engine.build_schedule(at("09:00"), config, False)
                self.assertEqual(holiday["phase"], "HOLIDAY")
                self.assertEqual(holiday["rows"], [])

    def test_weather_https_parser_and_failure(self):
        app = engine.Engine(Mock(), Mock(load=lambda: {}))
        payload = {"current": {"temperature_2m": 12.4, "weather_code": 0}, "daily": {}}
        with patch.object(engine, "urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as request:
            self.assertTrue(app.refresh_weather({"timezone": "Europe/Kyiv"})["available"])
            self.assertTrue(request.call_args.args[0].full_url.startswith("https://api.open-meteo.com/"))
        fresh = engine.Engine(Mock(), Mock(load=lambda: {}))
        with patch.object(engine, "urlopen", side_effect=OSError("offline")):
            self.assertFalse(fresh.refresh_weather({"timezone": "Europe/Kyiv"})["available"])

    def test_remote_alert_and_all_clear(self):
        runtime = Mock(load=lambda: {})
        app = engine.Engine(Mock(), runtime)
        with patch.object(engine, "write_event"):
            for raw, expected in ((b'"A"', True), (b'"N"', False)):
                with patch.object(engine, "urlopen", return_value=io.BytesIO(raw)):
                    app.poll_alerts({"alerts_token": "fixture", "alerts_uid": "81"})
                self.assertEqual(app.alarm_active(), expected)
            self.assertGreater(app.all_clear_until, 0)
            self.assertEqual(runtime.save.call_count, 2)

    def test_schedule_bundle_download_and_atomic_promotion(self):
        default = ROOT / "data/default"
        # Build the same HTTPS response graph from the shipped, validated bundle.
        import hashlib
        names = sync_manager.REQUIRED + ["calendar.json", "content.json"]
        payloads = {name: (default / name).read_bytes() for name in names}
        entry = lambda name: {"url": name, "sha256": hashlib.sha256(payloads[name]).hexdigest()}
        obj = {"schedules": {name: entry(name) for name in sync_manager.REQUIRED},
               "calendar": entry("calendar.json"), "content": entry("content.json")}
        payloads["manifest.json"] = json.dumps(obj).encode()
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            with patch.multiple(sync_manager, DATA=data, CURRENT=data / "current", DEFAULT=default), patch.object(
                sync_manager, "urlopen", side_effect=lambda request, **kw: io.BytesIO(payloads[request.full_url.rsplit("/", 1)[-1]])
            ):
                sync_manager.sync_bundle("https://fixture.invalid/manifest.json")
            for name in names:
                self.assertEqual((data / "current" / name).read_bytes(), payloads[name])
