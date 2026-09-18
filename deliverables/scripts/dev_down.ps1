# Stops everything scripts\dev_up.ps1 started (process trees, so the Vite
# children under cmd.exe go too).
$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root "logs\dev.pids"
if (-not (Test-Path $pidFile)) { Write-Output "nothing recorded in logs\dev.pids"; exit 0 }
foreach ($id in Get-Content $pidFile) {
  if ($id -match '^\d+$') { taskkill /PID $id /T /F 2>$null | Out-Null }
}
Remove-Item $pidFile -Force
Write-Output "stopped"
