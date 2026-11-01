#!/usr/bin/env bash
# Explicitly invoked installation only; all gates run before service changes.
set -Eeuo pipefail
[[ $EUID -ne 0 ]] || { echo 'Run as a normal user with sudo access.' >&2; exit 1; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PI_IP="${1:-192.168.0.18}"
python3 -B "$ROOT/scripts/release_preflight.py" --root "$ROOT" --target-rpi --tests
# No skip-backup option on this release entrypoint.
sudo bash "$ROOT/scripts/preinstall_backup.sh"
sudo bash "$ROOT/scripts/preinstall_system_backup.sh"
bash "$ROOT/scripts/install.sh" "$PI_IP"
sudo bash "$ROOT/scripts/install_official_update_check.sh"
python3 - <<'PY'
import json
from urllib.request import build_opener, ProxyHandler
opener = build_opener(ProxyHandler({}))
with opener.open('http://127.0.0.1:8080/api/health', timeout=8) as response:
    health = json.load(response)
if not health.get('ok') or health.get('version') != '3.6.1':
    raise SystemExit('Post-install health failed; use the verified backup for recovery')
print('PASS: installed server health/version')
PY
echo 'Installation finished without reboot. Verify HDMI/sound and then reboot manually.'
