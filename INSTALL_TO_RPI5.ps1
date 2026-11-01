param(
    [string]$PiHost = "192.168.0.18",
    [string]$PiUser = "admin",
    [switch]$NoReboot
)

$ErrorActionPreference = "Stop"
$parsedIP = $null
if (-not [System.Net.IPAddress]::TryParse($PiHost, [ref]$parsedIP) -or $parsedIP.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { throw "PiHost must be an IPv4 address." }
if ($PiUser -notmatch '^[a-z_][a-z0-9_-]{0,31}$') { throw "Invalid Linux username." }
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = "${PiUser}@${PiHost}"
$remote = "/home/$PiUser/LyceumTV-3.6.1-upload-$([guid]::NewGuid().ToString('N'))"

Write-Host "================================================="
Write-Host " LyceumTV 3.6.1 RASPBERRY PI 5 PRODUCTION"
Write-Host " Raspberry Pi: $target"
Write-Host "================================================="

foreach ($cmd in @("ssh", "scp")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        throw "$cmd not found. Install Windows OpenSSH Client."
    }
}

Write-Host "[1/5] Checking SSH and preparing remote folder..."
& ssh $target "mkdir -p '$remote'"
if ($LASTEXITCODE -ne 0) {
    throw "SSH connection failed. Check Pi IP, username, password/key, and SSH service."
}

$required = @(
    "server",
    "public",
    "data",
    "scripts",
    "README.md",
    "launcher.py"
)
foreach ($item in $required) {
    if (-not (Test-Path (Join-Path $root $item))) {
        throw "Missing required project item: $item"
    }
}

Write-Host "[2/5] Uploading project..."
$uploadItems = @(
    (Join-Path $root "server"),
    (Join-Path $root "public"),
    (Join-Path $root "data"),
    (Join-Path $root "scripts"),
    (Join-Path $root "README.md"),
    (Join-Path $root "launcher.py")
)
$gitignore = Join-Path $root ".gitignore"
if (Test-Path $gitignore) {
    $uploadItems += $gitignore
}

& scp -r @uploadItems "${target}:$remote/"
if ($LASTEXITCODE -ne 0) {
    throw "Upload failed."
}

Write-Host "[3/5] Running Raspberry Pi installer..."
Write-Host "Enter the Raspberry Pi user password if sudo requests it."
& ssh -t $target "cd '$remote' && chmod +x scripts/*.sh && ./scripts/install.sh '$PiHost'"
if ($LASTEXITCODE -ne 0) {
    throw "Remote install failed."
}

Write-Host "[4/5] Trusting this Pi HTTPS certificate and checking health..."
$certificatePath = Join-Path $env:TEMP ("lyceumtv-ca-" + [guid]::NewGuid().ToString("N") + ".crt")
try {
    & scp "${target}:lyceumtv-ca.crt" $certificatePath
    if ($LASTEXITCODE -ne 0) { throw "Cannot retrieve Pi CA through authenticated SSH." }
    $certificate = Import-Certificate -FilePath $certificatePath -CertStoreLocation "Cert:\CurrentUser\Root"
    Write-Host "Pi certificate trusted for the current Windows user: $($certificate.Thumbprint)"
}
finally {
    Remove-Item $certificatePath -ErrorAction SilentlyContinue
}
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$health = $null
for ($attempt = 1; $attempt -le 30; $attempt++) {
    try {
        $health = Invoke-RestMethod `
            -Uri "https://${PiHost}/api/health" `
            -TimeoutSec 3 `
            -ErrorAction Stop
        break
    }
    catch {
        Write-Host "Waiting for LyceumTV ($attempt/30)..."
        Start-Sleep -Seconds 2
    }
}

if ($null -eq $health) {
    Write-Warning "Server is not responding. Remote diagnostics:"
    & ssh -t $target "sudo systemctl status lyceumtv --no-pager -l || true; sudo journalctl -u lyceumtv -n 60 --no-pager || true"
    throw "LyceumTV health endpoint is not responding on ${PiHost}:443"
}

$health | ConvertTo-Json -Depth 6 | Out-Host

if (-not $health.ok -or $health.version -ne "3.6.1") {
    throw "Server reports version $($health.version), expected healthy 3.6.1. Reboot cancelled."
}

try {
    $state = Invoke-RestMethod `
        -Uri "https://${PiHost}/api/state" `
        -TimeoutSec 8 `
        -ErrorAction Stop

    if ($state.config_public.mobile_public_url) {
        Write-Host "Mobile public URL: $($state.config_public.mobile_public_url)"
    }
}
catch {
    Write-Warning "API state check failed, but health endpoint is OK."
}

if (-not $NoReboot) {
    Write-Host "[5/5] Rebooting Raspberry Pi..."
    & ssh -t $target "sudo reboot"
    Write-Host "Reboot command sent."
}
else {
    Write-Host "[5/5] Reboot skipped."
}

Write-Host ""
Write-Host "Installation complete."
Write-Host "Default role keys have been replaced by unique keys. Retrieve them using SSH and sudo; see README.md."
Write-Host "TV:      https://${PiHost}/"
Write-Host "Admin:   https://${PiHost}/admin"
Write-Host "Mobile:  https://${PiHost}/mobile/"
Write-Host "Ops:     https://${PiHost}/ops"
Write-Host "Health:  https://${PiHost}/api/health"
Write-Host "Kiosk:   Chromium + Cage, password-store=basic"
