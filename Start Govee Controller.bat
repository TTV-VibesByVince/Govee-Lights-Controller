@echo off
title Govee Light Controller
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo  Python is not installed.
    echo  Get it from https://www.python.org/downloads/ and tick
    echo  "Add python.exe to PATH" during setup, then run this again.
    echo.
    start https://www.python.org/downloads/
    pause
    exit /b 1
)

python -c "import PIL" >nul 2>nul
if errorlevel 1 (
    echo Installing Pillow, the one library the app needs...
    python -m pip install -r requirements.txt
)

rem Starts without a console window. If nothing appears, run
rem   python govee_controller_v1.4.py
rem in this folder to see the error.
start "" pythonw govee_controller_v1.4.py
