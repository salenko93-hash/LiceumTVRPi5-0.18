"""Approved official releases, integrity gates and backup ordering; no real API."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import official_updates as official
import backup_manager
import update_transaction
from test_update_transaction import fixture


class OfficialUpdateTests(unittest.TestCase):
    def test_foreign_sources_and_credentials_are_rejected(self):
        for url in ('http://github.com/'+official.REPOSITORY+'/releases/download/v4.0.0/a.zip',
                    'https://github.com/other/project/releases/download/v4.0.0/a.zip',
                    'https://github.com/'+official.REPOSITORY+'-evil/releases/download/v4.0.0/a.zip',
                    'https://github.com@evil.invalid/a', 'https://raw.githubusercontent.com/other/repo/main/update.json'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                official.trusted_url(url)

    def test_official_assets_and_redirect_host_policy(self):
        official.trusted_url('https://github.com/'+official.REPOSITORY+'/releases/download/v4.0.0/a.zip')
        with self.assertRaises(ValueError):
            official.trusted_url('https://release-assets.githubusercontent.com/a')
        official.trusted_url('https://release-assets.githubusercontent.com/a',redirect=True)
        with self.assertRaises(ValueError):
            official.trusted_url('https://evil.invalid/a',redirect=True)

    def test_private_provider_configuration_is_not_rewritten_but_foreign_git_is_refused(self):
        import sync_manager
        sync_manager._https_only('https://private-provider.invalid/local-schedule')
        sync_manager._https_only('https://raw.githubusercontent.com/'+official.REPOSITORY+'/main/data/default/content_manifest.json')
        with self.assertRaises(ValueError):
            sync_manager._https_only('https://raw.githubusercontent.com/other/repository/main/manifest.json')

    def test_apply_without_approval_performs_no_network_or_backup(self):
        with patch.object(official,'release_info') as network,patch.object(official,'verified_backup') as backup:
            with self.assertRaises(PermissionError):
                official.apply(Path('/unused'),'v4.0.0')
            network.assert_not_called()
            backup.assert_not_called()

    def info(self, ci=True):
        return {'tag':'v4.0.0','repository':official.REPOSITORY,'commit':'a'*40,'ci_verified':ci,
                'filename':'LyceumTV-RPi5-v4.0.0.zip',
                'checksum_url':'https://github.com/'+official.REPOSITORY+'/releases/download/v4.0.0/LyceumTV-RPi5-v4.0.0.zip.sha256',
                'package_url':'https://github.com/'+official.REPOSITORY+'/releases/download/v4.0.0/LyceumTV-RPi5-v4.0.0.zip'}

    def test_failed_ci_blocks_before_download_and_backup(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td).resolve()
            with patch.object(official,'ROOT',root),patch.object(official,'require_supervisor'),patch.object(official,'release_info',return_value=self.info(False)),patch.object(official,'download') as download,patch.object(official,'verified_backup') as backup:
                with self.assertRaisesRegex(ValueError,'workflow'):
                    official.apply(root,'v4.0.0',True)
                download.assert_not_called()
                backup.assert_not_called()

    def test_checksum_failure_prevents_backup_and_prepare(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td).resolve()
            with patch.object(official,'ROOT',root),patch.object(official,'require_supervisor'),patch.object(official,'release_info',return_value=self.info()),patch.object(official,'download',side_effect=[('0'*64+'  LyceumTV-RPi5-v4.0.0.zip').encode(),b'tampered']),patch.object(official,'verified_backup') as backup,patch('update_transaction.prepare') as prepare:
                with self.assertRaisesRegex(ValueError,'SHA-256 mismatch'):
                    official.apply(root,'v4.0.0',True)
                backup.assert_not_called()
                prepare.assert_not_called()

    def test_zip_traversal_and_links_rejected_before_extract(self):
        for name,mode in (('../escape',0o100644),('project/link',0o120777)):
            raw=io.BytesIO()
            with zipfile.ZipFile(raw,'w') as z:
                entry=zipfile.ZipInfo(name);entry.external_attr=mode<<16;z.writestr(entry,b'outside')
            with tempfile.TemporaryDirectory() as td,self.assertRaises(ValueError):
                official.extract_package(raw.getvalue(),Path(td))

    def test_check_is_read_only_and_does_not_apply(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'release.json').write_text('{"version":"3.9.0"}')
            before={p.name:p.read_bytes() for p in root.iterdir()}
            with patch.object(official,'ROOT',root),patch.object(official,'release_info',return_value=self.info()),patch.object(official,'apply') as apply,patch('sys.argv',['official_updates.py']),contextlib.redirect_stdout(io.StringIO()) as output:
                official.main()
            apply.assert_not_called()
            result=json.loads(output.getvalue())
            self.assertTrue(result['available'])
            self.assertFalse(result['install_performed'])
            self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir()})

    def test_only_official_verify_workflow_authorizes_release(self):
        name='LyceumTV-RPi5-v4.0.0.zip'
        release={'tag_name':'v4.0.0','html_url':'https://github.com/'+official.REPOSITORY+'/releases/tag/v4.0.0',
                 'assets':[{'name':n,'state':'uploaded','browser_download_url':'https://github.com/'+official.REPOSITORY+'/releases/download/v4.0.0/'+n} for n in (name,name+'.sha256')]}
        ref={'object':{'sha':'a'*40,'type':'commit'}}
        for conclusion,expected in [('success',True),('failure',False)]:
            runs={'workflow_runs':[{'path':'.github/workflows/verify.yml','head_sha':'a'*40,'event':'push','status':'completed','conclusion':conclusion}]}
            with patch.object(official,'api',side_effect=[release,ref,runs]):
                self.assertEqual(official.release_info('v4.0.0')['ci_verified'],expected)

    def package(self, folder):
        fixture(folder,'3.6.1')
        (folder/'release.json').write_text(json.dumps({'version':'4.0.0','repository':official.REPOSITORY}))
        manifest=json.loads((folder/'PACKAGE_SHA256.json').read_text())
        manifest['release.json']=hashlib.sha256((folder/'release.json').read_bytes()).hexdigest()
        (folder/'PACKAGE_SHA256.json').write_text(json.dumps(manifest))
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as z:
            for path in folder.rglob('*'):
                if path.is_file():
                    z.write(path,'release/'+path.relative_to(folder).as_posix())
        return raw.getvalue()

    def test_verified_backup_precedes_transaction_and_preserves_private_data(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td).resolve();root=base/'installed';source=base/'source'
            fixture(root,'3.6.0');raw=self.package(source)
            (root/'data/default').mkdir();(root/'data/default/private.json').write_text('local schedule')
            (root/'public/media').mkdir();(root/'public/media/local.mp4').write_bytes(b'local media')
            events=[]
            original_backup=official.verified_backup;original_prepare=update_transaction.prepare
            def download(url,limit=0):
                events.append('checksum' if url.endswith('.sha256') else 'package')
                return (hashlib.sha256(raw).hexdigest()+'  '+self.info()['filename']).encode() if url.endswith('.sha256') else raw
            def backup(path):
                events.append('backup');return original_backup(path)
            def prepare(path,release):
                events.append('prepare');job=original_prepare(path,release)
                update_transaction.execute(path,check=lambda _:True,poll=0)
                return job
            with patch.object(official,'ROOT',root),patch.object(official,'require_supervisor'),patch.object(official,'release_info',return_value=self.info()),patch.object(official,'download',side_effect=download),patch.object(official,'verified_backup',side_effect=backup),patch.object(update_transaction,'prepare',side_effect=prepare),patch.multiple(backup_manager,ROOT=root,DATA=root/'data',BACKUP_DIR=root/'data/backups'):
                result=official.apply(root,'v4.0.0',True)
            self.assertEqual(events,['checksum','package','backup','prepare'])
            self.assertEqual(result['result'],'healthy')
            self.assertEqual((root/'data/default/private.json').read_text(),'local schedule')
            self.assertEqual((root/'public/media/local.mp4').read_bytes(),b'local media')
            self.assertTrue((root/'data/backups'/result['backup']['name']).is_file())
            self.assertFalse((root/'data/ota_pending').exists())

    def test_failed_backup_never_queues_installation(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td).resolve();root=base/'installed';fixture(root,'3.6.0');raw=self.package(base/'source')
            sidecar=(hashlib.sha256(raw).hexdigest()+'  '+self.info()['filename']).encode()
            with patch.object(official,'ROOT',root),patch.object(official,'require_supervisor'),patch.object(official,'release_info',return_value=self.info()),patch.object(official,'download',side_effect=[sidecar,raw]),patch.object(official,'verified_backup',side_effect=OSError('backup failed')),patch.object(update_transaction,'prepare') as prepare:
                with self.assertRaises(OSError):
                    official.apply(root,'v4.0.0',True)
                prepare.assert_not_called()
            self.assertFalse((root/'data/ota_pending').exists())
