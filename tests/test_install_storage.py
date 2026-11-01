"""New-directory preparation never repairs or rewrites existing production data."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import runtime_storage

@unittest.skipUnless(hasattr(os,'geteuid') and os.geteuid()!=0,'requires nonroot POSIX permissions')
class InstallStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'app'
    def prepare(self):
        with patch.object(runtime_storage.os,'chown') as owner:
            runtime_storage.prepare(self.root,os.getuid(),os.getgid())
            return owner.call_count
    def fixture(self):
        self.prepare()
        shutil.copytree(ROOT/'data/default',self.root/'data/default')
        shutil.copy2(ROOT/'data/config.example.json',self.root/'data/config.example.json')
        for name in ('runtime_data.py','install_config.py'):
            shutil.copy2(ROOT/'server'/name,self.root/'server'/name)
    def test_clean_install_and_idempotent_directory_creation(self):
        self.assertGreater(self.prepare(),0);self.assertEqual(self.prepare(),0)
        for rel,mode in runtime_storage.DIRECTORIES.items():
            self.assertEqual((self.root/rel).stat().st_mode & 0o777,mode)
    def test_wrong_existing_owner_blocks_entire_plan(self):
        self.root.mkdir()
        with self.assertRaises(PermissionError): runtime_storage.prepare(self.root,os.getuid()+1,os.getgid())
        self.assertEqual(list(self.root.iterdir()),[])
    def test_insecure_existing_mode_preserved_and_refused(self):
        self.root.mkdir();self.root.chmod(0o777)
        with self.assertRaises(PermissionError): self.prepare()
        self.assertEqual(self.root.stat().st_mode & 0o777,0o777)
    def test_initialize_preserves_calendar_config_media_on_rerun(self):
        self.fixture();runtime_storage.initialize(self.root)
        calendar=self.root/'data/current/calendar.json';calendar.write_bytes(b'{"custom":true}');calendar.chmod(0o444)
        config=self.root/'data/config.json';original=config.read_bytes()
        media=self.root/'public/media/test.mp3';media.write_bytes(b'keep')
        runtime_storage.initialize(self.root)
        self.assertEqual(calendar.read_bytes(),b'{"custom":true}');self.assertEqual(config.read_bytes(),original)
        self.assertEqual(media.read_bytes(),b'keep');self.assertEqual(config.stat().st_mode & 0o777,0o600)
    def test_symlink_directory_refused(self):
        self.root.symlink_to(Path(self.tmp.name),target_is_directory=True)
        with self.assertRaises(ValueError): self.prepare()
