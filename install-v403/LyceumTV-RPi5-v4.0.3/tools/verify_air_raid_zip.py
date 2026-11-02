"""Verify the deliverable itself in a disposable directory; never deploy it."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--tests', action='store_true')
    args = parser.parse_args()
    digest = hashlib.sha256(args.archive.read_bytes()).hexdigest()
    sidecar = args.archive.with_name(args.archive.name + '.sha256').read_text().split()[0]
    if digest != sidecar:
        raise ValueError('External archive SHA-256 mismatch')
    with tempfile.TemporaryDirectory(prefix='lyceumtv-release-check-') as directory:
        with zipfile.ZipFile(args.archive) as archive:
            names = archive.namelist()
            if archive.testzip() or len(names) != len(set(names)):
                raise ValueError('Corrupt or duplicate archive members')
            folders = {PurePosixPath(n).parts[0] for n in names}
            if len(folders) != 1:
                raise ValueError('Expected one release folder')
            folder = next(iter(folders))
            for name in names:
                p = PurePosixPath(name)
                if p.is_absolute() or '..' in p.parts or '\\' in name:
                    raise ValueError('Unsafe archive member')
                rel = p.relative_to(folder).as_posix()
                if rel.startswith(('.preview-tools/', 'public/media/')) or rel in {
                    'data/config.json', 'data/runtime.json', 'data/control.json', 'data/calendar_override.json'
                } or rel.endswith(('.key', '.pem', '.pfx')):
                    raise ValueError('Private/runtime material in release: ' + rel)
                mode = archive.getinfo(name).external_attr >> 16
                if name.endswith('.sh') and mode & 0o777 != 0o755:
                    raise ValueError('Shell permissions missing')
            archive.extractall(directory)
        root = Path(directory) / folder
        command = [sys.executable, '-B', str(root / 'scripts/release_preflight.py'), '--root', str(root)]
        if args.tests:
            command.append('--tests')
        subprocess.run(command, cwd=root, check=True)
        manifest = json.loads((root / 'PACKAGE_SHA256.json').read_text())
        print(json.dumps({'status': 'PASS', 'archive': args.archive.name, 'sha256': digest,
                          'files': len(manifest), 'extracted_preflight': 'PASS',
                          'tests_on_extracted_package': args.tests}, ensure_ascii=False))


if __name__ == '__main__':
    main()
