#!/usr/bin/env bash
# Local disposable Linux/systemd test only; never invokes the Pi apply script.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root in a disposable Linux test environment' >&2; exit 1; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work="$(mktemp -d /var/lib/lyceumtv-systemd-test.XXXXXXXX)"
echo "Test copy: $work (retained for inspection)"
mkdir "$work/app"
cp -r "$ROOT/server" "$ROOT/public" "$ROOT/scripts" "$ROOT/data" "$ROOT/tests" "$ROOT/tools" "$work/app/"
cp "$ROOT/launcher.py" "$ROOT/requirements.txt" "$ROOT/README.md" "$work/app/"
cp "$ROOT/"*.ps1 "$ROOT/"*.md "$ROOT/"*.py "$ROOT/"*.toml "$ROOT/requirements-dev.txt" "$work/app/"
find "$work/app" -type d -name __pycache__ -prune -exec rm -rf -- {} +
for file in "$work/app/scripts/install.sh" "$work/app/scripts/apply-systemd-hardening.sh" "$work/app/scripts/rollback-systemd-hardening.sh"; do bash -n "$file"; done
shellcheck "$work/app/scripts/apply-systemd-hardening.sh" "$work/app/scripts/rollback-systemd-hardening.sh" "$ROOT/tools/check_systemd_hardening.sh"
python3 - "$ROOT" "$work" <<'PY'
from pathlib import Path
import sys
root, work = map(Path, sys.argv[1:])
text = (root / 'scripts/install.sh').read_text().split('sudo tee /etc/systemd/system/lyceumtv.service >/dev/null <<EOF\n', 1)[1].split('\nEOF', 1)[0]
text = text.replace('$APP_USER', '65534').replace('$INSTALL_DIR', str(work / 'app'))
(work / 'lyceumtv.service').write_text(text + '\n')
dropins = work / 'lyceumtv.service.d'
dropins.mkdir()
(dropins / '50-lyceumtv-hardening.conf').write_bytes((root / 'scripts/systemd/50-lyceumtv-hardening.conf').read_bytes())
PY
systemd-analyze verify --man=no "$work/lyceumtv.service"
properties=()
while IFS= read -r line; do
  [[ -z "$line" || "$line" == \#* || "$line" == \[* ]] && continue
  properties+=(--property="$line")
done < "$ROOT/scripts/systemd/50-lyceumtv-hardening.conf"
chown -R nobody:nogroup "$work"
chmod 755 "$work"
systemd-run --wait --pipe --collect --unit="lyceumtv-local-test-$(basename "$work")" \
  --property=User=nobody --property=Group=nogroup --property=NoNewPrivileges=true \
  --property=UMask=0077 --property=TasksMax=128 --property=MemoryMax=768M \
  --property=PrivateTmp=true --property=ProtectHome=true --property=ProtectSystem=strict \
  --property="ReadWritePaths=$work" --property="WorkingDirectory=$work/app" \
  --setenv=PYTHONDONTWRITEBYTECODE=1 --setenv=PYTHONPATH=server:tests \
  --setenv=LYCEUMTV_SANDBOX_TEST=1 \
  "${properties[@]}" /usr/bin/python3 -B -m unittest discover -s tests -v
