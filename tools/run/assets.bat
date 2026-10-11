@echo off
rem FaustLauncher asset pack (assets / voices / skin images): pack | status | fetch | upload
rem Usage: assets.bat [pack|status|fetch|upload]   (no argument = pack)
rem This file lives in tools/run/, so cd back to the repo root first.
cd /d "%~dp0..\.."
set "PY=venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=pack"
"%PY%" tools\build\assets_pack.py %ACTION%
pause
