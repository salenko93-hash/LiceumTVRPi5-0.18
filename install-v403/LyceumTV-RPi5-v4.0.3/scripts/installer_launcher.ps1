function Protect-LyceumLog([string]$Text) {
    $Text = $Text -replace '(?i)((?:["'']?)[\w-]*(?:password|passwd|token|secret|_key)(?:["'']?)\s*[=:]\s*)(?:"[^"]*"|''[^'']*''|[^\s,;]+)', '$1[REDACTED]'
    $Text = $Text -replace '(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*', 'Bearer [REDACTED]'
    return $Text -replace '\b(?:gh[pousr]_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+|\d{8,12}:[A-Za-z0-9_-]{30,})\b', '[REDACTED]'
}
function Write-LyceumLog([string]$Text) {
    $safe = Protect-LyceumLog $Text
    Write-Host $safe
    if ($script:LyceumLog) { Add-Content -LiteralPath $script:LyceumLog -Value $safe -Encoding UTF8 }
}
function Get-LyceumPackageReport([string]$Root) {
    $errors = [Collections.Generic.List[string]]::new()
    $files = [Collections.Generic.List[string]]::new()
    $base = [IO.Path]::GetFullPath($Root).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    try {
        $manifest = Get-Content -LiteralPath (Join-Path $Root 'PACKAGE_SHA256.json') -Raw | ConvertFrom-Json
        foreach ($entry in $manifest.PSObject.Properties) {
            $name = $entry.Name
            if ($name -match '(^/|\\|:|(^|/)\.\.(/|$)|(^|/)(\.git|\.idea|\.vscode|__pycache__)(/|$))' -or $entry.Value -notmatch '^[a-f0-9]{64}$') {
                $errors.Add("Unsafe manifest entry: $name"); continue
            }
            $path = [IO.Path]::GetFullPath((Join-Path $Root $name))
            if (-not $path.StartsWith($base,[StringComparison]::OrdinalIgnoreCase)) { $errors.Add("Escaping path: $name"); continue }
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { $errors.Add("Missing: $name"); continue }
            $node = Get-Item -LiteralPath $path -Force
            $unsafe = $false
            while ($node -and $node.FullName.StartsWith($base,[StringComparison]::OrdinalIgnoreCase)) {
                if ($node.Attributes -band [IO.FileAttributes]::ReparsePoint) { $unsafe = $true; break }
                if ($node -is [IO.FileInfo]) { $node = $node.Directory } else { $node = $node.Parent }
            }
            if ($unsafe) { $errors.Add("Reparse point: $name"); continue }
            if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value) { $errors.Add("SHA-256 mismatch: $name") }
            $files.Add($name)
        }
        foreach ($required in @('scripts/installer.py','scripts/installer_upgrade.py','scripts/runtime_storage.py','scripts/install.sh','release.json','server/app.py','public/tv4.html','data/config.example.json')) {
            if ($files -notcontains $required) { $errors.Add("Required manifest entry absent: $required") }
        }
        foreach ($file in Get-ChildItem -LiteralPath $Root -Recurse -Force -File) {
            $rel = $file.FullName.Substring($base.Length).Replace('\','/')
            if ($rel -eq 'PACKAGE_SHA256.json' -or $rel -match '^(\.idea|\.vscode|\.git|__pycache__)/' -or $file.Name -in @('.DS_Store','Thumbs.db')) { continue }
            if ($files -notcontains $rel) { $errors.Add("Unlisted file: $rel") }
        }
    } catch { $errors.Add($_.Exception.Message) }
    return [pscustomobject]@{ Errors = @($errors.ToArray()); Files = @($files.ToArray()) }
}
function Invoke-LyceumNative([string]$Command, [string[]]$Arguments) {
    # No transcript: password input remains in SSH, never collected by this script.
    $lines = @(& $Command @Arguments 2>&1 | ForEach-Object { $text = Protect-LyceumLog "$_"; Write-LyceumLog $text; $text })
    return [pscustomobject]@{ ExitCode = $LASTEXITCODE; Lines = $lines }
}
function Test-LyceumCommand([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}
function Invoke-LyceumInstaller {
    param([string]$Root,[string]$TargetHost,[string]$User,[bool]$OnlyCheck,[bool]$Approved,[string]$Logs)
    $ErrorActionPreference = 'Stop'
    if (-not $Logs) { $Logs = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'LyceumTV/installer-logs' }
    New-Item -ItemType Directory -Path $Logs -Force | Out-Null
    $script:LyceumLog = Join-Path $Logs (('install-{0}-{1}.log' -f (Get-Date -Format 'yyyyMMdd-HHmmss'),[guid]::NewGuid().ToString('N')))
    $temporary = $null; $remote = $null; $target = $null
    try {
        $errors = [Collections.Generic.List[string]]::new()
        $ip = $null
        if (-not [Net.IPAddress]::TryParse($TargetHost,[ref]$ip) -or $ip.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) { $errors.Add('PiHost must be IPv4') }
        if ($User -notmatch '^[a-z_][a-z0-9_-]{0,31}$') { $errors.Add('Invalid administrative username') }
        Write-LyceumLog '[1/4] Local release integrity and tools'
        $package = Get-LyceumPackageReport $Root
        foreach ($errorText in $package.Errors) { $errors.Add($errorText) }
        foreach ($command in @('ssh','scp')) { if (-not (Test-LyceumCommand $command)) { $errors.Add("Required command absent: $command") } }
        if ($errors.Count) { throw ($errors -join "`n") }
        $target = "${User}@${TargetHost}"
        Write-LyceumLog '[2/4] SSH connectivity (no service changes)'
        $probe = Invoke-LyceumNative 'ssh' @('-o','ConnectTimeout=15',$target,'printf LYCEUMTV_SSH_OK')
        if ($probe.ExitCode) { throw "SSH unavailable: $($probe.Lines -join ' ')" }
        if (-not $OnlyCheck -and -not $Approved -and (Read-Host 'Type INSTALL to authorize this installation') -cne 'INSTALL') { throw 'Installation cancelled before upload' }
        $created = Invoke-LyceumNative 'ssh' @($target,'mktemp -d /tmp/lyceumtv-install.XXXXXXXX')
        $remote = ($created.Lines | Where-Object { $_ -match '^/tmp/lyceumtv-install\.[A-Za-z0-9]{8}$' } | Select-Object -Last 1)
        if ($created.ExitCode -or -not $remote) { throw 'Cannot allocate owned remote staging directory' }
        $temporary = Join-Path ([IO.Path]::GetTempPath()) ('lyceumtv-install-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $temporary | Out-Null
        foreach ($rel in @($package.Files) + @('PACKAGE_SHA256.json')) {
            $destination = Join-Path $temporary $rel
            New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
            Copy-Item -LiteralPath (Join-Path $Root $rel) -Destination $destination
        }
        Write-LyceumLog '[3/4] Uploading manifest-listed files only'
        $upload = Invoke-LyceumNative 'scp' @('-r',"$temporary/.","${target}:$remote/")
        if ($upload.ExitCode) { throw "Upload failed: $($upload.Lines -join ' ')" }
        Write-LyceumLog '[4/4] Raspberry Pi diagnostics / safe transaction'
        $flag = if ($OnlyCheck) { ' --check-only' } else { '' }
        $run = Invoke-LyceumNative 'ssh' @('-tt',$target,"sudo python3 -B '$remote/scripts/installer.py' --package '$remote' --admin '$User' --pi-host '$TargetHost'$flag")
        if ($run.ExitCode) { throw "Target failed (exit $($run.ExitCode)): $($run.Lines -join [Environment]::NewLine)" }
        Write-LyceumLog 'PASS. No automatic reboot. Physical HDMI/audio validation requires a separate Raspberry Pi check.'
        return 0
    } catch {
        Write-LyceumLog ('FAIL: ' + $_.Exception.Message)
        return 1
    } finally {
        if ($remote -match '^/tmp/lyceumtv-install\.[A-Za-z0-9]{8}$' -and $target) {
            try {
                $cleanup = Invoke-LyceumNative 'ssh' @('-o','ConnectTimeout=10',$target,"test -d '$remote' && test -O '$remote' && rm -rf -- '$remote'")
                if ($cleanup.ExitCode) { throw 'SSH cleanup returned nonzero status' }
            } catch { Write-LyceumLog "WARN: remote staging cleanup failed: $remote" }
        }
        if ($temporary) {
            $resolved = [IO.Path]::GetFullPath($temporary)
            $parent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([IO.Path]::DirectorySeparatorChar)
            if ((Split-Path -Parent $resolved) -eq $parent -and (Split-Path -Leaf $resolved) -match '^lyceumtv-install-[a-f0-9]{32}$') { Remove-Item -LiteralPath $resolved -Recurse -Force }
        }
        Write-LyceumLog "Diagnostic log: $script:LyceumLog"
    }
}
