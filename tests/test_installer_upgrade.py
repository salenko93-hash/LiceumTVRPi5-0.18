"""Coordinator/worker backup gate and transaction handoff failures."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'server')]
import installer_upgrade
import official_updates
import update_transaction
import backup_manager

class UpgradeBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.events=[]
        self.stack=__import__('contextlib').ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('release_preflight.verify'))
        self.stack.enter_context(patch.object(official_updates,'require_supervisor'))
        self.stack.enter_context(patch.multiple(backup_manager,ROOT=backup_manager.ROOT,DATA=backup_manager.DATA,BACKUP_DIR=backup_manager.BACKUP_DIR))
    def prepare(self,*args):
        self.events.append('prepare')
        job='a'*32;path=self.root/'data/update_jobs'/job;path.mkdir(parents=True)
        (path/'result.json').write_text(json.dumps({'phase':self.phase}))
        return {'job':job}
    def test_backup_failure_never_queues_update(self):
        with patch.object(official_updates,'verified_backup',side_effect=OSError('backup failed')),patch.object(update_transaction,'prepare') as prepare:
            with self.assertRaises(OSError): installer_upgrade.upgrade(self.root,ROOT)
            prepare.assert_not_called()
    def test_verified_backup_precedes_transaction_and_health(self):
        self.phase='healthy'
        def backup(root): self.events.append('backup_verified');return {'name':'fixture.tar.gz'}
        with patch.object(official_updates,'verified_backup',side_effect=backup),patch.object(update_transaction,'prepare',side_effect=self.prepare):
            installer_upgrade.upgrade(self.root,ROOT)
        self.assertEqual(self.events,['backup_verified','prepare'])
    def test_rolled_back_result_is_failure_not_success(self):
        self.phase='rolled_back'
        with patch.object(official_updates,'verified_backup',return_value={'name':'fixture.tar.gz'}),patch.object(update_transaction,'prepare',side_effect=self.prepare):
            with self.assertRaisesRegex(RuntimeError,'rolled_back'): installer_upgrade.upgrade(self.root,ROOT)
