@echo off
rem FaustLauncher - rebuild + upload the game offset index (decrypt, dump, parse, push)
rem Takes 1-2 minutes on all cores. This file lives in tools/run/, so cd back to the
rem repo root first, otherwise venv\Scripts\python.exe and functions/ cannot be found.
cd /d "%~dp0..\.."
set "PY=venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -m functions.hook.main update
pause
