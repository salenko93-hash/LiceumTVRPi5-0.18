"""Regression: content GitHub feed is separate from software release repository."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from sync_manager import _https_only

class ContentSourcePolicyTests(unittest.TestCase):
    def test_approved_content_feed(self):
        _https_only("https://raw.githubusercontent.com/salenko93-hash/lyceumtv-updates/main/sample-server/content_manifest.json")
        _https_only("https://raw.githubusercontent.com/salenko93-hash/lyceumtv-updates/main/sample-server/schedule_numerator.json")
        _https_only("https://raw.githubusercontent.com/salenko93-hash/LiceumTVRPi5-0.18/main/data/default/content_manifest.json")

    def test_foreign_github_repos_still_blocked(self):
        for url in (
            "https://raw.githubusercontent.com/other/repo/main/manifest.json",
            "https://github.com/salenko93-hash/lyceumtv-updates-malicious/main/f.json",
            "http://raw.githubusercontent.com/salenko93-hash/lyceumtv-updates/main/f.json",
            "https://evil@example.com/manifest.json",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                _https_only(url)

if __name__ == "__main__":
    unittest.main()
