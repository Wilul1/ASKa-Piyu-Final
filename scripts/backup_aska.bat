@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM Backup Postgres + Chroma/documents/attachments/kb_media from Compose full profile.
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

echo Confirming kb_media volume is mounted on the api container...
docker compose --profile full exec -T api test -d /data/kb_media
if errorlevel 1 (
  echo ERROR: /data/kb_media does not exist on the api container. Aborting backup
  echo rather than silently skipping article/KB media files.
  exit /b 1
)

echo Backing up /data volumes ^(chroma, documents, ticket_attachments, kb_media^) to %OUT%\data_volumes.tgz
docker compose --profile full exec -T api tar -C /data -czf - chroma documents ticket_attachments kb_media > "%OUT%\data_volumes.tgz"
if errorlevel 1 (
  echo ERROR: data volume tar failed.
  exit /b 1
)

echo Verifying kb_media is actually present in the archive...
tar -tzf "%OUT%\data_volumes.tgz" > "%OUT%\_archive_list.txt"
if errorlevel 1 (
  echo ERROR: %OUT%\data_volumes.tgz is not a readable/valid tar archive.
  exit /b 1
)

set "KB_MEDIA_SOURCE_COUNT="
for /f %%i in ('docker compose --profile full exec -T api sh -c "cd /data/kb_media && find . -type f | wc -l"') do set "KB_MEDIA_SOURCE_COUNT=%%i"
if not defined KB_MEDIA_SOURCE_COUNT (
  echo ERROR: could not count kb_media source files.
  exit /b 1
)

findstr /B "kb_media/" "%OUT%\_archive_list.txt" | findstr /V /E "/" > "%OUT%\_kbm_files.txt" 2>nul
set "KB_MEDIA_ARCHIVE_COUNT=0"
for /f %%i in ('type "%OUT%\_kbm_files.txt" ^| find /c /v ""') do set "KB_MEDIA_ARCHIVE_COUNT=%%i"
del /q "%OUT%\_archive_list.txt" "%OUT%\_kbm_files.txt" 2>nul

if not "%KB_MEDIA_SOURCE_COUNT%"=="%KB_MEDIA_ARCHIVE_COUNT%" (
  echo ERROR: kb_media backup verification failed: source has %KB_MEDIA_SOURCE_COUNT% file^(s^), archive has %KB_MEDIA_ARCHIVE_COUNT% file^(s^). Refusing to report success.
  echo KB_MEDIA_BACKUP_OK=NO
  exit /b 1
)
REM An empty kb_media volume (0 files) is fine as long as source and archive agree.
echo kb_media verification OK: %KB_MEDIA_SOURCE_COUNT% file^(s^) present in both source and archive.

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
  set "FINAL_ARCHIVE=%OUT%\aska_backup_bundle.tgz.enc"
  echo.
  echo Backup OK ^(encrypted^): !FINAL_ARCHIVE!
  echo Decrypt: openssl enc -d -aes-256-cbc -pbkdf2 -pass env:ASKA_BACKUP_PASSPHRASE -in aska_backup_bundle.tgz.enc -out aska_backup_bundle.tgz
) else (
  set "FINAL_ARCHIVE=%OUT%\data_volumes.tgz"
  echo.
  echo Backup OK ^(PLAINTEXT^): %OUT%
  echo WARNING: Set ASKA_BACKUP_PASSPHRASE or create deploy\BACKUP_PASSPHRASE.txt to encrypt.
)

echo KB_MEDIA_FILES=%KB_MEDIA_SOURCE_COUNT%
echo KB_MEDIA_BACKUP=!FINAL_ARCHIVE!
echo KB_MEDIA_BACKUP_OK=YES
echo Copy this folder off the server.
exit /b 0
