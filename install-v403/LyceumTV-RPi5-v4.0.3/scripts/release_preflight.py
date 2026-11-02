"""Read-only release integrity and target checks. Never starts the application."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import platform
import subprocess
import sys

LOCAL_METADATA = {'.idea', '.vscode', '.git', '__pycache__'}


def local_metadata(name):
    parts=PurePosixPath(name).parts
    return bool(parts) and (parts[0] in LOCAL_METADATA or parts[-1] in {'.DS_Store','Thumbs.db'})


def verify(root):
    root = Path(root).resolve()
    manifest = json.loads((root / 'PACKAGE_SHA256.json').read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError('Empty or invalid release manifest')
    required = {'server/engine.py', 'public/js/air-raid-display.js', 'public/css/air-raid-display.css',
                'scripts/install.sh', 'scripts/preinstall_backup.sh', 'scripts/preinstall_system_backup.sh', 'scripts/install_air_raid.sh',
                'scripts/release_preflight.py', 'VERIFY_PROJECT.py', 'scripts/installer.py',
                'scripts/installer_upgrade.py', 'scripts/runtime_storage.py', 'scripts/installer_launcher.ps1'}
    if not required <= manifest.keys():
        raise ValueError('Incomplete air-raid release')
    for name, expected in manifest.items():
        p = PurePosixPath(name)
        if local_metadata(name):
            raise ValueError('Local metadata must not be listed in release: ' + name)
        if p.is_absolute() or PureWindowsPath(name).drive or '..' in p.parts or '\\' in name:
            raise ValueError('Unsafe manifest path: ' + name)
        path = root / name
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Missing or unsafe file: ' + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('SHA-256 mismatch: ' + name)
    for path in root.rglob('*'):
        if local_metadata(path.relative_to(root).as_posix()):
            continue
        if path.is_symlink():
            raise ValueError('Symlink in release: ' + str(path))
        if path.is_file() and '__pycache__' not in path.parts and path.name != 'PACKAGE_SHA256.json':
            if path.relative_to(root).as_posix() not in manifest:
                raise ValueError('Unlisted release file: ' + str(path))
    for name in manifest:
        if name.endswith('.py'):
            ast.parse((root / name).read_text(encoding='utf-8-sig'), filename=name)
    print(f'PASS: {len(manifest)} release files verified, Python syntax valid')


def target_rpi():
    from installer import diagnose
    report=diagnose(admin=os.environ.get('SUDO_USER','admin'))
    print(json.dumps(report,ensure_ascii=False))
    if not report['ok']:
        raise ValueError('Target diagnostics failed; see all reported issues')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--target-rpi', action='store_true')
    parser.add_argument('--tests', action='store_true')
    args = parser.parse_args()
    verify(args.root)
    if args.target_rpi:
        target_rpi()
    if args.tests:
        subprocess.run([sys.executable, '-B', str(args.root / 'VERIFY_PROJECT.py')], cwd=args.root, check=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print('PREFLIGHT FAIL:', exc, file=sys.stderr)
        sys.exit(1)
