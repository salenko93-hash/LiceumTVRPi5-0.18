"""Isolated safety scenarios: no application startup or production writes."""
import json
from pathlib import Path
from datetime import datetime
import unittest
import threading
import time
from unittest.mock import Mock, patch

import engine
from engine import Engine


class AirRaidTests(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((Path(__file__).resolve().parents[1] / 'data/config.example.json').read_text(encoding='utf-8'))
        self.cfg['alerts_token'] = 'controlled-test-token'
        store = Mock()
        store.load.return_value = self.cfg
        store.public.return_value = {}
        runtime = Mock()
        runtime.load.return_value = {}
        with patch('engine.threading.Thread.start'):
            self.e = Engine(store, runtime)
        import schedule_engine
        original_read = schedule_engine.read_json
        sample = json.loads((Path(__file__).resolve().parents[1] / 'tests/fixtures/public_schedule.json').read_text())
        fixture_read = patch('schedule_engine.read_json', side_effect=lambda name, **kw: sample if name.startswith(('schedule_', 'shelter_')) else original_read(name, **kw))
        fixture_read.start()
        self.addCleanup(fixture_read.stop)
        self.now = datetime.fromisoformat('2026-11-02T08:10:00+02:00')
        self.clock = patch.object(self.e, '_now', side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def state(self):
        with patch('engine.duty_for_date', return_value={}), patch('engine.active_announcements', return_value=[]):
            return self.e.get_state()

    @patch('engine.write_event')
    def test_alarm_calendar_and_return(self, _):
        for date, phase in [('2026-11-02T08:10:00+02:00', 'LESSON'),
                            ('2026-11-02T08:50:00+02:00', 'BREAK'),
                            ('2026-11-08T08:10:00+02:00', 'NO_SCHEDULE'),
                            ('2026-10-28T08:10:00+02:00', 'HOLIDAY')]:
            with self.subTest(date=date):
                self.now = datetime.fromisoformat(date)
                self.e.set_manual_alarm(True)
                s = self.state()
                self.assertEqual(s['mode'], 'AIR_RAID')
                self.assertTrue(s['schedule']['shelter'])
                self.assertEqual(s['schedule']['phase'], phase)
                self.assertTrue(s['alarm']['sound_enabled'])
                self.assertTrue(s['alarm']['event_id'])
                self.assertFalse(s['announcement'])
                self.e.set_manual_alarm(False)
                self.assertEqual(self.state()['mode'], 'ALL_CLEAR')
                self.e.all_clear_until = 0
                s = self.state()
                self.assertEqual(s['mode'], 'NORMAL')
                self.assertFalse(s['schedule']['shelter'])

    def test_schedule_error_cannot_hide_alarm(self):
        self.e.manual_alarm = True
        self.e.silence_until = float('inf')
        with patch('engine.build_schedule', side_effect=OSError):
            s = self.state()
        self.assertEqual(s['mode'], 'AIR_RAID')
        self.assertEqual(s['schedule']['phase'], 'UNAVAILABLE')

    @patch('engine.write_event')
    def test_existing_remote_protocol_and_network_failure(self, _):
        for raw, expected in [(b'A', True), (b'P', True), (b'N', False)]:
            response = Mock(status=200)
            response.read.return_value = raw
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            with patch('engine.urlopen', return_value=response):
                self.e.poll_alerts()
            self.assertEqual(self.e.alarm_active(), expected)
        self.e.remote_alert_state = 'ACTIVE'
        with patch('engine.urlopen', side_effect=OSError('offline')):
            self.e.poll_alerts()
        self.assertTrue(self.e.alarm_active())
        self.assertIsNone(self.e.alert_status['http'])

    def test_weather_failure_cache_and_invalid_temperatures(self):
        for value in [None, float('nan'), float('inf'), 'invalid']:
            response = Mock()
            response.read.return_value = json.dumps({'current': {'temperature_2m': value}}).encode()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            with patch('engine.urlopen', return_value=response):
                self.assertFalse(self.e.refresh_weather()['available'])
        response.read.return_value = json.dumps({'current': {'temperature_2m': 0, 'apparent_temperature': 0, 'weather_code': 3}}).encode()
        with patch('engine.urlopen', return_value=response):
            weather = self.e.refresh_weather()
        self.assertTrue(weather['available'])
        self.assertEqual(weather['temperature'], 0)
        updated = weather['updated_at']
        with patch('engine.urlopen', side_effect=OSError):
            cached = self.e.refresh_weather()
        self.assertTrue(cached['stale'])
        self.assertEqual(cached['updated_at'], updated)

    def test_alert_loop_does_not_call_weather_or_schedule_downloads(self):
        self.e.refresh_weather = Mock(side_effect=AssertionError('Weather must use separate worker'))
        self.e.poll_alerts = Mock()
        self.e.sync_now = Mock()
        self.e._timed_states = Mock()
        self.e._stop.wait = lambda _: self.e._stop.set()
        self.e._loop()
        self.e.poll_alerts.assert_called_once()
        self.e.refresh_weather.assert_not_called()
        self.e.sync_now.assert_not_called()

    def test_blocked_background_downloads_cannot_block_alarm_activation(self):
        for blocked in ('weather', 'schedule'):
            with self.subTest(blocked=blocked):
                self.e._stop = threading.Event()
                entered, release, polled = threading.Event(), threading.Event(), threading.Event()
                def slow(*args, **kwargs):
                    entered.set()
                    release.wait(4)
                self.e._next_weather = 0 if blocked == 'weather' else time.time() + 999
                self.e._next_sync = 0
                self.e.refresh_weather = slow
                self.e.sync_now = slow
                self.e._timed_states = Mock()
                def alert(*args):
                    self.e.remote_alert_state = 'ACTIVE'
                    polled.set()
                self.e.poll_alerts = alert
                self.e._next_alert = 0
                data = threading.Thread(target=self.e._data_loop)
                alerts = threading.Thread(target=self.e._loop)
                data.start()
                try:
                    self.assertTrue(entered.wait(2))
                    alerts.start()
                    self.assertTrue(polled.wait(1), 'Alert polling blocked by download')
                    self.assertEqual(self.state()['mode'], 'AIR_RAID')
                finally:
                    self.e._stop.set()
                    release.set()
                    data.join(2)
                    if alerts.ident is not None:
                        alerts.join(2)


if __name__ == '__main__':
    unittest.main()
