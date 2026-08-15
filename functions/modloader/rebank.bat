@echo off
rem rebank launcher
rem runs the CLI in its own directory so relative paths resolve consistently
rem and the FMOD DLLs next to this folder are auto-found.
cd /d "%~dp0"
python rebank.py %*
