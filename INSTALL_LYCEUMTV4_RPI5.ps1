param(
    [string]$PiHost = "192.168.0.18",
    [string]$PiUser = "admin",
    [switch]$NoReboot,
    [switch]$SkipBackup
)
$ErrorActionPreference = "Stop"
$parsedIP = $null
if (-not [System.Net.IPAddress]::TryParse($PiHost, [ref]$parsedIP) -or $parsedIP.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { throw 'PiHost must be an IPv4 address.' }
if ($PiUser -notmatch '^[a-z_][a-z0-9_-]{0,31}$') { throw 'Invalid Linux username.' }
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = "${PiUser}@${PiHost}"
if (-not (Test-Path (Join-Path $root 'public/tv4.html'))) { throw 'TV4 frontend is missing' }
if (-not (Test-Path (Join-Path $root 'INSTALL_TO_RPI5.ps1'))) { throw 'Base installer is missing' }
if (-not (Test-Path (Join-Path $root 'scripts/systemd/50-lyceumtv-hardening.conf'))) { throw 'Server hardening profile is missing' }
if (-not (Test-Path (Join-Path $root 'scripts/preinstall_backup.sh'))) { throw 'Pre-install backup helper is missing' }
$displayHtml = [IO.File]::ReadAllText((Join-Path $root 'public/tv4.html'))
if (-not $displayHtml.Contains('data-tv-production="true"') -or -not (Test-Path (Join-Path $root 'public/js/tv-display-runtime.js'))) { throw 'Production TV Display layout/runtime is missing. Use the complete TV-DISPLAY installation package.' }
Write-Host 'LyceumTV 4.0 IP018 | NEW TV DISPLAY | Raspberry Pi 5 installation' -ForegroundColor Cyan
Write-Host "Target: $target"
Write-Host 'TV4 will replace the main TV page; existing application services will restart.' -ForegroundColor Yellow
Write-Host 'New layout: 8 classes simultaneously, 2 tables; real timetable and calendar modes.'
Write-Host 'Current schedules/configuration should remain, but backup is required.'
$choice = Read-Host 'Type INSTALL to continue'
if ($choice -cne 'INSTALL') { Write-Host 'Cancelled'; exit 0 }
if (-not $SkipBackup) {
    Write-Host 'Backing up existing /opt/lyceumtv locally on Raspberry Pi...'
    # Encode reviewed script bytes to preserve quoting/newlines through Windows SSH.
    # sudo reads the password from the allocated terminal, not from script stdin.
    $backupScript = [System.IO.File]::ReadAllText((Join-Path $root 'scripts/preinstall_backup.sh')).Replace("`r`n", "`n")
    $encodedBackup = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($backupScript))
    $backupCommand = "sudo bash -o pipefail -c 'printf %s $encodedBackup | base64 --decode | bash'"
    & ssh -t $target $backupCommand
    if ($LASTEXITCODE -ne 0) { throw "Backup failed (SSH exit code $LASTEXITCODE). Installation stopped; see the preceding error." }
}
$argsList = @{ PiHost = $PiHost; PiUser = $PiUser; NoReboot = [bool]$NoReboot }
& (Join-Path $root 'INSTALL_TO_RPI5.ps1') @argsList
if (-not $?) { throw 'Installer reported a failure' }
Write-Host "TV4: https://${PiHost}/" -ForegroundColor Green
Write-Host "Previous TV: https://${PiHost}/legacy-tv"
Write-Host "Admin: https://${PiHost}/admin"
Write-Host 'IMPORTANT: On the actual TV, verify alarm, shelter schedule, minute of silence and sound.' -ForegroundColor Yellow
