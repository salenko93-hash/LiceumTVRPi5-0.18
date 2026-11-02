"""Validated, atomic content storage for the optional media dashboard."""
from pathlib import Path
import json
import os
import threading

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / 'data' / 'media_dashboard.json'
LOCK = threading.RLock()
FIELDS = {'main_title': 120, 'main_text': 360, 'main_meta': 140,
          'announcements': 360, 'today': 360, 'achievements': 360,
          'media_url': 400, 'media_type': 16, 'media_caption': 140}
DEFAULT = {'main_title': '', 'main_text': '', 'main_meta': '',
           'announcements': '', 'today': '', 'achievements': '',
           'media_url': '', 'media_type': 'image', 'media_caption': ''}

def load():
    with LOCK:
        try:
            raw = json.loads(PATH.read_text(encoding='utf-8'))
            if not isinstance(raw, dict): return DEFAULT.copy()
        except (OSError, ValueError):
            return DEFAULT.copy()
        return {k: str(raw.get(k, v))[:FIELDS[k]] for k,v in DEFAULT.items()}

def save(payload):
    if not isinstance(payload, dict): raise ValueError('Expected JSON object')
    if set(payload) - set(FIELDS): raise ValueError('Unknown fields')
    clean = {k: str(payload.get(k, v)).replace('\x00','')[:FIELDS[k]] for k,v in DEFAULT.items()}
    if clean['media_type'] not in ('image','video','none'):
        raise ValueError('Неприпустимий тип медіа')
    url = clean['media_url'].strip()
    if url and (not url.startswith('/media/') or url.startswith('//') or '..' in url.split('/') or '?' in url or '#' in url or '\\' in url):
        raise ValueError('Медіа має бути локальним шляхом /media/...')
    with LOCK:
        PATH.parent.mkdir(parents=True,exist_ok=True)
        import tempfile
        fd, name = tempfile.mkstemp(dir=PATH.parent,prefix='.media-dashboard-',suffix='.tmp')
        try:
            os.chmod(name,0o600)
            with os.fdopen(fd,'w',encoding='utf-8') as out:
                json.dump(clean,out,ensure_ascii=False,indent=2)
                out.flush(); os.fsync(out.fileno())
            os.replace(name,PATH)
        finally:
            if os.path.exists(name): os.unlink(name)
    return clean
