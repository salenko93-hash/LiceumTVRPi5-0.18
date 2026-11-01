# Compatibility entry point: server/public/data/scripts are verified by the coordinator.
param([string]$PiHost='192.168.0.18',[string]$PiUser='admin',[switch]$CheckOnly,[switch]$Yes,[switch]$NoReboot,[string]$LogDirectory='')
& (Join-Path $PSScriptRoot 'INSTALL_AIR_RAID_RPI5.ps1') -PiHost $PiHost -PiUser $PiUser -CheckOnly:$CheckOnly -Yes:$Yes -LogDirectory $LogDirectory
exit $LASTEXITCODE
