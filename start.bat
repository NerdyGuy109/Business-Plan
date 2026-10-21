@echo off
REM Start the menu & inventory website, then open http://localhost:8000
cd /d "%~dp0"
py -m pip install -q -r requirements.txt
start "" http://localhost:8000
py -m app.server %*
