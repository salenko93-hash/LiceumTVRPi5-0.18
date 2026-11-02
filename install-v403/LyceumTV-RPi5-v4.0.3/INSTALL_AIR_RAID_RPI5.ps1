param(
    [string]$PiHost = '192.168.0.18',
    [string]$PiUser = 'admin',
    [switch]$CheckOnly,
    [switch]$Yes,
    [string]$LogDirectory = ''
)
. (Join-Path $PSScriptRoot 'scripts/installer_launcher.ps1')
$result = Invoke-LyceumInstaller -Root $PSScriptRoot -TargetHost $PiHost -User $PiUser -OnlyCheck $CheckOnly.IsPresent -Approved $Yes.IsPresent -Logs $LogDirectory
exit $result
