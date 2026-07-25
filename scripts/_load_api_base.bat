@echo off
REM Loads ASKA_API_BASE_URL from env, else flutter_app\api_base.url (one line, no quotes).
REM Always enforces https:// for release scripts unless ASKA_ALLOW_INSECURE_API_URL=true.

if not "%ASKA_API_BASE_URL%"=="" goto :validate

set "API_BASE_FILE=%~dp0..\flutter_app\api_base.url"
if not exist "%API_BASE_FILE%" (
  echo ERROR: ASKA_API_BASE_URL is not set and flutter_app\api_base.url is missing.
  echo.
  echo Create the file from the example:
  echo   copy flutter_app\api_base.url.example flutter_app\api_base.url
  echo Then edit it to your real API origin, e.g. https://api.your.edu
  echo.
  echo Or set the env var:
  echo   set ASKA_API_BASE_URL=https://api.your.edu
  exit /b 1
)

set /p ASKA_API_BASE_URL=<"%API_BASE_FILE%"
REM trim spaces
for /f "tokens=* delims= " %%A in ("%ASKA_API_BASE_URL%") do set "ASKA_API_BASE_URL=%%A"
if "%ASKA_API_BASE_URL%"=="" (
  echo ERROR: flutter_app\api_base.url is empty.
  exit /b 1
)

:validate
if /i "%ASKA_API_BASE_URL%"=="https://api.example.com" (
  echo ERROR: Replace the placeholder URL in flutter_app\api_base.url with your real API.
  exit /b 1
)
echo %ASKA_API_BASE_URL% | findstr /I /B "https://" >nul
if errorlevel 1 (
  if /I not "%ASKA_ALLOW_INSECURE_API_URL%"=="true" (
    echo ERROR: ASKA_API_BASE_URL must start with https:// for release builds.
    echo Got: %ASKA_API_BASE_URL%
    echo.
    echo For local http:// testing only:
    echo   set ASKA_ALLOW_INSECURE_API_URL=true
    exit /b 1
  )
  echo WARNING: Building with non-HTTPS API URL ^(ASKA_ALLOW_INSECURE_API_URL=true^).
)
exit /b 0
