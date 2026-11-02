"""Create a reviewed public distribution without touching the private working copy.

Run into an existing clean clone of the ONE official repository. No publication
is performed. Real schedules/XLSX/reports/runtime data are never copied there.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = 'https://github.com/salenko93-hash/LiceumTVRPi5-0.18.git'


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')


def private_words(obj):
    words = set()
    if isinstance(obj,dict):
        for key,value in obj.items():
            if key=='teacher' and isinstance(value,str):
                words.update(re.findall(r'[А-ЯІЇЄҐ][а-яіїєґ]{3,}',value))
            words.update(private_words(value))
    elif isinstance(obj,list):
        for value in obj:
            words.update(private_words(value))
    return words


def public_binary(path):
    raw=path.read_bytes()
    if path.suffix=='.mp3':
        if raw.startswith(b'ID3') and len(raw)>=10:
            size=sum((raw[6+i]&127)<<(7*(3-i)) for i in range(4))
            raw=raw[10+size+(10 if raw[5]&16 else 0):]
        if len(raw)>=128 and raw[-128:-125]==b'TAG':
            raw=raw[:-128]
    if path.suffix=='.png' and raw.startswith(b'\x89PNG\r\n\x1a\n'):
        result=raw[:8];offset=8
        while offset+12<=len(raw):
            size=int.from_bytes(raw[offset:offset+4],'big');kind=raw[offset+4:offset+8]
            chunk=raw[offset:offset+12+size]
            if kind not in {b'tEXt',b'zTXt',b'iTXt',b'eXIf',b'tIME'}:
                result+=chunk
            offset+=12+size
        raw=result
    return raw


def prepare(destination):
    destination = Path(destination).resolve()
    if destination==ROOT or ROOT in destination.parents and destination.name!='.public-release':
        raise ValueError('Use the dedicated .public-release clone')
    origin = subprocess.check_output(['git','-C',str(destination),'remote','get-url','origin'],text=True).strip()
    if origin!=REPO:
        raise ValueError('Wrong origin; refusing export')
    if subprocess.check_output(['git','-C',str(destination),'status','--porcelain'],text=True).strip():
        raise ValueError('Destination must be clean; do not overwrite local work')
    source_schedules = [json.loads(p.read_text(encoding='utf-8')) for p in (ROOT/'data/default').glob('*numerator.json')]
    source_schedules += [json.loads(p.read_text(encoding='utf-8')) for p in (ROOT/'data/default').glob('*denominator.json')]
    secrets = set().union(*(private_words(o) for o in source_schedules))
    long_source = json.loads((ROOT/'public/preview-data/long.json').read_text(encoding='utf-8'))
    original_long_name = long_source['schedule']['rows'][0]['entries'][0]['teacher']
    long_name = 'Демонстраційний викладач довгого тестового предмета'
    for folder in ('server','public','scripts','tests','tools'):
        for source in (ROOT/folder).rglob('*'):
            if not source.is_file() or source.is_symlink() or '__pycache__' in source.parts:
                continue
            rel = source.relative_to(ROOT)
            if rel.parts[:2] in {('public','media'),('public','preview-data')} or source.suffix in {'.pyc','.pyo','.xlsx','.xls','.zip','.key','.pem'}:
                continue
            if rel.as_posix()=='public/js/demo_data.js':
                continue
            target = destination/rel
            target.parent.mkdir(parents=True,exist_ok=True)
            try:
                text = source.read_text(encoding='utf-8')
                text = text.replace(original_long_name,long_name)
                for name in sorted(secrets,key=len,reverse=True):
                    text = text.replace(name,'Приклад')
                target.write_text(text,encoding='utf-8',newline='\n')
            except UnicodeDecodeError:
                if rel.as_posix() not in {'public/img/logo_white.png','public/audio/trivoga.mp3','public/audio/minute_silence.mp3'} and not rel.as_posix().startswith('public/mobile/icons/'):
                    raise ValueError('Unreviewed binary: '+str(rel))
                target.write_bytes(public_binary(source))
    for name in ('README.md','launcher.py','VERIFY_PROJECT.py','requirements.txt','requirements-dev.txt','pyproject.toml',
                 '.gitignore','.prettierignore','INSTALL_TO_RPI5.ps1','INSTALL_LYCEUMTV4_RPI5.ps1',
                 'INSTALL_AIR_RAID_RPI5.ps1','CHECK_RPI.ps1','CHECK_SECURITY_RPI.ps1','OPEN_ADMIN.ps1','release.json'):
        shutil.copy2(ROOT/name,destination/name)
    metadata = json.loads((destination/'release.json').read_text())
    metadata['public_distribution'] = True
    write(destination/'release.json',metadata)
    cfg = json.loads((ROOT/'data/config.example.json').read_text())
    cfg.update(manifest_url='',sheets_url='',ota_manifest_url='')
    write(destination/'data/config.example.json',cfg)
    template = copy.deepcopy(source_schedules[0])
    template['source']='public-empty-template.xlsx'
    for daily in template['days'].values():
        for cls in daily:
            daily[cls]={}
    names=('schedule_numerator','schedule_denominator','shelter_numerator','shelter_denominator')
    for name in names:
        write(destination/f'data/default/{name}.json',template)
    for name in ('content.json','smart_ops.json','calendar.json'):
        obj=json.loads((ROOT/'data/default'/name).read_text(encoding='utf-8'))
        if 'source' in obj:
            obj['source']='public-example-calendar'
        write(destination/'data/default'/name,obj)
    synthetic=copy.deepcopy(template)
    synthetic['source']='synthetic-test-fixture.xlsx'
    for daily in synthetic['days'].values():
        for i,cls in enumerate(daily):
            daily[cls]={str(n):[{'subject':f'Тестовий предмет {i+1}','teacher':f'Викладач {i+1} (DEMO)','room':f'D{i+1}'}] for n in range(1,9)}
    write(destination/'tests/fixtures/public_schedule.json',synthetic)
    def sanitize_state(state,kind):
        for i,row in enumerate(state.get('schedule',{}).get('rows',[])):
            count=1 if kind=='substitution' and i==0 else 2 if i%3==0 or kind in ('groups','long') else 1
            row['entries']=[{'subject':f'Тестовий предмет {i+1}'+(' — розгорнутий демонстраційний навчальний приклад' if kind=='long' else ''),
                             'teacher':long_name if kind=='long' and i==0 else f'Викладач {i+1} (DEMO)',
                             'room':'К2' if kind=='substitution' and i==0 else f'D{i+1}',
                             'subgroup':str(g+1) if count>1 else ''} for g in range(count)]
            row['substitution']=kind=='substitution' and i==0
        return state
    for source in (ROOT/'public/preview-data').glob('*.json'):
        value=json.loads(source.read_text(encoding='utf-8'))
        value=[sanitize_state(item,source.stem) for item in value] if isinstance(value,list) else sanitize_state(value,source.stem)
        write(destination/'public/preview-data'/source.name,value)
    manifest={'version':'public-4.0.0','schedules':{}}
    for name in (*names,'calendar','content'):
        entry={'url':name+'.json','sha256':hashlib.sha256((destination/'data/default'/(name+'.json')).read_bytes()).hexdigest()}
        if name in names:
            manifest['schedules'][name+'.json']=entry
        else:
            manifest[name]=entry
    write(destination/'data/default/content_manifest.json',manifest)
    subprocess.run([sys.executable,'-B',str(destination/'tools/build_demo.py')],check=True)
    # Runtime lessons must come from an explicit synthetic fixture in public tests,
    # never from production defaults (which intentionally contain no lessons).
    path=destination/'tests/test_systemd_runtime.py'
    text=path.read_text().replace('ROOT / "data/default/schedule_numerator.json"','ROOT / "tests/fixtures/public_schedule.json"')
    path.write_text(text,encoding='utf-8')
    path=destination/'tests/test_air_raid_engine.py'
    text=path.read_text().replace('        self.now = datetime.fromisoformat(',
        "        import schedule_engine\n        original_read = schedule_engine.read_json\n        sample = json.loads((Path(__file__).resolve().parents[1] / 'tests/fixtures/public_schedule.json').read_text())\n        fixture_read = patch('schedule_engine.read_json', side_effect=lambda name, **kw: sample if name.startswith(('schedule_', 'shelter_')) else original_read(name, **kw))\n        fixture_read.start()\n        self.addCleanup(fixture_read.stop)\n        self.now = datetime.fromisoformat(",1)
    path.write_text(text,encoding='utf-8')
    path=destination/'tests/browser_tv_display_preview.cjs'
    text=path.read_text().replace('actual engine states','synthetic schema states').replace('Real engine substitution result','Synthetic substitution result')
    path.write_text(text,encoding='utf-8')
    print('Public export prepared. Private source data preserved. Review before git add/push.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination',type=Path)
    prepare(parser.parse_args().destination)
