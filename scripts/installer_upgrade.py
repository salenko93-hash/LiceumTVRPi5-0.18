"""Unprivileged installation worker: verified data backup before code transaction."""
import argparse
import json
from pathlib import Path
import sys
import time
from urllib.request import build_opener, ProxyHandler

PACKAGE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(PACKAGE/'server'),str(PACKAGE/'scripts')]


def health(root,timeout=60):
    cfg=json.loads((root/'data/config.json').read_text())
    expected=json.loads((root/'data/config.example.json').read_text())['version']
    url='http://127.0.0.1:'+str(int(cfg.get('port',8080)))+'/api/health'
    deadline=time.monotonic()+timeout;consecutive=0
    while time.monotonic()<deadline:
        try:
            with build_opener(ProxyHandler({})).open(url,timeout=2) as response:
                result=json.load(response)
            valid=result.get('ok') is True and result.get('service')=='LyceumTV' and result.get('version')==expected
        except (OSError,ValueError):
            valid=False
        consecutive=consecutive+1 if valid else 0
        if consecutive>=3:
            return
        time.sleep(1)
    raise TimeoutError('Installed application failed three consecutive health checks')


def upgrade(root,package,timeout=200):
    from release_preflight import verify
    verify(package)
    import official_updates,backup_manager,update_transaction
    official_updates.require_supervisor(root)
    backup_manager.ROOT=root;backup_manager.DATA=root/'data';backup_manager.BACKUP_DIR=root/'data/backups'
    print(json.dumps({'stage':'DATA_BACKUP','status':'START'}),flush=True)
    backup=official_updates.verified_backup(root)
    print(json.dumps({'stage':'VERIFIED_BACKUP','status':'PASS','backup':backup}),flush=True)
    job=update_transaction.prepare(root,package)
    print(json.dumps({'stage':'CODE_TRANSACTION','status':'QUEUED','job':job['job']}),flush=True)
    result_path=root/'data/update_jobs'/job['job']/'result.json'
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if result_path.is_file():
            result=json.loads(result_path.read_text())
            phase=result.get('phase')
            if phase!='healthy':
                raise RuntimeError('Health failed; automatic code recovery result: '+str(phase))
            print(json.dumps({'status':'PASS','stage':'HEALTH','job':job['job'],'backup':backup}),flush=True)
            return
        time.sleep(1)
    raise TimeoutError('Transaction still running; inspect data/update_jobs before retrying')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--package',type=Path)
    p.add_argument('--health',action='store_true')
    a=p.parse_args()
    try:
        health(a.root) if a.health else upgrade(a.root,a.package or PACKAGE)
    except Exception as exc:
        from installer import redact
        print(json.dumps({'status':'FAIL','error':redact(exc)}),flush=True)
        raise SystemExit(1)
