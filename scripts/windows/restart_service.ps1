param(
  [string]$Name = "Spooler"
)

Restart-Service -Name $Name -ErrorAction Stop
Write-Output "Service restarted: $Name"
