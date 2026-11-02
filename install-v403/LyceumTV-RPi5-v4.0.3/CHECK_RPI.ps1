param(
    [string]$PiHost = "192.168.0.18",
    [string]$PiUser = "admin"
)

$ErrorActionPreference = "Stop"
$target = "${PiUser}@${PiHost}"

if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    throw "ssh not found. Install Windows OpenSSH Client."
}

Write-Host "Checking Raspberry Pi: $target"
Write-Host ""

& ssh $target @'
set +e
echo "=== API ==="
curl -fsS http://127.0.0.1:8080/api/health
echo
echo
echo "=== SERVICES ==="
for s in lyceumtv.service lyceumtv-kiosk.service lyceumtv-watchdog.timer nginx.service; do
  printf "%-28s " "$s"
  systemctl is-active "$s"
done
echo
echo "=== BOOT TARGET ==="
systemctl get-default
echo
echo "=== DISPLAY MODES ==="
for f in /sys/class/drm/*HDMI*/modes; do
  [ -f "$f" ] || continue
  echo "-- $f"
  head -n 8 "$f"
done
echo
echo "=== KIOSK LOG TAIL ==="
journalctl -u lyceumtv-kiosk.service -n 20 --no-pager || true
'@

if ($LASTEXITCODE -ne 0) {
    Write-Warning "One or more remote checks returned a non-zero exit code."
}

Write-Host ""
Write-Host "TV:       https://${PiHost}/"
Write-Host "Admin:    https://${PiHost}/admin"
Write-Host "Ops:      https://${PiHost}/ops"
Write-Host "UI debug: https://${PiHost}/?debug=1"
Write-Host "Mobile:   https://${PiHost}/mobile/"
