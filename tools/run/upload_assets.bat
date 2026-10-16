@echo off
rem FaustLauncher - asset pack quick release: pack THEN upload (asset pack only, NOT an app version)
rem Usage: upload_assets.bat [version]        no argument = today's date
rem Steps: precheck local assets -> pack (overwrites faust-assets.zip) -> upload to Release tag=assets
rem This file lives in tools/run/, so cd back to the repo root first.
rem NOTE: keep every line ASCII-only. This is a UTF-8 file and cmd's parser breaks on
rem       non-ASCII text once chcp switches the codepage (truncated commands). Chinese in
rem       this file must not exist; python writes its own logs fine without PYTHONIOENCODING.
setlocal
cd /d "%~dp0..\.."
set "PY=venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
if "%~1"=="" (set "VERARG=") else (set "VERARG=--version %~1")

echo [1/3] Checking local assets ...
set "MISS="
if not exist "assets\images\icon\icon.ico" set "MISS=%MISS% assets\images\icon\icon.ico"
if not exist "assets\voices\click.wav" set "MISS=%MISS% assets\voices\click.wav"
if not "%MISS%"=="" (
    echo   [X] Missing:%MISS%
    echo       Fetch the pack first: tools\run\assets.bat fetch
    pause
    exit /b 1
)

echo [2/3] Packing asset pack ...
"%PY%" tools\build\assets_pack.py pack %VERARG%
if errorlevel 1 (
    echo   [X] Pack failed, upload aborted
    pause
    exit /b 1
)

echo [3/3] Uploading to GitHub Release ^(tag=assets^) ...
"%PY%" tools\build\assets_pack.py upload
if errorlevel 1 (
    echo   [X] Upload failed - check that gh is authenticated ^(gh auth status^)
    pause
    exit /b 1
)

echo.
echo [OK] Done - download URL is always:
echo   https://github.com/f0lkskill/FaustLauncher/releases/download/assets/faust-assets.zip
pause
