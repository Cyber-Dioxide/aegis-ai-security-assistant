@echo off
REM Local development run on Windows (for Linux servers use deploy/deploy.sh).
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
if "%AEGIS_PORT%"=="" set AEGIS_PORT=8080
echo ==^> Aegis on http://127.0.0.1:%AEGIS_PORT%
python app.py
