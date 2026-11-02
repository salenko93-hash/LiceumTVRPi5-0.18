"""Installer diagnostics/preparation/transaction. No production action without CLI apply.

Only missing, allowlisted directories may be repaired. Existing permissions,
owners, production configuration and OTA markers are never silently changed.
"""
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

CODE_ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CODE_ROOT/'server'))
sys.path.insert(0,str(CODE_ROOT/'scripts'))
from release_preflight import verify

DIRECTORIES={'data':0o700,'data/.locks':0o700,'data/backups':0o700,'data/logs':0o700,
             'data/update_jobs':0o700,'public/media':0o700}
UNITS=('lyceumtv.service','lyceumtv-kiosk.service','lyceumtv-watchdog.timer',
       'lyceumtv-backup.timer','lyceumtv-mirror.timer')


def redact(text):
    text=re.sub(r'''(?i)((?:["']?)[\w-]*(?:password|passwd|token|secret|_key)(?:["']?)\s*[=:]\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)''',r'\1[REDACTED]',str(text))
    text=re.sub(r'(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*','Bearer [REDACTED]',text)
    return re.sub(r'\b(?:gh[pousr]_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+|\d{8,12}:[A-Za-z0-9_-]{30,})\b','[REDACTED]',text)


class Host:
    def run(self,args,timeout=60):
        result=subprocess.run([str(a) for a in args],capture_output=True,text=True,timeout=timeout)
        if result.returncode:
            raise RuntimeError(redact((result.stderr or result.stdout)[-2500:]).strip() or f'{args[0]} exited {result.returncode}')
        return result.stdout.strip()

    def account(self,name):
        import pwd,grp
        try:
            p=pwd.getpwnam(name)
            return {'uid':p.pw_uid,'gid':p.pw_gid,'shell':p.pw_shell,
                    'groups':[grp.getgrgid(g).gr_name for g in os.getgrouplist(name,p.pw_gid)]}
        except KeyError:
            return None

    def identity(self):
        release={}
        for line in Path('/etc/os-release').read_text().splitlines():
            if '=' in line:
                k,v=line.split('=',1);release[k]=v.strip('"')
        return {'system':sys.platform,'machine':platform.machine(),'os':release.get('ID',''),
                'like':release.get('ID_LIKE',''),'model':Path('/proc/device-tree/model').read_text().rstrip('\0')}

    def accessible(self,name,paths):
        code='import os,json,sys;print(json.dumps([os.access(p,m) for p,m in json.loads(sys.argv[1])]))'
        return json.loads(self.run(['runuser','-u',name,'--','python3','-B','-c',code,json.dumps([(str(p),m) for p,m in paths])]))

    def unit(self,name):
        result=subprocess.run(['systemctl','show',name,'-p','LoadState','-p','ActiveState'],capture_output=True,text=True,timeout=15)
        state=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
        if result.returncode and state.get('LoadState')!='not-found':
            raise RuntimeError(redact(result.stderr) or 'Cannot inspect systemd')
        return state

    def commands(self):
        return [name for name in ('python3','bash','runuser','sudo','tar','gzip','sha256sum','flock','systemctl','apt-get') if not shutil.which(name)]

    def dependencies(self):
        return [name for name in ('openpyxl','qrcode') if importlib.util.find_spec(name) is None]

    def supervisor(self,root):
        pid=(root/'data/launcher.pid').read_text().strip()
        if not pid.isdecimal(): return False
        raw=(Path('/proc')/pid/'cmdline').read_bytes()
        return b'launcher.py' in raw and str(root).encode() in raw

    def free(self,path):
        path=Path(path)
        while not path.exists():
            path=path.parent
        return shutil.disk_usage(path).free

    def chown_new(self,path,account):
        os.chown(path,account['uid'],account['gid'])


def issue(report,level,code,message,remedy=''):
    report['issues'].append({'level':level,'code':code,'message':message,'remedy':remedy})


