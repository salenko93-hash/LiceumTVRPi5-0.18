"""A damaged or incomplete extracted release must fail before installation."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_preflight', ROOT / 'scripts/release_preflight.py')
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


class ReleasePreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = {}
        for name in ('server/engine.py', 'public/js/air-raid-display.js', 'public/css/air-raid-display.css',
                     'scripts/install.sh', 'scripts/preinstall_backup.sh', 'scripts/preinstall_system_backup.sh', 'scripts/install_air_raid.sh',
                     'scripts/release_preflight.py', 'VERIFY_PROJECT.py', 'scripts/installer.py',
                     'scripts/installer_upgrade.py', 'scripts/runtime_storage.py', 'scripts/installer_launcher.ps1'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('pass\n' if name.endswith('.py') else 'fixture\n')
            self.manifest[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.save()

    def save(self):
        (self.root / 'PACKAGE_SHA256.json').write_text(json.dumps(self.manifest))

    def test_valid_package_and_tamper_rejection(self):
        preflight.verify(self.root)
        (self.root / 'server/engine.py').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            preflight.verify(self.root)

    def test_missing_safety_asset_is_rejected(self):
        (self.root / 'public/css/air-raid-display.css').unlink()
        with self.assertRaises(ValueError):
            preflight.verify(self.root)

    def test_unlisted_file_is_rejected(self):
        (self.root / 'production-config.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Unlisted'):
            preflight.verify(self.root)

    def test_ide_metadata_ignored_but_not_trusted_by_manifest(self):
        path=self.root/'.idea/.gitignore';path.parent.mkdir();path.write_text('local IDE metadata')
        preflight.verify(self.root)
        self.manifest['.idea/.gitignore']=hashlib.sha256(path.read_bytes()).hexdigest();self.save()
        with self.assertRaises(ValueError): preflight.verify(self.root)

    def test_manifest_path_escape_is_rejected(self):
        for name in ('../escape', 'C:/escape', '/escape', 'dir\\escape'):
            with self.subTest(name=name):
                self.manifest[name] = '0' * 64
                self.save()
                with self.assertRaisesRegex(ValueError, 'Unsafe'):
                    preflight.verify(self.root)
                del self.manifest[name]
