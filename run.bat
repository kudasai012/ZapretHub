@echo off
REM ============================================================
REM  Zapret Hub launcher.
REM  ASCII only on purpose: Cyrillic in .bat breaks cmd.exe.
REM
REM  run.bat          - normal start, no console window
REM  run.bat debug    - start with a console, so any traceback is visible
REM
REM  If the program flashes and disappears, run "run.bat debug" and
REM  read the output - it is the actual reason.
REM ============================================================
cd /d "%~dp0"

setlocal

REM --- elevate ourselves ------------------------------------------------
REM winws.exe works through WinDivert and will not start without admin
REM rights. Without this block the program opened just fine but every
REM strategy in Diagnostics reported "no access". We ask for elevation
REM once here instead of failing later inside the app.
net session >nul 2>&1
if errorlevel 1 (
    echo Requesting administrator rights...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
    exit /b
)

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
REM "import PySide6" is NOT enough: the package imports fine while the
REM native QtCore.dll fails to load (missing MSVC redistributable, broken
REM install). That used to look exactly like "the window flashes and dies".
%PYRUN% -c "import PySide6.QtWidgets" >nul 2>&1
if errorlevel 1 (
    echo Dependencies are missing. Installing...
    %PYRUN% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Failed to install dependencies.
        echo Install Python 3.10+ and run this file again.
        pause
        exit /b 1
    )
    echo Re-checking PySide6...
    %PYRUN% -c "import PySide6.QtWidgets"
    if errorlevel 1 (
        echo.
        echo PySide6 still does not import. Most often this is the missing
        echo "Microsoft Visual C++ Redistributable" - install it from
        echo https://aka.ms/vs/17/release/vc_redist.x64.exe and try again.
        echo.
        echo Full error is above. Press any key to exit.
        pause >nul
        exit /b 1
    )
)

REM --- console mode for debugging ---
REM "shift" drops the word "debug" so run.pyw does not receive it.
if /i "%~1"=="debug" (
    shift
    echo Starting Zapret Hub with a console ^(tracebacks will be shown^)...
    %PYRUN% run.pyw %*
    echo.
    echo [exit code %errorlevel%]
    pause
    exit /b %errorlevel%
)

REM --- windowed interpreter (no console window) ---
set "PYW="
where pyw.exe >nul 2>&1 && set "PYW=pyw.exe -3"
if not defined PYW (
    where pythonw.exe >nul 2>&1 && set "PYW=pythonw.exe"
)
if not defined PYW set "PYW=%PYRUN%"

REM A crash inside the program is written to crash.log next to run.bat
REM and shown as a message box - see app/crashlog.py.
start "" %PYW% run.pyw %*
exit /b 0
