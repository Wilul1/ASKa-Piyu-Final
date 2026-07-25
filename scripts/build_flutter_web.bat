@echo off
setlocal

call "%~dp0_load_api_base.bat" || exit /b 1

set "FLUTTER_DIR=%~dp0..\flutter_app"
cd /d "%FLUTTER_DIR%" || exit /b 1

echo Building Flutter web with ASKA_API_BASE_URL=%ASKA_API_BASE_URL%
flutter build web --release --dart-define=ASKA_API_BASE_URL=%ASKA_API_BASE_URL%
exit /b %ERRORLEVEL%
