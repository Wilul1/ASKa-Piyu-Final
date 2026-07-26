# Harden lab ops (signup policy, rotate passwords, backup passphrase).
# Usage (repo root):
#   powershell -ExecutionPolicy Bypass -File scripts\harden_lab_ops.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\harden_lab_ops.ps1 -ApplyDb

param(
  [switch]$ApplyDb
)

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$argsList = @()
if ($ApplyDb) { $argsList += "--apply-db" }

python "$Root\scripts\harden_lab_ops.py" @argsList
exit $LASTEXITCODE
