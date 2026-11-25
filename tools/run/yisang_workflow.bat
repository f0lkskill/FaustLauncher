@echo off
rem FaustLauncher - open YisangMirrorFlow (packaging workflow + extension tools)
rem This file lives in tools/run/, so cd back to the repo root first,
rem otherwise venv\Scripts\python.exe and tools\workflow\main.py cannot be found.
cd /d "%~dp0..\.."
set "PY=venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" tools\workflow\main.py %*
if errorlevel 1 pause
