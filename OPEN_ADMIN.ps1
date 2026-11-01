param([string]$PiHost = "192.168.0.18")
Start-Process "https://${PiHost}/admin"
