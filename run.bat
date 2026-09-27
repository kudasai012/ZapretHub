@echo off
REM ============================================================
REM  Zapret Hub launcher.
REM  ASCII only on purpose: Cyrillic in .bat breaks cmd.exe.
REM ============================================================
cd /d "%~dp0"

REM --- find a working Python (py launcher, then python) ---
set "PYRUN="
where py.exe >nul 2>&1 && set "PYRUN=py.exe -3"
if not defined PYRUN (
    where python.exe >nul 2>&1 && set "PYRUN=python.exe"
)
if not defined PYRUN (
    echo Python not found.
    echo Install Python 3.10+ from https://www.python.org/downloads/
    echo and make sure "Add Python to PATH" is checked.
    pause
    exit /b 1
)

REM --- dependencies ---
%PYRUN% -c "import PySide6" >nul 2>&1
if errorlevel 1 (
    echo Dependencies are missing. Installing...
    %PYRUN% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Failed to install dependencies.
        echo Install Python 3.10+ and run this file again.
        pause
        exit /b 1
    )
)

REM --- windowed interpreter (no console window) ---
set "PYW="
where pyw.exe >nul 2>&1 && set "PYW=pyw.exe -3"
if not defined PYW (
    where pythonw.exe >nul 2>&1 && set "PYW=pythonw.exe"
)
if not defined PYW set "PYW=%PYRUN%"

start "" %PYW% run.pyw %*
exit /b 0
