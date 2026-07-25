@echo off
setlocal

call "%~dp0_load_api_base.bat" || exit /b 1

set "FLUTTER_DIR=%~dp0..\flutter_app"
cd /d "%FLUTTER_DIR%" || exit /b 1

if not exist "android\key.properties" (
  if /I not "%ASKA_ALLOW_DEBUG_RELEASE_SIGNING%"=="true" (
    echo.
    echo ERROR: Missing flutter_app\android\key.properties
    echo Application id: ph.edu.lspu.aska_piyu
    echo.
    echo For Play Store / campus MDM:
    echo   1. Copy android\key.properties.example to android\key.properties
    echo   2. Create a keystore ^(see comments in the example file^)
    echo   3. Fill in storePassword / keyPassword / keyAlias / storeFile
    echo.
    echo For local smoke tests only:
    echo   set ASKA_ALLOW_DEBUG_RELEASE_SIGNING=true
    echo.
    exit /b 1
  )
  echo WARNING: Signing release AAB with DEBUG keystore ^(local only^).
)

echo Building Flutter App Bundle ^(ph.edu.lspu.aska_piyu^) with ASKA_API_BASE_URL=%ASKA_API_BASE_URL%
flutter build appbundle --release --dart-define=ASKA_API_BASE_URL=%ASKA_API_BASE_URL%
exit /b %ERRORLEVEL%
