@echo off
rem FaustLauncher - debug mode (main.py --debug: stdout is NOT redirected, console shows output)
rem This file lives in tools/run/, so cd back to the repo root first, otherwise
rem venv\Scripts\python.exe and main.py cannot be found.
cd /d "%~dp0..\.."
set "PY=venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" main.py --debug
pause
