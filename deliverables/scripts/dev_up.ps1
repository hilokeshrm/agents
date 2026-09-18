# Starts the backend on the live dev database and the frontend.
#
#   scripts\dev_up.ps1                 AUTH_MODE=local: one app at :5180 with the real
#                                      sign-in (landing / sign-up / OTP / login).
#                                      Demo accounts: python -m scripts.seed_demo_accounts
#   scripts\dev_up.ps1 -Mode headers   the header stand-in: one pre-signed-in app per
#                                      role at :5181-:5185, no passwords.
#
# Stop everything with scripts\dev_down.ps1. Logs in logs\.
param([ValidateSet("local", "headers")][string]$Mode = "local")

$root = Split-Path -Parent $PSScriptRoot
$logs = Join-Path $root "logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$api = "http://127.0.0.1:8000/api/v1"

$env:AUTH_MODE = $Mode
if (-not $env:OTP_DELIVERY) { $env:OTP_DELIVERY = "console" }   # codes go to logs\backend.log until SMTP is configured
$backend = Start-Process -FilePath "python" -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" `
  -WorkingDirectory (Join-Path $root "backend") -WindowStyle Hidden -PassThru `
  -RedirectStandardOutput (Join-Path $logs "backend.log") -RedirectStandardError (Join-Path $logs "backend.err.log")
$pids = @($backend.Id)

function Start-Frontend([int]$port, [string]$role, [string]$actor, [string]$regions, [string]$logName) {
  $env:VITE_API_BASE = $api
  $env:VITE_OPPTRACK_ROLE = $role
  $env:VITE_OPPTRACK_ACTOR = $actor
  $env:VITE_OPPTRACK_REGIONS = $regions
  $p = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "npx vite --port $port --strictPort --host 127.0.0.1" `
    -WorkingDirectory (Join-Path $root "frontend") -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logs "frontend-$logName.log") -RedirectStandardError (Join-Path $logs "frontend-$logName.err.log")
  return $p.Id
}

if ($Mode -eq "local") {
  $pids += Start-Frontend 5180 "owner" "" "*" "app"
  Set-Content -Path (Join-Path $logs "dev.pids") -Value ($pids -join "`n")
  Write-Output "backend   http://127.0.0.1:8000/docs   (AUTH_MODE=local, OTP_DELIVERY=$($env:OTP_DELIVERY))"
  Write-Output "app       http://127.0.0.1:5180/       sign in with a seeded account or create one"
} else {
  $roles = @(
    @{ role = "director"; port = 5181; actor = "marc";        regions = "*" },
    @{ role = "owner";    port = 5182; actor = "owner-korea"; regions = "*" },
    @{ role = "manager";  port = 5183; actor = "kim";         regions = "Korea" },
    @{ role = "finance";  port = 5184; actor = "cfo";         regions = "*" },
    @{ role = "admin";    port = 5185; actor = "root";        regions = "*" }
  )
  foreach ($r in $roles) { $pids += Start-Frontend $r.port $r.role $r.actor $r.regions $r.role }
  Set-Content -Path (Join-Path $logs "dev.pids") -Value ($pids -join "`n")
  Write-Output "backend  http://127.0.0.1:8000/docs   (AUTH_MODE=headers)"
  foreach ($r in $roles) { Write-Output ("{0,-9} http://127.0.0.1:{1}/   (acting as {2}, regions {3})" -f $r.role, $r.port, $r.actor, $r.regions) }
}
