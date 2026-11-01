#!/usr/bin/env bash
# Full pre-install snapshot. Run only via the explicitly confirmed installer.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo' >&2; exit 1; }
umask 077
[[ -d /opt/lyceumtv ]] || { echo 'No existing installation; backup not needed.'; exit 0; }
exec 9>/run/lyceumtv-preinstall-backup.lock
flock -n 9 || { echo 'Another pre-install backup is running.' >&2; exit 1; }
if [[ -d /opt/lyceumtv/data ]]; then
  # Same preparation lock as the running OTA implementation. Keep its owner.
  if [[ ! -e /opt/lyceumtv/data/.locks ]]; then
    install -d -m 700 -o "$(stat -c %u /opt/lyceumtv/data)" -g "$(stat -c %g /opt/lyceumtv/data)" /opt/lyceumtv/data/.locks
  fi
  [[ ! -L /opt/lyceumtv/data/.locks && $(stat -c %u /opt/lyceumtv/data/.locks) == $(stat -c %u /opt/lyceumtv/data) && $(stat -c %a /opt/lyceumtv/data/.locks) == 700 ]] || { echo 'Unsafe existing lock directory.' >&2; exit 1; }
  if [[ ! -e /opt/lyceumtv/data/.locks/update-prepare.lock ]]; then
    (set -o noclobber; : > /opt/lyceumtv/data/.locks/update-prepare.lock)
    chown --reference=/opt/lyceumtv/data /opt/lyceumtv/data/.locks/update-prepare.lock
  fi
  [[ ! -L /opt/lyceumtv/data/.locks/update-prepare.lock && $(stat -c %u /opt/lyceumtv/data/.locks/update-prepare.lock) == $(stat -c %u /opt/lyceumtv/data) && $(stat -c %a /opt/lyceumtv/data/.locks/update-prepare.lock) == 600 ]] || { echo 'Unsafe existing OTA lock.' >&2; exit 1; }
  exec 8<>/opt/lyceumtv/data/.locks/update-prepare.lock
  flock -n 8 || { echo 'OTA preparation is running; retry after it finishes.' >&2; exit 1; }
fi
[[ ! -e /opt/lyceumtv/data/ota_pending ]] || { echo 'Finish OTA/recovery before installation.' >&2; exit 1; }
if [[ ! -e /var/backups/lyceumtv ]]; then install -d -o root -g root -m 700 /var/backups/lyceumtv; fi
[[ ! -L /var/backups/lyceumtv && $(stat -c %a /var/backups/lyceumtv) == 700 && $(stat -c %u /var/backups/lyceumtv) == 0 ]] || { echo 'Unsafe existing backup directory.' >&2; exit 1; }
units=(lyceumtv-watchdog.timer lyceumtv-backup.timer lyceumtv-mirror.timer
       lyceumtv-watchdog.service lyceumtv-backup.service lyceumtv-mirror.service lyceumtv.service)
loaded=()
active=()
for unit in "${units[@]}"; do
  load="$(systemctl show "$unit" -p LoadState --value)"
  [[ "$load" == loaded ]] || continue
  loaded+=("$unit")
  state="$(systemctl show "$unit" -p ActiveState --value)"
  case "$state" in
    active|activating) active+=("$unit");;
    inactive|failed) ;;
    *) echo "Service state is changing ($unit: $state); retry later." >&2; exit 1;;
  esac
done
restore() {
  local result=$? i
  trap - EXIT HUP INT TERM
  # Restore server first, then workers, then timers. Do not start inactive units.
  for ((i=${#active[@]}-1; i>=0; i--)); do
    if ! systemctl start "${active[i]}"; then
      echo "Failed to restore ${active[i]}; installation must not continue." >&2
      result=1
    fi
  done
  exit "$result"
}
trap restore EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
echo 'Temporarily stopping LyceumTV writers for a consistent backup...'
# Stop timers first, then their workers and finally the application server.
for unit in "${loaded[@]}"; do systemctl stop "$unit"; done
for unit in "${loaded[@]}"; do
  state="$(systemctl show "$unit" -p ActiveState --value)"
  [[ "$state" == inactive || "$state" == failed ]] || { echo "Still running: $unit" >&2; exit 1; }
done
partial="$(mktemp "/var/backups/lyceumtv/before-tv4-$(date +%Y%m%d-%H%M%S)-XXXXXX.tar.gz.partial")"
echo "Creating backup: $partial"
tar -czf "$partial" -C /opt lyceumtv
gzip -t "$partial"
tar -tzf "$partial" >/dev/null
archive="${partial%.partial}"
mv -- "$partial" "$archive"
echo "Verified backup: $archive"
# EXIT trap restores the previous active services even after a backup error.
