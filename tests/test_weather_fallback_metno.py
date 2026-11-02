"""Offline regression tests for the independent MET Norway weather fallback."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from engine import Engine


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps({
            'properties': {'timeseries': [{
                'data': {'instant': {'details': {
                    'air_temperature': 11.7, 'cloud_area_fraction': 90,
                }}, 'next_1_hours': {'summary': {'symbol_code': 'cloudy'}}}
            }]}
        }).encode()


class WeatherFallbackTests(unittest.TestCase):
    def test_metno_response_parses_and_marks_provider(self):
        engine = Engine.__new__(Engine)
        engine._now = lambda: __import__('datetime').datetime(2026, 11, 2)
        with patch('engine.urlopen', return_value=FakeResponse()) as opener:
            data = engine._weather_fallback_metno({'weather_city': 'Кропивницький'})
        self.assertTrue(data['available'])
        self.assertEqual(data['temperature'], 12)
        self.assertEqual(data['code'], 3)
        self.assertEqual(data['provider'], 'met.no')
        self.assertFalse(data['stale'])
        self.assertIn('api.met.no', opener.call_args.args[0].full_url)


if __name__ == '__main__':
    unittest.main()
