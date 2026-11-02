#!/usr/bin/env bash
set -Eeuo pipefail
if [[ $EUID -ne 0 ]]; then
  echo "Run: sudo $0"
  exit 1
fi

systemctl disable --now lyceumtv-watchdog.timer 2>/dev/null || true
systemctl disable --now lyceumtv-kiosk.service 2>/dev/null || true
systemctl enable getty@tty1.service 2>/dev/null || true
systemctl set-default graphical.target

for svc in display-manager.service lightdm.service gdm3.service sddm.service; do
  systemctl unmask "$svc" 2>/dev/null || true
  if systemctl list-unit-files | grep -q "^${svc}"; then
    systemctl enable "$svc" 2>/dev/null || true
  fi
done

rm -f /etc/pam.d/lyceumtv-kiosk 2>/dev/null || true
rm -f /etc/chromium/policies/managed/lyceumtv-kiosk.json 2>/dev/null || true
rm -f /etc/chromium-browser/policies/managed/lyceumtv-kiosk.json 2>/dev/null || true

echo "Headless keyring-free kiosk disabled. Reboot to return to the graphical desktop."
