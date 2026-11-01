param(
    [string]$PiHost = '192.168.0.18',
    [string]$PiUser = 'admin'
)
$ErrorActionPreference = 'Stop'
$parsedIP = $null
if (-not [Net.IPAddress]::TryParse($PiHost, [ref]$parsedIP) -or $parsedIP.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) { throw 'PiHost must be IPv4.' }
if ($PiUser -notmatch '^[a-z_][a-z0-9_-]{0,31}$') { throw 'Invalid Linux username.' }
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($cmd in @('python','ssh','scp')) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "$cmd is required." }
}
# Fail before SSH or service changes if any extracted file was altered.
& python -B (Join-Path $root 'scripts/release_preflight.py') --root $root
if ($LASTEXITCODE -ne 0) { throw 'Local package preflight failed.' }
$target = "${PiUser}@${PiHost}"
$remote = "/home/$PiUser/LyceumTV-air-raid-$([guid]::NewGuid().ToString('N'))"
Write-Host "Target: $target. Native Pi tests run before backup/install; no automatic reboot."
if ((Read-Host 'Type INSTALL to install this reviewed release') -cne 'INSTALL') { Write-Host 'Cancelled'; exit 0 }
& ssh $target "mkdir -m 700 '$remote'"
if ($LASTEXITCODE -ne 0) { throw 'SSH failed.' }
$items = Get-ChildItem -LiteralPath $root -Force | ForEach-Object { $_.FullName }
& scp -r @items "${target}:$remote/"
if ($LASTEXITCODE -ne 0) { throw 'Upload failed; installation not started.' }
& ssh -t $target "cd '$remote' && bash scripts/install_air_raid.sh '$PiHost'"
if ($LASTEXITCODE -ne 0) { throw 'Pi preflight/backup/install failed. Inspect output; use docs/AIR_RAID_RPI5_RELEASE.md for recovery.' }
Write-Host 'Verify local health, HDMI display and physical audio. No reboot was requested.'
