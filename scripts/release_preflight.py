"""Read-only release integrity and target checks. Never starts the application."""
import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import platform
import subprocess
import sys


def verify(root):
    root = Path(root).resolve()
    manifest = json.loads((root / 'PACKAGE_SHA256.json').read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError('Empty or invalid release manifest')
    required = {'server/engine.py', 'public/js/air-raid-display.js', 'public/css/air-raid-display.css',
                'scripts/install.sh', 'scripts/preinstall_backup.sh', 'scripts/preinstall_system_backup.sh', 'scripts/install_air_raid.sh',
                'scripts/release_preflight.py', 'VERIFY_PROJECT.py'}
    if not required <= manifest.keys():
        raise ValueError('Incomplete air-raid release')
    for name, expected in manifest.items():
        p = PurePosixPath(name)
        if p.is_absolute() or PureWindowsPath(name).drive or '..' in p.parts or '\\' in name:
            raise ValueError('Unsafe manifest path: ' + name)
        path = root / name
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Missing or unsafe file: ' + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('SHA-256 mismatch: ' + name)
    for path in root.rglob('*'):
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
    if sys.platform != 'linux' or platform.machine() not in {'aarch64', 'arm64'}:
        raise ValueError('Requires Linux ARM64 Raspberry Pi 5')
    model = Path('/proc/device-tree/model').read_text().rstrip('\0')
    if 'Raspberry Pi 5' not in model:
        raise ValueError('Target is not Raspberry Pi 5: ' + model)
    subprocess.run(['systemctl', '--version'], check=True, stdout=subprocess.DEVNULL)
    if Path('/opt/lyceumtv/data/ota_pending').exists():
        raise ValueError('Pending OTA/recovery: installation refused')
    print('PASS: Raspberry Pi 5 ARM64 target; no pending OTA')


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
