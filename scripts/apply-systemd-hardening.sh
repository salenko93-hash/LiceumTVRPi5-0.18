#!/usr/bin/env bash
# No live changes unless --apply is explicitly supplied on the target machine.
set -Eeuo pipefail
mode="${1:---check}"
[[ "$mode" == --check || "$mode" == --apply ]] || { echo 'Usage: sudo bash apply-systemd-hardening.sh [--check|--apply]' >&2; exit 2; }
[[ $EUID -eq 0 ]] || { echo 'Run with sudo on the target Pi' >&2; exit 1; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
candidate="$ROOT/scripts/systemd/50-lyceumtv-hardening.conf"
target=/etc/systemd/system/lyceumtv.service.d/50-lyceumtv-hardening.conf
exec 9>/run/lyceumtv-hardening.lock
flock -n 9 || { echo 'Another hardening operation is running' >&2; exit 1; }
[[ -f "$candidate" && ! -L "$target" ]]
[[ $(systemctl show lyceumtv.service -p User --value) == lyceumtv ]]
[[ $(systemctl show lyceumtv.service -p WorkingDirectory --value) == /opt/lyceumtv ]]
systemctl is-active --quiet lyceumtv.service
# Hold the same lock as OTA preparation until restart and health verification end.
install -d -o lyceumtv -g lyceumtv -m 700 /opt/lyceumtv/data/.locks
touch /opt/lyceumtv/data/.locks/update-prepare.lock
chown lyceumtv:lyceumtv /opt/lyceumtv/data/.locks/update-prepare.lock
chmod 600 /opt/lyceumtv/data/.locks/update-prepare.lock
exec 8>/opt/lyceumtv/data/.locks/update-prepare.lock
flock -n 8 || { echo 'OTA preparation is running' >&2; exit 1; }
[[ ! -e /opt/lyceumtv/data/ota_pending ]] || { echo 'Finish OTA/recovery first' >&2; exit 1; }
[[ $(getconf LONG_BIT) == 64 && $(uname -m) == aarch64 ]] || { echo 'This profile requires the reviewed 64-bit Pi OS (aarch64)' >&2; exit 1; }
systemd-analyze --version
stage="$(mktemp -d)"
trap 'rm -rf -- "$stage"' EXIT
fragment="$(systemctl show lyceumtv.service -p FragmentPath --value)"
cp -- "$fragment" "$stage/lyceumtv.service"
mkdir "$stage/lyceumtv.service.d"
# Include the effective vendor/runtime/admin drop-ins, in their effective order.
read -r -a dropins <<< "$(systemctl show lyceumtv.service -p DropInPaths --value)"
for file in "${dropins[@]}"; do cp -- "$file" "$stage/lyceumtv.service.d/$(basename "$file")"; done
cp -- "$candidate" "$stage/lyceumtv.service.d/50-lyceumtv-hardening.conf"
# Treat diagnostics (including unknown directives) as a failed compatibility check.
if ! systemd-analyze verify --man=no "$stage/lyceumtv.service" >"$stage/verify.log" 2>&1; then cat "$stage/verify.log"; exit 1; fi
if [[ -s "$stage/verify.log" ]]; then cat "$stage/verify.log"; exit 1; fi
cat "$candidate"
[[ "$mode" == --apply ]] || { echo 'Verified syntax; no service configuration changed. Runtime acceptance still required.'; exit; }
install -d -o root -g root -m 700 /var/lib/lyceumtv-hardening
# Refuse overlapping uncommitted trials.
for pending in /var/lib/lyceumtv-hardening/run.*/pending; do
  [[ ! -e "$pending" ]] || { echo "Resolve previous trial: $pending" >&2; exit 1; }
done
backup="$(mktemp -d /var/lib/lyceumtv-hardening/run.XXXXXXXX)"
if [[ -f "$target" ]]; then cp -- "$target" "$backup/previous.conf"; else touch "$backup/absent"; fi
install -o root -g root -m 700 "$ROOT/scripts/rollback-systemd-hardening.sh" "$backup/rollback.sh"
systemctl cat lyceumtv.service >"$backup/before.unit"
systemd-analyze security --no-pager lyceumtv.service >"$backup/before.security" 2>&1
touch "$backup/pending"
timer="lyceumtv-hardening-$(basename "$backup")"
# Independent rollback survives SSH loss. Backup/helper are outside app-owned OTA paths.
if ! systemd-run --unit="$timer" --on-active=15min --timer-property=AccuracySec=1s /bin/bash "$backup/rollback.sh" --timeout "$backup"; then
  rm -- "$backup/pending"
  exit 1
fi
failed() {
  trap - ERR INT TERM
  flock -u 8
  flock -u 9
  /bin/bash "$backup/rollback.sh" --rollback "$backup"
  exit 1
}
trap failed ERR INT TERM
install -d -o root -g root -m 755 "$(dirname "$target")"
install -o root -g root -m 644 "$candidate" "$target"
systemctl daemon-reload
systemctl restart lyceumtv.service
healthy=false
for _ in {1..30}; do
  if systemctl is-active --quiet lyceumtv.service && curl -fsS --max-time 2 http://127.0.0.1:8080/api/health | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("ok") is True and d.get("service")=="LyceumTV"'; then healthy=true; break; fi
  sleep 1
done
[[ "$healthy" == true ]]
systemd-analyze security --no-pager lyceumtv.service >"$backup/after.security" 2>&1
trap - ERR INT TERM
echo "15-minute trial active. Check functionality before committing. Backup: $backup"
echo "Commit: sudo bash $backup/rollback.sh --commit $backup"
echo "Rollback: sudo bash $backup/rollback.sh --rollback $backup"
