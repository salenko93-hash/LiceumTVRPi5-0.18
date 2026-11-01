"""Fail closed on private data/secrets in the public release candidate."""
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
PATTERNS={
    'private-key':rb'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----',
    'github-token':rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})',
    'telegram-token':rb'\b\d{8,12}:[A-Za-z0-9_-]{30,}\b',
    'google-script-id':rb'AKfycb[A-Za-z0-9_-]{20,}',
    'personal-email':rb'[A-Za-z0-9._%+-]+@(?:gmail|outlook|hotmail|yahoo)\.[A-Za-z]{2,}',
}


def check(root=ROOT):
    from build_release import release_files
    files=release_files(root)
    findings=[]
    # Audit Git publication candidates too, including Actions (not shipped in ZIP).
    listed=subprocess.check_output(['git','-C',str(root),'ls-files','--cached','--others','--exclude-standard','-z'])
    for rel in listed.decode().split('\0'):
        if not rel:
            continue
        path=Path(root)/rel
        if path.is_symlink():
            findings.append((rel,'symlink'))
        elif path.is_file():
            files.setdefault(rel,path.read_bytes())
    for name,raw in files.items():
        if name.startswith(('reports/','docs/source/','public/media/')) or name.endswith(('.xlsx','.xls','.key','.pem','.pfx','.sqlite','.bak','.zip','.tar.gz')) or name.startswith('data/') and not (name.startswith('data/default/') or name=='data/config.example.json'):
            findings.append((name,'private path/type'))
        for rule,pattern in PATTERNS.items():
            if re.search(pattern,raw):
                findings.append((name,rule))
    cfg=json.loads(files['data/config.example.json'])
    for key,value in cfg.items():
        if (key.endswith(('_token','_key')) or key in {'telegram_chat_id','manifest_url','sheets_url','ota_manifest_url'}) and value:
            findings.append(('data/config.example.json','nonempty private configuration field: '+key))
    for name in ('schedule_numerator','schedule_denominator','shelter_numerator','shelter_denominator'):
        obj=json.loads(files['data/default/'+name+'.json'])
        if any(lessons for daily in obj['days'].values() for lessons in daily.values()):
            findings.append(('data/default/'+name+'.json','production template must contain zero lessons'))
    # Every teacher in public DEMO fixtures must be explicitly synthetic.
    def teachers(obj):
        if isinstance(obj,dict):
            for key,value in obj.items():
                if key=='teacher' and value and not any(marker in value for marker in ('DEMO','Демонстраційн')):
                    raise ValueError('Non-synthetic teacher in public fixtures')
                teachers(value)
        elif isinstance(obj,list):
            for item in obj:
                teachers(item)
    for name,raw in files.items():
        if name.startswith('public/preview-data/') and name.endswith('.json'):
            teachers(json.loads(raw))
    if findings:
        raise ValueError('Publication refused: '+str(findings))
    print(f'PASS: public privacy gate ({len(files)} reviewed files; no live lessons/secrets)')
    return files


if __name__=='__main__':
    try:
        check()
    except Exception as exc:
        print(str(exc),file=sys.stderr)
        sys.exit(1)
