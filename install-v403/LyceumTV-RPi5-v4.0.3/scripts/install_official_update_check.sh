#!/usr/bin/env bash
# Install only a read-only checker. Never installs a release automatically.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo' >&2; exit 1; }
cat >/etc/systemd/system/lyceumtv-official-check.service <<'UNIT'
[Unit]
Description=Check official LyceumTV GitHub release (never install)
Wants=network-online.target
After=network-online.target
[Service]
Type=oneshot
User=lyceumtv
Group=lyceumtv
ExecStart=/usr/bin/python3 -B /opt/lyceumtv/server/official_updates.py check
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
UNIT
cat >/etc/systemd/system/lyceumtv-official-check.timer <<'UNIT'
[Unit]
Description=Periodic read-only check of official LyceumTV releases
[Timer]
OnBootSec=5min
OnUnitActiveSec=6h
Persistent=true
Unit=lyceumtv-official-check.service
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now lyceumtv-official-check.timer
