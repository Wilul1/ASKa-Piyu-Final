#Requires -Version 5.1
# Thin wrapper around the Python bootstrap (avoids PowerShell quoting issues).
param(
  [string]$PublicOrigin = "https://aska.local",
  [string]$AdminEmail = "admin@aska.local",
  [switch]$SkipSeed,
  [switch]$SkipKeystore,
  [switch]$ApplyProductionEnv
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root "backend\venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
  throw "Missing backend venv python: $Py"
}

$argsList = @(
  (Join-Path $Root "scripts\bootstrap_campus_deploy.py"),
  "--public-origin", $PublicOrigin,
  "--admin-email", $AdminEmail
)
if ($SkipSeed) { $argsList += "--skip-seed" }
if ($SkipKeystore) { $argsList += "--skip-keystore" }
if ($ApplyProductionEnv) { $argsList += "--apply-production-env" }

& $Py @argsList
exit $LASTEXITCODE
