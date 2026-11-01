"""Build the versioned public installation ZIP; optionally test the extracted ZIP."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from build_release import build

ROOT=Path(__file__).resolve().parents[1]

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    meta=json.loads((ROOT/'release.json').read_text())
    version=meta['version']
    if not meta.get('public_distribution') or meta.get('repository')!='salenko93-hash/LiceumTVRPi5-0.18' or not re.fullmatch(r'\d+\.\d+\.\d+',version):
        raise SystemExit('Build only from the reviewed official public distribution')
    folder='LyceumTV-RPi5-v'+version
    archive=build(ROOT/'dist'/(folder+'.zip'),folder)
    if args.verify:
        subprocess.run([sys.executable,'-B',str(ROOT/'tools/verify_air_raid_zip.py'),str(archive),'--tests'],check=True)
