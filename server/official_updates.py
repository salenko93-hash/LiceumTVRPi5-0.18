"""Official GitHub releases only. Checking is read-only; apply needs --approve."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import zipfile

REPOSITORY = 'salenko93-hash/LiceumTVRPi5-0.18'
API = 'https://api.github.com/repos/' + REPOSITORY
ROOT = Path(__file__).resolve().parents[1]


def trusted_url(url, redirect=False):
    p = urlsplit(url)
    if p.scheme != 'https' or p.username or p.password or p.port not in (None,443):
        raise ValueError('Official update URLs must be HTTPS without credentials')
    if p.hostname == 'api.github.com' and p.path.startswith('/repos/' + REPOSITORY + '/'):
        return url
    if p.hostname == 'github.com' and p.path.startswith('/' + REPOSITORY + '/releases/download/'):
        return url
    if redirect and p.hostname in {'release-assets.githubusercontent.com','objects.githubusercontent.com'}:
        return url
    raise ValueError('Update source is not the official repository')


class OfficialRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        trusted_url(newurl, redirect=True)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def download(url, limit=2*1024*1024):
    trusted_url(url)
    req = Request(url, headers={'User-Agent':'LyceumTV-official-updates', 'Accept':'application/vnd.github+json'})
    with build_opener(OfficialRedirect()).open(req, timeout=90) as response:
        trusted_url(response.geturl(), redirect=True)
        raw = response.read(limit+1)
    if len(raw)>limit:
        raise ValueError('Update response exceeds size limit')
    return raw


def api(path):
    return json.loads(download(API + path))


def release_info(tag=None):
    if tag is not None and not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
        raise ValueError('Use an explicit vMAJOR.MINOR.PATCH release')
    release = api('/releases/tags/' + tag if tag else '/releases/latest')
    actual = release.get('tag_name','')
    if release.get('draft') or release.get('prerelease') or not re.fullmatch(r'v\d+\.\d+\.\d+',actual):
        raise ValueError('Only published stable versioned releases are accepted')
    assets = {a['name']:a['browser_download_url'] for a in release.get('assets',[]) if a.get('state')=='uploaded'}
    name = 'LyceumTV-RPi5-' + actual + '.zip'
    if name not in assets or name+'.sha256' not in assets:
        raise ValueError('Release ZIP/checksum missing')
    for url in (assets[name],assets[name+'.sha256']):
        trusted_url(url)
        if urlsplit(url).path != '/' + REPOSITORY + '/releases/download/' + actual + '/' + url.rsplit('/',1)[-1]:
            raise ValueError('Asset is not from the selected release')
    ref = api('/git/ref/tags/' + actual)['object']
    if ref['type']=='tag':
        ref = api('/git/tags/' + ref['sha'])['object']
    if ref['type']!='commit' or not re.fullmatch(r'[0-9a-f]{40}',ref['sha']):
        raise ValueError('Tag does not resolve to a commit')
    runs = api('/actions/runs?head_sha=' + ref['sha'] + '&per_page=100').get('workflow_runs',[])
    verified = any(r.get('path')=='.github/workflows/verify.yml' and r.get('head_sha')==ref['sha']
                   and r.get('event')=='push' and r.get('status')=='completed' and r.get('conclusion')=='success' for r in runs)
    return {'repository':REPOSITORY, 'tag':actual, 'commit':ref['sha'], 'ci_verified':verified,
            'url':release['html_url'], 'package_url':assets[name], 'checksum_url':assets[name+'.sha256'], 'filename':name}


def extract_package(raw, destination):
    archive = destination / 'update.zip'
    archive.write_bytes(raw)
    with zipfile.ZipFile(archive) as z:
        info = z.infolist()
        if len(info)>4096 or sum(i.file_size for i in info)>256*1024*1024:
            raise ValueError('Oversized ZIP')
        for item in info:
            p = PurePosixPath(item.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in item.filename or ':' in item.filename or (item.external_attr>>16)&0o170000==0o120000:
                raise ValueError('Unsafe ZIP path/link')
        if len({i.filename for i in info})!=len(info) or z.testzip():
            raise ValueError('Corrupt or duplicate ZIP entries')
        z.extractall(destination/'extract')
    roots = [p for p in (destination/'extract').iterdir() if p.is_dir() and (p/'server/app.py').is_file()]
    if len(roots)!=1:
        raise ValueError('Expected one complete project')
    return roots[0]


def verified_backup(root):
    import backup_manager
    # The CLI only operates on its own installed tree, never on another --root.
    if Path(root).resolve()!=backup_manager.ROOT.resolve():
        raise ValueError('Backup root mismatch')
    result = backup_manager.create_backup(label='before-official-update')
    name = result.get('name') or result.get('file')
    if not name:
        raise ValueError('Backup did not return a filename')
    path = backup_manager.BACKUP_DIR / name
    with gzip.open(path,'rb') as stream:
        while stream.read(1024*1024):
            pass
    with tarfile.open(path,'r:gz') as archive:
        archive.getmembers()
    return {'name':name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def require_supervisor(root):
    sys.path.insert(0,str(ROOT))
    import launcher
    pid = root/'data/launcher.pid'
    if not pid.exists() or not launcher.process_exists(pid.read_text().strip()):
        raise ValueError('Running launcher supervisor required')
    cmdline = Path('/proc')/pid.read_text().strip()/'cmdline'
    if not cmdline.is_file() or b'launcher.py' not in cmdline.read_bytes() or str(root).encode() not in cmdline.read_bytes():
        raise ValueError('Supervisor identity mismatch')


def apply(root, tag, approved=False, wait=180):
    if not approved:
        raise PermissionError('Administrative approval required: apply --approve')
    if Path(root).resolve()!=ROOT:
        raise ValueError('Run the updater from the installed project')
    require_supervisor(root)
    info = release_info(tag)
    if not info['ci_verified']:
        raise ValueError('No successful official verify workflow for this commit')
    checksum = download(info['checksum_url'],4096).decode().split()
    if len(checksum)!=2 or not re.fullmatch(r'[0-9a-f]{64}',checksum[0]) or checksum[1].lstrip('*')!=info['filename']:
        raise ValueError('Invalid SHA-256 sidecar')
    raw = download(info['package_url'],128*1024*1024)
    if hashlib.sha256(raw).hexdigest()!=checksum[0]:
        raise ValueError('Downloaded package SHA-256 mismatch')
    with tempfile.TemporaryDirectory(prefix='lyceumtv-official-') as td:
        source = extract_package(raw,Path(td))
        from update_transaction import validate_release, prepare
        validate_release(source)
        metadata = json.loads((source/'release.json').read_text())
        if metadata.get('repository')!=REPOSITORY or 'v'+metadata.get('version','')!=tag:
            raise ValueError('Package version/repository mismatch')
        backup = verified_backup(root)
        job = prepare(root,source)
    # prepare creates the marker only after download/hash/schema/backup/code snapshot.
    # The running supervisor stops/restarts the app and rolls back on failed health.
    deadline = time.monotonic()+wait
    result_path = root/'data/update_jobs'/job['job']/'result.json'
    while time.monotonic()<deadline:
        if result_path.is_file():
            result = json.loads(result_path.read_text())
            if result.get('phase')!='healthy':
                raise RuntimeError('Update did not pass health; recovery result: '+result.get('phase','unknown'))
            return {**info,'result':'healthy','backup':backup,'job':job['job']}
        time.sleep(1)
    raise TimeoutError('Supervisor still working; inspect job status before retrying')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',nargs='?',choices=['check','apply','rollback'],default='check')
    parser.add_argument('--tag')
    parser.add_argument('--approve',action='store_true')
    args = parser.parse_args()
    if args.action=='check':
        info = release_info(args.tag)
        current = json.loads((ROOT/'release.json').read_text()).get('version','0.0.0')
        info.update(current=current, available=tuple(map(int,info['tag'][1:].split('.')))>tuple(map(int,current.split('.'))), install_performed=False)
        print(json.dumps(info,ensure_ascii=False))
    elif args.action=='apply':
        if not args.tag:
            parser.error('apply requires an explicit --tag')
        print(json.dumps(apply(ROOT,args.tag,args.approve),ensure_ascii=False))
    else:
        if not args.approve:
            parser.error('rollback requires --approve')
        from update_transaction import queue_rollback
        print(json.dumps({'rollback_job':queue_rollback(ROOT)}))


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print('Official update refused: '+str(exc))
        raise SystemExit(1)
