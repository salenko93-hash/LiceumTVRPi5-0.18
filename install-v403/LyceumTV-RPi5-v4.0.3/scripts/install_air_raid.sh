#!/usr/bin/env bash
# One coordinator for diagnostics, allowlisted preparation, backup and rollback.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PI_IP="${1:-192.168.0.18}"
if [[ $# -gt 0 ]]; then shift; fi
ADMIN_USER="${SUDO_USER:-$(id -un)}"
exec sudo python3 -B "$ROOT/scripts/installer.py" --package "$ROOT" --admin "$ADMIN_USER" --pi-host "$PI_IP" "$@"
