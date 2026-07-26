@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM Backup Postgres + Chroma/documents/attachments from Compose full profile.
REM Optional encryption: set ASKA_BACKUP_PASSPHRASE or deploy\BACKUP_PASSPHRASE.txt
set "ROOT=%~dp0.."
cd /d "%ROOT%" || exit /b 1

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%i"
set "OUT=%ROOT%\deploy\backups\%STAMP%"
mkdir "%OUT%" 2>nul

if not defined ASKA_BACKUP_PASSPHRASE if exist "%ROOT%\deploy\BACKUP_PASSPHRASE.txt" (
  for /f "usebackq eol=# tokens=*" %%p in ("%ROOT%\deploy\BACKUP_PASSPHRASE.txt") do (
    if not defined ASKA_BACKUP_PASSPHRASE set "ASKA_BACKUP_PASSPHRASE=%%p"
  )
)

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

if defined ASKA_BACKUP_PASSPHRASE (
  where openssl >nul 2>&1
  if errorlevel 1 (
    echo ERROR: ASKA_BACKUP_PASSPHRASE is set but openssl was not found on PATH.
    exit /b 1
  )
  echo Encrypting backup archive...
  tar -C "%OUT%" -czf "%OUT%\aska_backup_bundle.tgz" aska_piyu.dump data_volumes.tgz
  if errorlevel 1 (
    echo ERROR: failed to create backup bundle tar.
    exit /b 1
  )
  openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:ASKA_BACKUP_PASSPHRASE -in "%OUT%\aska_backup_bundle.tgz" -out "%OUT%\aska_backup_bundle.tgz.enc"
  if errorlevel 1 (
    echo ERROR: openssl encryption failed.
    exit /b 1
  )
  del /q "%OUT%\aska_backup_bundle.tgz" "%OUT%\aska_piyu.dump" "%OUT%\data_volumes.tgz" 2>nul
  echo.
  echo Backup OK ^(encrypted^): %OUT%\aska_backup_bundle.tgz.enc
) else (
  echo.
  echo Backup OK ^(PLAINTEXT^): %OUT%
  echo WARNING: Set ASKA_BACKUP_PASSPHRASE or create deploy\BACKUP_PASSPHRASE.txt to encrypt.
)

echo Copy this folder off the server.
exit /b 0
