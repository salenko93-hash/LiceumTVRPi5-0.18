#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo' >&2; exit 1; }
mode="${1:-}"
backup="${2:-}"
[[ "$mode" == --rollback || "$mode" == --timeout || "$mode" == --commit ]] || exit 2
[[ "$backup" =~ ^/var/lib/lyceumtv-hardening/run\.[a-zA-Z0-9]+$ && -d "$backup" && ! -L "$backup" ]] || exit 2
[[ $(stat -c %u "$backup") == 0 && $(stat -c %a "$backup") == 700 ]] || exit 2
exec 9>/run/lyceumtv-hardening.lock
flock -x 9
target=/etc/systemd/system/lyceumtv.service.d/50-lyceumtv-hardening.conf
timer="lyceumtv-hardening-$(basename "$backup")"
if [[ "$mode" == --commit ]]; then
  [[ -f "$backup/pending" ]] || { echo 'No pending trial (possibly already rolled back)' >&2; exit 1; }
  systemctl is-active --quiet lyceumtv.service
  # The operator commits only after the documented functional checks.
  rm -- "$backup/pending"
  systemctl stop "$timer.timer"
  echo "Trial committed; manual rollback remains available: $backup"
  exit
fi
if [[ "$mode" == --timeout && ! -f "$backup/pending" ]]; then exit; fi
if [[ -f "$backup/previous.conf" ]]; then
  install -o root -g root -m 644 "$backup/previous.conf" "$target"
elif [[ -f "$backup/absent" ]]; then
  rm -f -- "$target"
else
  echo 'Incomplete backup; refusing rollback' >&2; exit 1
fi
systemctl daemon-reload
systemctl restart lyceumtv.service
rm -f -- "$backup/pending"
if [[ "$mode" != --timeout ]]; then systemctl stop "$timer.timer" || true; fi
echo "Restored previous drop-in from $backup"
