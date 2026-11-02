import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import media_dashboard

class MediaDashboardTest(unittest.TestCase):
    def test_defaults_and_atomic_save(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(media_dashboard, 'PATH', Path(d)/'media_dashboard.json'):
                self.assertEqual(media_dashboard.load()['main_title'], '')
                saved=media_dashboard.save({'main_title':'Тиждень науки','media_type':'image','media_url':'/media/picture.jpg'})
                self.assertEqual(saved['main_title'],media_dashboard.load()['main_title'])
                self.assertEqual((Path(d)/'media_dashboard.json').stat().st_mode&0o777,0o600)
    def test_reject_external_media(self):
        for url in ('https://example.com/a.png','//evil','/media/../data/config.json','/media/x.jpg?foo'):
            with self.subTest(url=url):
                with self.assertRaises(ValueError): media_dashboard.save({'media_url':url})
    def test_reject_unknown(self):
        with self.assertRaises(ValueError): media_dashboard.save({'secret':'value'})
if __name__=='__main__':unittest.main()
