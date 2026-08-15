@echo off
rem fmodbank launcher
rem runs the CLI in its own directory so relative paths (./wav, ./fsb, ./build)
rem resolve consistently and the FMOD DLLs next to this folder are auto-found.
cd /d "%~dp0"
python fmodbank.py %*
