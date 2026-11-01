"""Prepare only new application directories; initialize only absent fresh data."""
import argparse
import json
import os
from pathlib import Path
import sys

DIRECTORIES={'':0o755,'server':0o755,'scripts':0o755,'public':0o755,'data':0o700,
             'data/.locks':0o700,'data/current':0o700,'data/backups':0o700,
             'data/logs':0o700,'data/update_jobs':0o700,'public/media':0o700}


def prepare(root,uid,gid):
    root=Path(root)
    # Validate the whole plan before creating anything. No repair of existing dirs.
    for rel in DIRECTORIES:
        path=root/rel
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise ValueError('Symlink directory refused: '+str(path))
        if path.exists() and (not path.is_dir() or path.stat().st_uid!=uid or path.stat().st_mode & 0o022):
            raise PermissionError('Existing directory owner/type/permissions require review: '+str(path))
    for rel,mode in DIRECTORIES.items():
        path=root/rel
        if not path.exists():
            path.mkdir(mode=mode)
            os.chown(path,uid,gid) # exactly the directory just created, never -R
    marker=root/'data/.installer-fresh.json'
    if not marker.exists() and not (root/'server/app.py').exists():
        fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as output:
            json.dump({'previous_code':'absent','root':str(root.resolve())},output)
        os.chown(marker,uid,gid)


def exclusive_json(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as output:
        json.dump(value,output,ensure_ascii=False,indent=2)
        output.flush();os.fsync(output.fileno())


def initialize(root):
    root=Path(root)
    cfg=root/'data/config.json'
    if not cfg.exists():
        sys.path.insert(0,str(root/'server'))
        from install_config import secure_keys
        exclusive_json(cfg,secure_keys(json.loads((root/'data/config.example.json').read_text())))
    else:
        if not isinstance(json.loads(cfg.read_text()),dict):
            raise ValueError('Existing configuration invalid; preserved unchanged')
    sys.path.insert(0,str(root/'server'))
    from runtime_data import initialize_runtime_data
    initialize_runtime_data(root)
    ops=root/'data/smart_ops.json'
    if not ops.exists() and (root/'data/default/smart_ops.json').is_file():
        exclusive_json(ops,json.loads((root/'data/default/smart_ops.json').read_text()))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prepare',action='store_true')
    p.add_argument('--initialize',action='store_true')
    p.add_argument('--root',type=Path,default=Path('/opt/lyceumtv'))
    a=p.parse_args()
    if a.prepare:
        import pwd
        account=pwd.getpwnam('lyceumtv')
        prepare(a.root,account.pw_uid,account.pw_gid)
    if a.initialize:
        initialize(a.root)
