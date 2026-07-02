@echo off
setlocal

REM ============================================================
REM ASKa-Piyu project launcher
REM Opens separate terminals for the FastAPI backend and Flutter app.
REM ============================================================

REM Store the project root so both terminals can navigate safely.
set "PROJECT_ROOT=%~dp0"
set "BACKEND_DIR=%PROJECT_ROOT%backend"
set "FLUTTER_DIR=%PROJECT_ROOT%flutter_app"

REM Admin API key is loaded from backend/.env. Do not hardcode secrets in this launcher.

REM ============================================================
REM Start the FastAPI backend in its own terminal.
REM - Navigates to backend
REM - Activates the backend virtual environment
REM - Lets the backend load admin settings from backend/.env
REM - Runs Uvicorn on port 8000
REM - Keeps the terminal open if an error occurs
REM ============================================================
start "ASKa-Piyu Backend" /D "%BACKEND_DIR%" cmd /k "title ASKa-Piyu Backend && echo Admin API key will be loaded from backend/.env && if exist venv\Scripts\activate.bat (call venv\Scripts\activate.bat && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000) else (echo Backend virtual environment not found: %BACKEND_DIR%\venv && echo Create it first, then run this launcher again.)"

REM ============================================================
REM Start the Flutter application in its own terminal.
REM - Navigates to flutter_app
REM - Runs flutter run
REM - Keeps the terminal open if an error occurs
REM ============================================================
start "ASKa-Piyu Flutter" /D "%FLUTTER_DIR%" cmd /k "title ASKa-Piyu Flutter && flutter run --dart-define=ASKA_API_BASE_URL=http://localhost:8000"

endlocal
