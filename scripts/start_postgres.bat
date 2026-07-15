@echo off
setlocal
cd /d "%~dp0.."

echo.
echo === ASKa-Piyu: start PostgreSQL (Docker) ===
echo.

where docker >nul 2>nul
if errorlevel 1 (
  echo Docker is not installed or not on PATH.
  echo Install Docker Desktop: https://www.docker.com/products/docker-desktop/
  echo Then open Docker Desktop and run this script again.
  echo.
  echo OR install PostgreSQL locally and create databases aska_piyu + aska_piyu_test.
  exit /b 1
)

docker info >nul 2>nul
if errorlevel 1 (
  echo Docker is installed but not running.
  echo Start Docker Desktop, wait until it is ready, then run this again.
  exit /b 1
)

docker compose up -d postgres
if errorlevel 1 (
  echo Failed to start Postgres container.
  echo If port 5432 is already in use, stop local PostgreSQL or change the port in docker-compose.yml.
  exit /b 1
)

echo.
echo Waiting for Postgres to accept connections...
timeout /t 4 /nobreak >nul

docker compose ps
echo.
echo Postgres is up.
echo Default connection for backend/.env:
echo   ASKA_DATABASE_URL=postgresql+psycopg://postgres:aska1234@localhost:5432/aska_piyu
echo   ASKA_TEST_DATABASE_URL=postgresql+psycopg://postgres:aska1234@localhost:5432/aska_piyu_test
echo.
echo Next: create backend/.env from .env.example, then run the backend.
endlocal
