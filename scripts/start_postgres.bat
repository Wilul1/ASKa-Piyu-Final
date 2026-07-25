@echo off
setlocal
cd /d "%~dp0.."

echo.
echo === ASKa-Piyu: start PostgreSQL (Docker, local) ===
echo Project folder: %CD%
echo.

echo [1/4] Checking Docker...
where docker >nul 2>nul
if errorlevel 1 (
  echo ERROR: Docker is not installed or not on PATH.
  echo Install Docker Desktop, then reopen this terminal.
  exit /b 1
)
echo Docker command found.

echo [2/4] Checking Docker Engine is running...
docker info >nul 2>nul
if errorlevel 1 (
  echo ERROR: Docker is installed but Engine is not ready.
  echo Open Docker Desktop and wait until it says "Engine running".
  echo Then run this script again.
  exit /b 1
)
echo Docker Engine is ready.

if not exist ".env" (
  echo.
  echo Creating repo-root .env for local Docker ^(POSTGRES_PASSWORD=aska1234^)...
  (
    echo # Local Docker only — do not use this password on a VPS.
    echo POSTGRES_PASSWORD=aska1234
  ) > .env
)

echo [3/4] Starting Postgres ^(localhost:5432 only, not public^)...
echo First run may download the postgres image - this can take several minutes.
echo Do not close this window.
echo.
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres
if errorlevel 1 (
  echo.
  echo ERROR: Failed to start Postgres.
  echo - Ensure POSTGRES_PASSWORD is set in repo-root .env
  echo - If port 5432 is in use, stop local PostgreSQL or set POSTGRES_HOST_PORT
  exit /b 1
)

echo.
echo [4/4] Waiting a few seconds for Postgres to become ready...
timeout /t 5 /nobreak >nul

echo.
docker compose -f docker-compose.yml -f docker-compose.dev.yml ps
echo.
echo DONE. Postgres should be running as container: aska-piyu-postgres
echo Bound to 127.0.0.1 only ^(not exposed to the LAN/internet^).
echo.
echo Use these in backend\.env ^(password must match POSTGRES_PASSWORD in repo-root .env^):
echo   ASKA_DATABASE_URL=postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/aska_piyu
echo   ASKA_TEST_DATABASE_URL=postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/aska_piyu_test
echo Local default from this script: aska1234
echo.
endlocal