def diagnose(root=Path('/opt/lyceumtv'),admin='admin',host=None,backup_root=Path('/var/backups/lyceumtv'),package=CODE_ROOT):
    host=host or Host();root=Path(root)
    existing=(root/'server/app.py').is_file()
    report={'mode':'upgrade' if existing else 'fresh','issues':[],'preparation':[],
            'ota_pending':'absent (normal)','services':{},'current_version':None,'install_performed':False}
    try:
        identity=host.identity();report['target']=identity
        if identity['system']!='linux' or identity['machine'] not in ('aarch64','arm64') or 'Raspberry Pi 5' not in identity['model']:
            issue(report,'ERROR','TARGET','Requires Raspberry Pi 5 / Linux ARM64')
        if not ({identity['os'],*identity.get('like','').split()} & {'debian','raspbian'}):
            issue(report,'ERROR','OS','Requires Raspberry Pi OS / Debian-compatible system')
    except Exception as exc:
        issue(report,'ERROR','TARGET',redact(exc))
    accounts={}
    for name in dict.fromkeys((admin,'lyceumtv')):
        try:
            accounts[name]=host.account(name)
            if accounts[name] is None:
                issue(report,'ERROR' if name==admin or existing else 'WARN','USER_MISSING',f'Account {name} is absent',
                      'Fresh installation provisions service accounts only after verified baseline backup; never repair existing users automatically')
        except Exception as exc:
            issue(report,'ERROR','USER_CHECK',f'{name}: {redact(exc)}')
    app=accounts.get('lyceumtv')
    if accounts.get(admin) and accounts[admin]['uid']==0:
        issue(report,'ERROR','ADMIN_ROOT','Use a normal administrative SSH account')
    if app and (app['uid']==0 or set(app.get('groups',())) & {'root','sudo','wheel','adm','docker','lxd','disk','shadow'} or app.get('shell')!='/usr/sbin/nologin'):
        issue(report,'ERROR','UNSAFE_SERVICE_USER','lyceumtv account is privileged or has an interactive shell','Review the existing account; automatic security changes are forbidden')
    checks=[]
    if root.is_symlink():
        issue(report,'ERROR','SYMLINK','Installation root must not be a symlink')
    if not existing and root.exists() and any(root.iterdir()):
        try:
            marker=root/'data/.installer-fresh.json'
            saved=json.loads(marker.read_text())
            if marker.is_symlink() or not app or marker.stat().st_uid!=app['uid'] or saved!={'previous_code':'absent','root':str(root.resolve())}:
                raise ValueError('Untrusted fresh-install marker')
        except Exception:
            issue(report,'ERROR','PARTIAL_INSTALL','Nonempty installation without trusted fresh baseline marker; preserve data and review before retry')
    if existing or root.exists():
        for rel,mode in [('',0o755),*DIRECTORIES.items()]:
            path=root/rel
            if path.is_symlink() or any(p.is_symlink() for p in path.parents if p!=root.parent):
                issue(report,'ERROR','SYMLINK',f'Unsafe directory: {path}');continue
            if not path.exists():
                if rel in DIRECTORIES:
                    report['preparation'].append(rel)
                    issue(report,'ERROR','MISSING_DIR',f'Missing directory: {path}','Installer may create this allowlisted directory')
                else:
                    issue(report,'ERROR','ROOT_MISSING','Installation root absent')
                continue
            if not path.is_dir():
                issue(report,'ERROR','NOT_DIRECTORY',f'Not a directory: {path}');continue
            st=path.stat()
            if st.st_mode & 0o022 or app and st.st_uid!=app['uid']:
                issue(report,'ERROR','DIRECTORY_SECURITY',f'Unsafe owner/permissions: {path}','Stop: review this existing directory individually; no recursive chown/chmod')
            if app:
                checks.append((path,os.R_OK|os.W_OK|os.X_OK))
        for base in ('server','scripts','public'):
            if (root/base).is_dir():
                checks.extend((p,os.R_OK|os.W_OK|os.X_OK) for p in (root/base).rglob('*') if p.is_dir() and not p.is_relative_to(root/'public/media') and not p.is_symlink())
    if existing or (root/'data/config.json').exists():
        cfg=root/'data/config.json'
        try:
            obj=json.loads(cfg.read_text(encoding='utf-8-sig'))
            if cfg.is_symlink() or cfg.stat().st_mode & 0o077 or app and cfg.stat().st_uid!=app['uid']:
                raise ValueError('Unsafe configuration owner/type/permissions')
            if not isinstance(obj,dict) or type(obj.get('port')) is not int or not 1<=obj['port']<=65535:
                raise ValueError('Required configuration fields are missing/invalid')
            if app:
                checks.append((cfg,os.R_OK|os.W_OK))
        except Exception as exc:
            issue(report,'ERROR','CONFIG','Installation configuration is absent, unreadable or invalid',type(exc).__name__+'; preserve/recover the original file; it will not be rewritten')
        try:
            release=root/'release.json'
            report['current_version']=json.loads(release.read_text())['version'] if release.is_file() else 'legacy (no release.json)'
        except Exception:
            issue(report,'ERROR','VERSION','Installed release metadata is invalid')
    if checks and app:
        try:
            allowed=host.accessible('lyceumtv',checks)
            denied=[str(p) for (p,_),ok in zip(checks,allowed) if not ok]
            if denied:
                issue(report,'ERROR','SERVICE_ACCESS','lyceumtv cannot access: '+', '.join(denied[:12]),'Review exact existing paths; only missing directories are auto-created')
        except Exception as exc:
            issue(report,'ERROR','SERVICE_ACCESS',redact(exc))
    marker=root/'data/ota_pending'
    try:
        marker.lstat()
        report['ota_pending']='present'
        issue(report,'ERROR','OTA_PENDING','OTA/recovery marker exists; finish recovery first')
    except FileNotFoundError:
        pass
    except OSError as exc:
        issue(report,'ERROR','OTA_ACCESS','Cannot inspect OTA marker: '+redact(exc))
    try:
        commands=host.commands()
        if commands: issue(report,'ERROR','COMMANDS','Missing required tools: '+', '.join(commands))
        missing=host.dependencies()
        if missing:
            issue(report,'ERROR' if existing else 'WARN','PYTHON_DEPENDENCIES','Missing Python modules: '+', '.join(missing),
                  'Fresh installer provisions dependencies after backup; review dependencies explicitly on existing systems')
    except Exception as exc:
        issue(report,'ERROR','DEPENDENCIES',redact(exc))
    for name in UNITS:
        try:
            state=host.unit(name);report['services'][name]=state
            if existing and name=='lyceumtv.service' and state.get('LoadState')!='loaded':
                issue(report,'ERROR','SERVICE_MISSING','Existing installation has no loaded lyceumtv.service','Recover service configuration; code-only upgrade cannot change system security')
        except Exception as exc:
            issue(report,'ERROR','SYSTEMD',f'{name}: {redact(exc)}')
    if existing:
        try:
            if not host.supervisor(root): raise ValueError('Supervisor identity mismatch')
        except Exception as exc:
            issue(report,'ERROR','SUPERVISOR','Running launcher supervisor required: '+redact(exc),'Recover the existing service before a code-only update')
    try:
        package_size=sum(p.stat().st_size for p in Path(package).rglob('*') if p.is_file() and '.git' not in p.parts)
        data_size=0;code_size=0
        if root.exists():
            for directory in (root/'data/current',root/'data/default',root/'data/imports/history',root/'public/media'):
                if directory.exists():
                    data_size+=sum(p.stat().st_size for p in directory.rglob('*') if p.is_file() and not p.is_symlink())
            for directory in (root/'server',root/'scripts',root/'public'):
                if directory.exists():
                    code_size+=sum(p.stat().st_size for p in directory.rglob('*') if p.is_file() and not p.is_symlink() and not p.is_relative_to(root/'public/media'))
        if host.free(root)<max(package_size*3,package_size*2+code_size)+64*1024*1024:
            issue(report,'ERROR','DISK','Insufficient installation/snapshot disk reserve')
        if host.free(backup_root if not existing else root/'data/backups')<data_size+64*1024*1024:
            issue(report,'ERROR','BACKUP_SPACE','Insufficient verified backup disk reserve')
        if backup_root.is_symlink() or any(p.is_symlink() for p in backup_root.parents) or backup_root.exists() and (not backup_root.is_dir() or backup_root.stat().st_mode & 0o077 or backup_root.stat().st_uid!=os.getuid()):
            issue(report,'ERROR','BACKUP_SECURITY','Backup location has unsafe type or permissions','Existing backup directory will not be chmod/chowned')
    except Exception as exc:
        issue(report,'ERROR','BACKUP_ACCESS',redact(exc))
    report['ok']=not any(i['level']=='ERROR' for i in report['issues'])
    return report


