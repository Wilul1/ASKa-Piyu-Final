@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
set PYTHONUTF8=1
set TQDM_DISABLE=1
chcp 65001 >nul
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
