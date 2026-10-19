@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python isn't installed. Get it from https://www.python.org/downloads/
  echo During setup, tick "Add python.exe to PATH", then run this again.
  pause
  exit /b 1
)
python -c "import pygame" >nul 2>nul
if errorlevel 1 (
  echo First run: installing pygame...
  python -m pip install --user -r requirements.txt
)
python main.py
if errorlevel 1 pause
