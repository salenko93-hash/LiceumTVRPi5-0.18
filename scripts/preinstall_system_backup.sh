#!/usr/bin/env bash
# Companion to the consistent /opt backup: preserve installer-owned system files.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo' >&2; exit 1; }
[[ -d /opt/lyceumtv ]] || { echo 'No previous system installation.'; exit 0; }
umask 077
install -d -o root -g root -m 700 /var/backups/lyceumtv
paths=()
shopt -s nullglob
for path in /etc/systemd/system/lyceumtv* /etc/lyceumtv /etc/nginx \
  /usr/local/lib/lyceumtv /usr/local/sbin/lyceumtv-* \
  /etc/pam.d/lyceumtv-kiosk /boot/firmware/cmdline.txt /boot/cmdline.txt \
  /etc/chromium/policies/managed/lyceumtv-kiosk.json \
  /etc/chromium-browser/policies/managed/lyceumtv-kiosk.json \
  /etc/systemd/system/default.target /etc/systemd/system/display-manager.service \
  /etc/systemd/system/lightdm.service /etc/systemd/system/gdm3.service \
  /etc/systemd/system/sddm.service /etc/systemd/system/getty.target.wants/getty@tty1.service; do
  [[ -e "$path" || -L "$path" ]] && paths+=("${path#/}")
done
[[ ${#paths[@]} -gt 0 ]] || { echo 'No previous system files to snapshot.'; exit 0; }
partial="$(mktemp /var/backups/lyceumtv/system-before-air-raid-XXXXXXXX.tar.gz.partial)"
tar -czf "$partial" -C / "${paths[@]}"
gzip -t "$partial"
tar -tzf "$partial" >/dev/null
archive="${partial%.partial}"
mv -- "$partial" "$archive"
sha256sum "$archive" > "$archive.sha256"
{
  systemctl get-default
  systemctl list-unit-files 'lyceumtv*' display-manager.service lightdm.service gdm3.service sddm.service getty@tty1.service --no-pager
  systemctl list-units 'lyceumtv*' --all --no-pager
} > "$archive.state.txt"
echo "Verified system snapshot: $archive"
