"""TV4 default route and guardrails (static integration checks)."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class TV4ReleaseTests(unittest.TestCase):
    def test_default_route_and_rollback(self):
        s=(ROOT/'server/app.py').read_text()
        self.assertIn('path = "/tv4.html"',s)
        self.assertIn('path = "/index.html"',s)
    def test_safety_audio(self):
        js=(ROOT/'public/js/tv4.js').read_text()
        html=(ROOT/'public/tv4.html').read_text()
        for v in ('AIR_RAID','SILENCE','tv4-alarm-audio','tv4-silence-audio','sound_enabled','event_id'):
            self.assertIn(v,js+html)
    def test_normal_data_not_synthetic(self):
        s=(ROOT/'public/js/tv4.js').read_text()
        self.assertIn("new URLSearchParams(location.search).get('demo') === '1'",s)
        self.assertIn("fetch('/api/state'",s)
    def test_legacy_main_retained(self):
        self.assertIn('id="alarmAudio"',(ROOT/'public/index.html').read_text())