def prepare_missing(root,host,admin='admin',backup_root=Path('/var/backups/lyceumtv'),package=CODE_ROOT):
    report=diagnose(root,admin,host,backup_root,package)
    if any(i['level']=='ERROR' and i['code']!='MISSING_DIR' for i in report['issues']):
        raise ValueError('Unsafe existing state; see complete diagnostic report')
    app=host.account('lyceumtv')
    created=[]
    for rel in report['preparation']:
        if rel not in DIRECTORIES or not app:
            raise ValueError('Unapproved preparation operation')
        path=Path(root)/rel
        # Never race into chmod/chown of an already-existing directory.
        path.mkdir(mode=DIRECTORIES[rel],parents=False,exist_ok=False)
        host.chown_new(path,app)
        created.append(rel)
    return created


def verified_baseline(backup_root,host,root=None):
    if not backup_root.exists():
        backup_root.mkdir(mode=0o700,parents=False)
    if backup_root.is_symlink() or any(p.is_symlink() for p in backup_root.parents) or backup_root.stat().st_mode & 0o077 or backup_root.stat().st_uid!=os.getuid():
        raise ValueError('Unsafe existing backup directory')
    path=backup_root/('fresh-baseline-'+uuid.uuid4().hex+'.tar.gz')
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'wb') as output:
        with tarfile.open(fileobj=output,mode='w:gz') as archive:
            import io
            raw=b'{"previous_code":"absent","purpose":"fresh installation baseline"}'
            item=tarfile.TarInfo('baseline.json');item.size=len(raw);archive.addfile(item,io.BytesIO(raw))
            if root and root.exists():
                for rel in ('data','public/media'):
                    source=root/rel
                    if source.exists():
                        archive.add(source,arcname=rel,recursive=True)
        output.flush();os.fsync(output.fileno())
    verify_backup(path)
    return str(path)


