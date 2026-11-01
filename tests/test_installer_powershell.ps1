$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../scripts/installer_launcher.ps1')
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('lyceumtv-ps-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null
$passed = 0
function Assert-Lyceum($Condition,[string]$Message) {
    if (-not $Condition) { throw $Message }
    $script:passed++; Write-Host "PASS: $Message"
}
try {
    $root = Join-Path $temporary 'package'
    New-Item -ItemType Directory -Path $root | Out-Null
    $manifest = [ordered]@{}
    foreach ($rel in @('scripts/installer.py','scripts/installer_upgrade.py','scripts/runtime_storage.py','scripts/install.sh','release.json','server/app.py','public/tv4.html','data/config.example.json')) {
        $path = Join-Path $root $rel
        New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force | Out-Null
        [IO.File]::WriteAllText($path,'fixture')
        $manifest[$rel] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'PACKAGE_SHA256.json') -Encoding UTF8
    Assert-Lyceum ((Get-LyceumPackageReport $root).Errors.Count -eq 0) 'valid package accepted'
    New-Item -ItemType Directory -Path (Join-Path $root '.idea') | Out-Null
    Set-Content -LiteralPath (Join-Path $root '.idea/.gitignore') -Value 'local'
    $report = Get-LyceumPackageReport $root
    Assert-Lyceum ($report.Errors.Count -eq 0 -and $report.Files -notcontains '.idea/.gitignore') 'IDE files ignored and excluded from upload'
    Set-Content -LiteralPath (Join-Path $root 'untrusted.ps1') -Value 'bad'
    Assert-Lyceum ((Get-LyceumPackageReport $root).Errors -match 'Unlisted') 'unknown executable rejected'
    Remove-Item -LiteralPath (Join-Path $root 'untrusted.ps1')
    Assert-Lyceum ((Protect-LyceumLog 'password=example-value token=example-value') -notmatch 'example-value') 'diagnostic secrets redacted'
    if ((Protect-LyceumLog '{"api_key":"example-value with spaces","token":"example-value"} Bearer example-value') -match 'example-value') { throw 'JSON/authorization redaction failed' }
    $script:calls = [Collections.Generic.List[string]]::new()
    $script:failure = ''
    function Invoke-LyceumNative([string]$Command,[string[]]$Arguments) {
        $line = $Arguments -join ' '; $script:calls.Add("$Command $line")
        if ($script:failure -eq 'ssh' -and $line -match 'printf') { return [pscustomobject]@{ExitCode=255;Lines=@('Connection refused')} }
        if ($line -match '^.*mktemp') { return [pscustomobject]@{ExitCode=0;Lines=@('/tmp/lyceumtv-install.Ab123456')} }
        if ($Command -eq 'scp') {
            $source = $Arguments[1].TrimEnd('/.');$sent = @(Get-ChildItem -LiteralPath $source -Recurse -Force -File)
            Assert-Lyceum (-not ($sent.FullName -match '\.idea')) 'actual staging contains no IDE files'
        }
        if ($script:failure -eq 'target' -and $line -match 'sudo python3') { return [pscustomobject]@{ExitCode=1;Lines=@('DIRECTORY_SECURITY: data/update_jobs wrong owner')} }
        return [pscustomobject]@{ExitCode=0;Lines=@('ok')}
    }
    $logs = Join-Path $temporary 'logs'
    $code = Invoke-LyceumInstaller $root '192.0.2.18' 'admin' $true $false $logs
    Assert-Lyceum ($code -eq 0 -and ($script:calls -match '--check-only')) 'CheckOnly reaches remote read-only diagnostic'
    Assert-Lyceum (-not ($script:calls -match 'systemctl|install_air_raid')) 'launcher never stops services or bypasses coordinator'
    $script:failure = 'ssh';$script:calls.Clear()
    $code = Invoke-LyceumInstaller $root '192.0.2.18' 'admin' $true $false $logs
    Assert-Lyceum ($code -eq 1 -and -not ($script:calls -match '^scp')) 'SSH failure prevents upload/install'
    $script:failure = 'target';$script:calls.Clear()
    $code = Invoke-LyceumInstaller $root '192.0.2.18' 'admin' $true $false $logs
    Assert-Lyceum ($code -eq 1) 'target failure propagates nonzero status'
    $text = Get-Content -LiteralPath $script:LyceumLog -Raw
    Assert-Lyceum ($text -match 'DIRECTORY_SECURITY: data/update_jobs wrong owner') 'specific target cause saved in automatic log'
    Assert-Lyceum ($script:calls -match 'test -O.*rm -rf') 'remote cleanup restricted to owned staging path'
    Assert-Lyceum (-not (Get-ChildItem -LiteralPath ([IO.Path]::GetTempPath()) -Directory -Filter 'lyceumtv-install-*' | Where-Object { $_.CreationTime -gt (Get-Date).AddMinutes(-1) })) 'local staging cleaned after success and failure'
    function Test-LyceumCommand([string]$Name) { return $Name -ne 'ssh' }
    $script:calls.Clear()
    $code = Invoke-LyceumInstaller $root '192.0.2.18' 'admin' $true $false $logs
    Assert-Lyceum ($code -eq 1 -and $script:calls.Count -eq 0) 'missing SSH binary blocks before remote actions'
    Write-Host "PowerShell installer: $passed checks PASS"
} finally {
    $resolved = [IO.Path]::GetFullPath($temporary)
    if ((Split-Path -Leaf $resolved) -match '^lyceumtv-ps-test-[a-f0-9]{32}$' -and (Split-Path -Parent $resolved) -eq ([IO.Path]::GetTempPath()).TrimEnd([IO.Path]::DirectorySeparatorChar)) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
