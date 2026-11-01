#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $EUID -eq 0 ]]; then
  echo "Запускайте install.sh звичайним користувачем із sudo доступом."
  exit 1
fi

[[ "${LYCEUMTV_COORDINATED_INSTALL:-}" == 1 ]] || {
  echo 'Use INSTALL_AIR_RAID_RPI5.ps1 or scripts/install_air_raid.sh (verified backup required).' >&2
  exit 1
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="$(id -un)"
GROUP_NAME="$(id -gn)"
INSTALL_DIR="/opt/lyceumtv"
APP_USER="lyceumtv"
KIOSK_USER="lyceumtv-kiosk"
KIOSK_WAS_ACTIVE="$(systemctl is-active lyceumtv-kiosk.service 2>/dev/null || true)"
PI_IP="${1:-192.168.0.18}"
python3 -c 'import ipaddress,sys; ipaddress.IPv4Address(sys.argv[1])' "$PI_IP"

echo "[1/8] Installing packages..."
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3 python3-openpyxl python3-qrcode rsync curl cage dbus-user-session \
  fonts-dejavu-core fonts-noto-core fonts-noto-color-emoji nginx openssl

if ! command -v chromium >/dev/null 2>&1 && ! command -v chromium-browser >/dev/null 2>&1; then
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y chromium \
    || sudo DEBIAN_FRONTEND=noninteractive apt-get install -y chromium-browser
fi

echo "[2/8] Preparing fresh service accounts and new directories..."
[[ ! -f "$INSTALL_DIR/server/app.py" ]] || { echo 'Existing installations must use the code transaction, not full provisioning.' >&2; exit 1; }
for account in "$APP_USER" "$KIOSK_USER"; do
  if ! id "$account" >/dev/null 2>&1; then
    sudo useradd --system --user-group --home-dir "/var/lib/$account" --create-home --shell /usr/sbin/nologin "$account"
  fi
  if [[ $(id -u "$account") -eq 0 ]] || id -nG "$account" | tr ' ' '\n' | grep -Eq '^(root|sudo|wheel|adm|docker|lxd|disk|shadow)$'; then
    echo "Refusing privileged service account: $account" >&2; exit 1
  fi
  [[ $(getent passwd "$account" | cut -d: -f7) == /usr/sbin/nologin ]] || { echo 'Service account shell needs security review.' >&2; exit 1; }
done
KIOSK_UID="$(id -u "$KIOSK_USER")"
sudo python3 "$ROOT/scripts/runtime_storage.py" --prepare --root "$INSTALL_DIR"

echo "[3/8] Installing verified software; preserving existing data..."
sudo rsync -a --no-perms --delete --chown="$APP_USER:$APP_USER" \
  --exclude '.git' --exclude '.idea' --exclude '.vscode' --exclude '__pycache__' \
  --exclude '.DS_Store' --exclude 'Thumbs.db' \
  --exclude 'data/' --exclude 'public/media/' --exclude 'docs/' \
  --exclude 'tests/' --exclude 'tools/' --exclude 'cloud/' \
  "$ROOT/" "$INSTALL_DIR/"
sudo install -o "$APP_USER" -g "$APP_USER" -m 644 "$ROOT/data/config.example.json" "$INSTALL_DIR/data/config.example.json"
if ! sudo test -e "$INSTALL_DIR/data/default"; then
  sudo install -d -o "$APP_USER" -g "$APP_USER" -m 700 "$INSTALL_DIR/data/default"
  sudo rsync -r --chown="$APP_USER:$APP_USER" "$ROOT/data/default/" "$INSTALL_DIR/data/default/"
fi
for helper in "$ROOT"/scripts/*.sh; do
  sudo install -o "$APP_USER" -g "$APP_USER" -m 755 "$helper" "$INSTALL_DIR/scripts/"
done
sudo -u "$APP_USER" python3 -B "$INSTALL_DIR/scripts/runtime_storage.py" --initialize --root "$INSTALL_DIR"
# No recursive chmod/chown, calendar migration or rewriting existing config.
sudo install -d -o root -g root -m 755 /usr/local/lib/lyceumtv
sudo install -o root -g root -m 755 "$ROOT/scripts/watchdog.sh" /usr/local/lib/lyceumtv/watchdog.sh
sudo install -o root -g root -m 755 "$ROOT/scripts/launch-kiosk.sh" /usr/local/lib/lyceumtv/launch-kiosk.sh
sudo install -o root -g root -m 755 "$ROOT/scripts/security_audit.sh" /usr/local/sbin/lyceumtv-security-audit
sudo install -o root -g root -m 755 "$ROOT/scripts/show_keys.py" /usr/local/sbin/lyceumtv-show-keys
sudo bash "$ROOT/scripts/configure_https.sh" "$PI_IP"
sudo install -o "$USER_NAME" -g "$GROUP_NAME" -m 644 /etc/lyceumtv/tls/ca.crt "$HOME/lyceumtv-ca.crt"

echo "[4/8] Preparing kiosk user..."
for grp in video render input audio; do
  if getent group "$grp" >/dev/null 2>&1; then
    sudo usermod -aG "$grp" "$KIOSK_USER"
  fi
done
sudo bash "$ROOT/scripts/prepare-keyring-free-kiosk.sh" "$KIOSK_USER"

echo "[5/8] Installing systemd services..."
sudo tee /etc/systemd/system/lyceumtv.service >/dev/null <<EOF
[Unit]
Description=LyceumTV 3.6.1
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
NoNewPrivileges=true
UMask=0077
TasksMax=128
MemoryMax=768M
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=$INSTALL_DIR
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 $INSTALL_DIR/launcher.py
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# Server-only sandbox; kiosk and its device/audio/session permissions stay separate.
sudo install -d -o root -g root -m 755 /etc/systemd/system/lyceumtv.service.d
sudo install -o root -g root -m 644 "$ROOT/scripts/systemd/50-lyceumtv-hardening.conf" /etc/systemd/system/lyceumtv.service.d/50-lyceumtv-hardening.conf
sudo systemd-analyze verify --man=no /etc/systemd/system/lyceumtv.service

sudo tee /etc/systemd/system/lyceumtv-kiosk.service >/dev/null <<EOF
[Unit]
Description=LyceumTV Adaptive TV Kiosk
After=network-online.target systemd-user-sessions.service lyceumtv.service
Wants=network-online.target lyceumtv.service
Requires=user-runtime-dir@$KIOSK_UID.service
After=user-runtime-dir@$KIOSK_UID.service
Conflicts=getty@tty1.service
StartLimitIntervalSec=0

[Service]
Type=simple
User=$KIOSK_USER
Group=$KIOSK_USER
UMask=0077
ProtectHome=tmpfs
BindPaths=/run/user/$KIOSK_UID
PAMName=lyceumtv-kiosk
TTYPath=/dev/tty1
StandardInput=tty-force
StandardOutput=journal
StandardError=journal
TTYReset=yes
TTYVHangup=yes
TTYVTDisallocate=yes
UtmpIdentifier=tty1
UtmpMode=user
Environment=XDG_RUNTIME_DIR=/run/user/$KIOSK_UID
ExecStart=/usr/local/lib/lyceumtv/launch-kiosk.sh
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# The base unit now includes the runtime fix; remove only our temporary 3.6.0 hotfix.
sudo rm -f /etc/systemd/system/lyceumtv-kiosk.service.d/30-lyceumtv-runtime.conf

sudo tee /etc/systemd/system/lyceumtv-watchdog.service >/dev/null <<EOF
[Unit]
Description=LyceumTV watchdog

[Service]
Type=oneshot
User=root
RuntimeDirectory=lyceumtv-watchdog
RuntimeDirectoryMode=0700
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ExecStart=/usr/local/lib/lyceumtv/watchdog.sh
EOF

sudo tee /etc/systemd/system/lyceumtv-watchdog.timer >/dev/null <<'EOF'
[Unit]
Description=Run LyceumTV watchdog every 20 seconds

[Timer]
OnBootSec=45
OnUnitActiveSec=20
AccuracySec=3
Unit=lyceumtv-watchdog.service

[Install]
WantedBy=timers.target
EOF

sudo tee /etc/systemd/system/lyceumtv-backup.service >/dev/null <<EOF
[Unit]
Description=LyceumTV daily Smart Campus backup
After=lyceumtv.service

[Service]
Type=oneshot
User=$APP_USER
Group=$APP_USER
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ExecStart=$INSTALL_DIR/scripts/daily_backup.sh
EOF

sudo tee /etc/systemd/system/lyceumtv-backup.timer >/dev/null <<'EOF'
[Unit]
Description=LyceumTV daily backup timer

[Timer]
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=300
Unit=lyceumtv-backup.service

[Install]
WantedBy=timers.target
EOF

sudo tee /etc/systemd/system/lyceumtv-mirror.service >/dev/null <<EOF
[Unit]
Description=LyceumTV Cloud Mirror sync
After=network-online.target lyceumtv.service
Wants=network-online.target

[Service]
Type=oneshot
User=$APP_USER
Group=$APP_USER
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ExecStart=$INSTALL_DIR/scripts/cloud_mirror.sh
EOF

sudo tee /etc/systemd/system/lyceumtv-mirror.timer >/dev/null <<'EOF'
[Unit]
Description=LyceumTV Cloud Mirror timer

[Timer]
OnBootSec=120
OnUnitActiveSec=60
Persistent=true
Unit=lyceumtv-mirror.service

[Install]
WantedBy=timers.target
EOF

echo "[6/8] Confirming keyring-free headless kiosk boot..."
# prepare-keyring-free-kiosk.sh already masks Desktop/Login Manager and sets
# multi-user.target. Do not stop the current desktop session mid-install;
# the next reboot enters Cage + Chromium directly.
CMDLINE=""
if [[ -f /boot/firmware/cmdline.txt ]]; then
  CMDLINE=/boot/firmware/cmdline.txt
elif [[ -f /boot/cmdline.txt ]]; then
  CMDLINE=/boot/cmdline.txt
fi
if [[ -n "$CMDLINE" ]]; then
  sudo grep -q 'consoleblank=0' "$CMDLINE" || sudo sed -i '1 s/$/ consoleblank=0/' "$CMDLINE"
  sudo grep -q 'vt.global_cursor_default=0' "$CMDLINE" || sudo sed -i '1 s/$/ vt.global_cursor_default=0/' "$CMDLINE"
fi

echo "[7/8] Enabling services..."
sudo systemctl daemon-reload
sudo systemctl enable lyceumtv.service
sudo systemctl restart lyceumtv.service
sudo systemctl enable lyceumtv-kiosk.service
if [[ "$KIOSK_WAS_ACTIVE" == active ]]; then sudo systemctl restart lyceumtv-kiosk.service; fi
sudo systemctl enable --now lyceumtv-watchdog.timer
sudo systemctl enable --now lyceumtv-backup.timer
sudo systemctl enable --now lyceumtv-mirror.timer

echo "[8/8] Health check..."
sudo -u "$APP_USER" python3 -B "$INSTALL_DIR/scripts/installer_upgrade.py" --root "$INSTALL_DIR" --health

echo
echo "LyceumTV 3.6.1 installed."
echo "TV:    http://127.0.0.1:8080/"
echo "Admin:   https://$PI_IP/admin"
echo "Ops:     https://$PI_IP/ops"
echo "Teacher: https://$PI_IP/teacher"
echo "Campus:  https://$PI_IP/campus/"
echo "Trust certificate: /etc/lyceumtv/tls/ca.crt (copy using SSH)"
echo "Role keys are private in /opt/lyceumtv/data/config.json; retrieve using sudo via SSH."
echo "The next reboot starts directly into Cage + Chromium, without Desktop or Default Keyring prompt."
echo
echo "Reboot:"
echo "  sudo reboot"
echo
echo "Status after reboot:"
echo "  systemctl status lyceumtv --no-pager"
echo "  systemctl status lyceumtv-kiosk --no-pager"
echo "  systemctl status lyceumtv-watchdog.timer --no-pager"
