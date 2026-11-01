"""Installer safety contracts, exercised without a Raspberry Pi or privileged changes."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import installer


class FakeHost:
    def __init__(self):
        self.calls=[];self.space=10**10;self.denied=False;self.modules=[]
    def identity(self):
        return dict(system='linux',machine='aarch64',os='debian',model='Raspberry Pi 5 Model B')
    def account(self,name):
        return dict(uid=os.getuid() if hasattr(os,'getuid') else 1000,gid=1000,shell='/usr/sbin/nologin',groups=[])
    def accessible(self,name,paths): return [not self.denied]*len(paths)
    def dependencies(self): return self.modules
    def commands(self): return []
    def unit(self,name): return dict(LoadState='loaded',ActiveState='active')
    def supervisor(self,root): return True
    def free(self,path): return self.space
    def chown_new(self,path,account): self.calls.append(('chown',str(path)))
    def run(self,args,timeout=60): self.calls.append(tuple(map(str,args)));return 'mock transaction complete'


@unittest.skipUnless(hasattr(os,'getuid') and os.getuid()!=0,'POSIX nonroot filesystem semantics')
class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'app';self.backups=self.base/'backups'
        self.host=FakeHost()
    def existing(self):
        for rel in ['',*installer.DIRECTORIES,'server','scripts','public']:
            (self.root/rel).mkdir(parents=True,exist_ok=True,mode=0o700)
        (self.root/'server/app.py').write_text('pass')
        (self.root/'data/config.json').write_text('{"port":8080}')
        (self.root/'data/config.json').chmod(0o600)
    def diag(self): return installer.diagnose(self.root,'admin',self.host,self.backups,ROOT)
    def execute(self,**kw):
        with patch.object(installer,'verify',return_value=None):
            return installer.execute(ROOT,self.root,'admin',self.host,self.backups,**kw)
    def test_clean_install_diagnostics_make_no_changes(self):
        report=self.diag();self.assertTrue(report['ok']);self.assertFalse(self.root.exists())
        self.assertEqual(report['mode'],'fresh');self.assertFalse(self.host.calls)
    def test_upgrade_missing_ota_pending_is_normal(self):
        self.existing();self.assertTrue(self.diag()['ok']);self.assertFalse((self.root/'data/ota_pending').exists())
    def test_present_ota_marker_blocks(self):
        self.existing();(self.root/'data/ota_pending').write_text('{}')
        self.assertIn('OTA_PENDING',[i['code'] for i in self.diag()['issues']])
    def test_missing_service_directory_created_once(self):
        self.existing();path=self.root/'data/update_jobs';path.rmdir()
        self.assertEqual(installer.prepare_missing(self.root,self.host,'admin',self.backups,ROOT),['data/update_jobs'])
        self.assertEqual(installer.prepare_missing(self.root,self.host,'admin',self.backups,ROOT),[])
        self.assertEqual(len(self.host.calls),1)
    def test_wrong_owner_blocks_without_chown(self):
        self.existing()
        original=self.host.account
        self.host.account=lambda name: dict(original(name),uid=os.getuid()+1) if name=='lyceumtv' else original(name)
        with self.assertRaises(ValueError): installer.prepare_missing(self.root,self.host,'admin',self.backups,ROOT)
        self.assertFalse(self.host.calls)
    def test_collects_disk_access_config_errors(self):
        self.existing();self.host.space=0;self.host.denied=True
        (self.root/'data/config.json').write_text('invalid')
        self.assertTrue({'DISK','BACKUP_SPACE','SERVICE_ACCESS','CONFIG'} <= {i['code'] for i in self.diag()['issues']})
    def test_check_only_never_runs_backend(self):
        self.existing();result=self.execute(check_only=True)
        self.assertEqual(result['status'],'PASS');self.assertFalse(self.host.calls)
    def test_backup_error_blocks_fresh_install(self):
        with patch.object(installer,'verified_baseline',side_effect=OSError('backup disk failed')):
            result=self.execute()
        self.assertEqual(result['status'],'FAIL');self.assertEqual(result['stage'],'BACKUP');self.assertFalse(self.host.calls)
    def test_fresh_orchestration_and_repeat_require_new_verified_backup(self):
        backups=[]
        original=self.host.run
        def run(args,timeout=60):
            if args[0]=='runuser':
                archives=list(self.backups.glob('fresh-baseline-*.tar.gz'))
                self.assertEqual(len(archives),len(backups)+1)
                backups.append(str(archives[-1]));installer.verify_backup(archives[-1])
            return original(args,timeout)
        self.host.run=run
        for _ in range(2):
            result=self.execute();self.assertEqual(result['status'],'PASS')
        self.assertEqual(len(backups),2)
    def test_fresh_health_failure_quarantines_code_preserves_data(self):
        original=self.host.run
        def run(args,timeout=60):
            if '--health' in args: raise RuntimeError('health rejected')
            if args[0]!='runuser': return original(args,timeout)
            self.root.mkdir();(self.root/'server').mkdir();(self.root/'server/app.py').write_text('new')
            (self.root/'data').mkdir();(self.root/'data/config.json').write_text('keep')
            return original(args,timeout)
        self.host.run=run
        result=self.execute()
        self.assertEqual(result['status'],'FAIL');self.assertFalse((self.root/'server/app.py').exists())
        self.assertEqual((self.root/'data/config.json').read_text(),'keep')
    def test_fresh_baseline_verified_and_preserves_retry_data(self):
        self.root.mkdir();(self.root/'data').mkdir();(self.root/'data/config.json').write_text('original')
        archive=installer.verified_baseline(self.backups,self.host,self.root)
        self.assertEqual(len(installer.verify_backup(archive)),64)
        import tarfile
        with tarfile.open(archive) as f: self.assertEqual(f.extractfile('data/config.json').read(),b'original')
    def test_untrusted_partial_install_refused(self):
        self.root.mkdir();(self.root/'private.txt').write_text('keep')
        self.assertIn('PARTIAL_INSTALL',[i['code'] for i in self.diag()['issues']])
    def test_release_error_still_collects_target_diagnostics(self):
        self.host.space=0
        with patch.object(installer,'verify',side_effect=ValueError('hash mismatch')):
            result=installer.execute(ROOT,self.root,'admin',self.host,self.backups,True)
        self.assertEqual(result['status'],'FAIL');self.assertIn('diagnostic',result)


class RedactionTests(unittest.TestCase):
    def test_sensitive_assignments_redacted(self):
        self.assertNotIn('example-value',installer.redact('password=example-value token=example-value admin_key=example-value'))
        self.assertNotIn('example-value',installer.redact('{"api_key":"example-value with spaces", "token":"example-value"} Bearer example-value'))

    def test_absent_systemd_unit_is_normal_during_fresh_diagnostics(self):
        import subprocess
        result=subprocess.CompletedProcess([],1,'LoadState=not-found\nActiveState=inactive\n','Unit not found')
        with patch.object(installer.subprocess,'run',return_value=result):
            self.assertEqual(installer.Host().unit('lyceumtv.service')['LoadState'],'not-found')
