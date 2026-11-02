#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo $0 <kiosk-user>" >&2
  exit 1
fi

KIOSK_USER="${1:-pi}"
KIOSK_HOME="$(getent passwd "$KIOSK_USER" | cut -d: -f6)"
if [[ -z "$KIOSK_HOME" || ! -d "$KIOSK_HOME" ]]; then
  echo "Cannot resolve home directory for user: $KIOSK_USER" >&2
  exit 1
fi

PROFILE_DIR="$KIOSK_HOME/.config/lyceumtv-kiosk-chromium"

echo "[keyring-free] Preparing isolated Chromium profile..."
install -d -m 700 -o "$KIOSK_USER" -g "$KIOSK_USER" "$PROFILE_DIR"
rm -f \
  "$PROFILE_DIR/SingletonLock" \
  "$PROFILE_DIR/SingletonCookie" \
  "$PROFILE_DIR/SingletonSocket" \
  "$PROFILE_DIR/Default/Login Data" \
  "$PROFILE_DIR/Default/Login Data-journal" 2>/dev/null || true

# Chromium on Debian/Raspberry Pi OS can read managed policies from one of
# these locations depending on the package name. Write both; unknown paths
# are harmless.
POLICY_JSON='{
  "PasswordManagerEnabled": false,
  "BrowserSignin": 0,
  "SyncDisabled": true,
  "AutofillAddressEnabled": false,
  "AutofillCreditCardEnabled": false,
  "PromotionalTabsEnabled": false,
  "DefaultBrowserSettingEnabled": false
}'
for dir in /etc/chromium/policies/managed /etc/chromium-browser/policies/managed; do
  install -d -m 755 "$dir"
  printf '%s\n' "$POLICY_JSON" >"$dir/lyceumtv-kiosk.json"
  chmod 644 "$dir/lyceumtv-kiosk.json"
done

# Use a dedicated PAM stack for the kiosk. The normal "login" PAM stack on
# desktop images can start desktop-keyring-module, which can create the locked
# "Default Keyring" seen on screen. We need pam_systemd for a real logind
# session/seat, but deliberately do not start a desktop keyring module.
cat >/etc/pam.d/lyceumtv-kiosk <<'PAM'
#%PAM-1.0
auth       required   pam_permit.so
account    required   pam_permit.so
session    required   pam_env.so
session    required   pam_limits.so
session    optional   pam_systemd.so
PAM
chmod 644 /etc/pam.d/lyceumtv-kiosk

echo "[keyring-free] Forcing headless kiosk boot..."
for svc in display-manager.service lightdm.service gdm3.service sddm.service; do
  systemctl disable "$svc" >/dev/null 2>&1 || true
  systemctl mask "$svc" >/dev/null 2>&1 || true
done
systemctl disable getty@tty1.service >/dev/null 2>&1 || true
systemctl set-default multi-user.target

echo "[keyring-free] Chromium will use --password-store=basic."
echo "[keyring-free] Desktop/login manager is masked; Cage kiosk owns tty1 after reboot."
