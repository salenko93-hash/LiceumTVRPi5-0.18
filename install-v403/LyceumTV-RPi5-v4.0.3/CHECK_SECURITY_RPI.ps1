param(
    [string]$PiHost = "192.168.0.18",
    [string]$PiUser = "admin"
)
$ErrorActionPreference = "Stop"
$parsedIP = $null
if (-not [System.Net.IPAddress]::TryParse($PiHost, [ref]$parsedIP) -or $parsedIP.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { throw "PiHost must be an IPv4 address." }
if ($PiUser -notmatch '^[a-z_][a-z0-9_-]{0,31}$') { throw "Invalid Linux username." }
Write-Host "Read-only security checks on your Raspberry Pi. Enter sudo password if requested."
& ssh -t "${PiUser}@${PiHost}" "sudo /usr/local/sbin/lyceumtv-security-audit '$PiHost'"
if ($LASTEXITCODE -ne 0) { throw "Security checks reported failures; review the PASS/FAIL output above." }
