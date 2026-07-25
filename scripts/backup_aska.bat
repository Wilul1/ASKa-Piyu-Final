@echo off
setlocal EnableExtensions
REM Backup Postgres + Chroma/documents/attachments from Compose full profile.
set "ROOT=%~dp0.."
cd /d "%ROOT%" || exit /b 1

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%i"
set "OUT=%ROOT%\deploy\backups\%STAMP%"
mkdir "%OUT%" 2>nul

echo Backing up Postgres to %OUT%\aska_piyu.dump
docker compose --profile full exec -T postgres pg_dump -U postgres -d aska_piyu -Fc > "%OUT%\aska_piyu.dump"
if errorlevel 1 (
  echo ERROR: pg_dump failed. Is compose --profile full running?
  exit /b 1
)

echo Backing up /data volumes to %OUT%\data_volumes.tgz
docker compose --profile full exec -T api tar -C /data -czf - chroma documents ticket_attachments > "%OUT%\data_volumes.tgz"
if errorlevel 1 (
  echo ERROR: data volume tar failed.
  exit /b 1
)

echo.
echo Backup OK: %OUT%
echo Copy this folder off the server.
exit /b 0