def verify_backup(path):
    with gzip.open(path,'rb') as stream:
        while stream.read(1024*1024):
            pass
    with tarfile.open(path,'r:gz') as archive:
        archive.getmembers()
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(package,root,admin,host,backup_root,check_only=False,pi_host='192.168.0.18'):
    report={'stages':[],'install_performed':False}
    def stage(name,fn):
        report['stage']=name
        print(json.dumps({'stage':name,'status':'START'},ensure_ascii=False),flush=True)
        try:
            value=fn()
        except Exception as exc:
            report.setdefault('failed_stage',name)
            report['stages'].append({'stage':name,'status':'FAIL','error':redact(exc)})
            raise
        report['stages'].append({'stage':name,'status':'PASS'});return value
    try:
        integrity_error=None
        try:
            stage('RELEASE_INTEGRITY',lambda:verify(package))
        except Exception as exc:
            integrity_error=redact(exc)
        diag=stage('DIAGNOSE',lambda:diagnose(root,admin,host,backup_root,package))
        report['diagnostic']=diag
        if integrity_error:
            raise ValueError('Release integrity: '+integrity_error+'; target diagnostics collected')
        if check_only:
            report['status']='PASS' if diag['ok'] else 'FAIL';return report
        stage('SAFE_PREPARATION',lambda:prepare_missing(root,host,admin,backup_root,package))
        diag=stage('RECHECK',lambda:diagnose(root,admin,host,backup_root,package));report['diagnostic']=diag
        if not diag['ok']:
            raise ValueError('Pre-install diagnostics failed; all independent errors are listed')
        if diag['mode']=='upgrade':
            # Public staging copy is readable to the service only for this run;
            # do not relax the administrator home or existing application dirs.
            with tempfile.TemporaryDirectory(prefix='lyceumtv-installer-source-') as td:
                public=Path(td);public.chmod(0o755)
                manifest=json.loads((package/'PACKAGE_SHA256.json').read_text())
                for rel in [*manifest,'PACKAGE_SHA256.json']:
                    target=public/rel
                    parent=public
                    for part in Path(rel).parts[:-1]:
                        parent=parent/part
                        if not parent.exists():
                            parent.mkdir(mode=0o755);parent.chmod(0o755)
                    shutil.copyfile(package/rel,target);target.chmod(0o644)
                worker=public/'scripts/installer_upgrade.py'
                report['transaction_requested']=True
                output=stage('BACKUP_AND_CODE_TRANSACTION',lambda:host.run(['runuser','-u','lyceumtv','--','python3','-B',worker,'--package',public,'--root',root],timeout=3600))
                report['transaction']=output
            report.update(status='PASS',install_performed=True)
        else:
            report['backup']=stage('BACKUP',lambda:verified_baseline(backup_root,host,root))
            stage('VERIFY_BACKUP',lambda:verify_backup(report['backup']))
            report['system_backup']=stage('SYSTEM_BACKUP',lambda:host.run(['bash',package/'scripts/preinstall_system_backup.sh']))
            try:
                report['install_performed']=True
                stage('FRESH_INSTALL',lambda:host.run(['runuser','-u',admin,'--','env','LYCEUMTV_COORDINATED_INSTALL=1','bash',package/'scripts/install.sh',pi_host],timeout=900))
                stage('HEALTH',lambda:host.run(['python3','-B',package/'scripts/installer_upgrade.py','--health','--root',root],timeout=90))
                stage('READ_ONLY_UPDATE_TIMER',lambda:host.run(['bash',package/'scripts/install_official_update_check.sh']))
                report['status']='PASS'
            except Exception:
                stage('FRESH_CODE_ROLLBACK',lambda:quarantine_fresh_code(root,backup_root,host))
                raise
    except Exception as exc:
        report.update(status='FAIL',error=redact(exc))
    return report


