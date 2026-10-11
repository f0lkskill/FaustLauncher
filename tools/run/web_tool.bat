@echo off
rem FaustLauncher - open the "extension tools" window only (same as the button in the main UI)
rem This file lives in tools/run/, so cd back to the repo root first, otherwise
rem venv\Scripts\python.exe and main.py cannot be found.
cd /d "%~dp0..\.."
set "PY=venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" main.py --extension-tools-window
pause
