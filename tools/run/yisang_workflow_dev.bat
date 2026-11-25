@echo off
rem YisangMirrorFlow - dev/debug launch (pywebview debug, opens devtools)
rem This file lives in tools/run/, so cd back to the repo root first.
cd /d "%~dp0..\.."
set "PY=venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" tools\workflow\main.py --debug %*
if errorlevel 1 pause