def quarantine_fresh_code(root,backup_root,host):
    # No prior code exists. Keep all data/media and quarantine only software files.
    import update_transaction
    for unit in UNITS:
        if host.unit(unit).get('LoadState')=='loaded':
            host.run(['systemctl','stop',unit])
    destination=backup_root/('failed-fresh-code-'+uuid.uuid4().hex)
    destination.mkdir(mode=0o700)
    for rel in [*update_transaction.inventory(root),*(['launcher.py'] if (root/'launcher.py').is_file() else [])]:
        target=destination/rel;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.move(str(root/rel),str(target))
    return str(destination)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package',type=Path,default=CODE_ROOT)
    p.add_argument('--admin',default='admin')
    p.add_argument('--check-only',action='store_true')
    p.add_argument('--pi-host',default='192.168.0.18')
    args=p.parse_args()
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}',args.admin):
        p.error('Invalid admin account')
    import ipaddress
    ipaddress.IPv4Address(args.pi_host)
    if not hasattr(os,'geteuid') or os.geteuid()!=0:
        p.exit(1,'Run this diagnostic/coordinator through sudo; Windows uses the PowerShell launcher.\n')
    # Serialize installers without touching application data. Check-only is read-only.
    if not args.check_only:
        import fcntl
        lock=os.open('/run/lyceumtv-installer.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    result=execute(args.package.resolve(),Path('/opt/lyceumtv'),args.admin,Host(),Path('/var/backups/lyceumtv'),args.check_only,args.pi_host)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    sys.exit(0 if result['status']=='PASS' else 1)


if __name__=='__main__':
    main()
