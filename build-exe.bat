@echo off
REM ============================================================
REM  Build Zapret Hub into a single installer (Electron + React)
REM  Requires: npm install
REM  ASCII only on purpose - Cyrillic in .bat breaks cmd.exe
REM ============================================================
setlocal

cd /d "%~dp0"

echo [1/5] Checking dependencies...
where npm >nul 2>&1
if errorlevel 1 (
    echo npm not found. Install Node.js 20 LTS first: https://nodejs.org/
    pause
    exit /b 1
)

echo [2/5] Installing packages...
call npm install
if errorlevel 1 (
    echo npm install failed
    pause
    exit /b 1
)

echo [3/5] Typechecking and building...
call npm run build
if errorlevel 1 (
    echo Build failed. See the messages above.
    pause
    exit /b 1
)

echo [4/5] Cleaning previous build...
REM ------------------------------------------------------------------
REM  electron-builder clears release\win-unpacked before unpacking, and
REM  fails with "Access is denied" when something still holds a file
REM  there. Almost always it is the app itself: Zapret Hub lives in the
REM  tray, so closing the window does not close the program. Antivirus
REM  scanners and an open Explorer window hold files too, and they let
REM  go after a moment - hence three attempts with a pause.
REM ------------------------------------------------------------------
if exist "release\win-unpacked" (
    rd /s /q "release\win-unpacked" >nul 2>&1
)
if exist "release\win-unpacked" (
    echo     Waiting for locked files...
    timeout /t 3 /nobreak >nul
    rd /s /q "release\win-unpacked" >nul 2>&1
)
if exist "release\win-unpacked" (
    timeout /t 5 /nobreak >nul
    rd /s /q "release\win-unpacked" >nul 2>&1
)
if exist "release\win-unpacked" (
    echo.
    echo     Could not remove release\win-unpacked - some files are in use.
    echo.
    tasklist /FI "IMAGENAME eq ZapretHub.exe" 2>NUL | find /I "ZapretHub.exe" >NUL
    if not errorlevel 1 (
        echo     Zapret Hub is running and holds its own files.
        echo     Close it for real: tray icon - right click - Exit.
        echo     Closing the window is not enough, the program stays in tray.
        echo.
    )
    echo     Other usual keepers of this folder:
    echo       - an open Explorer window inside release\win-unpacked
    echo       - an antivirus scanner mid-check, or a terminal placed there
    echo.
    echo     Nothing here is deleted while files are locked. Close the keepers
    echo     and run this file again.
    pause
    exit /b 1
)

echo [5/5] Packaging installer...
call npx electron-builder --win --config
if errorlevel 1 (
    echo Packaging failed. See the messages above.
    pause
    exit /b 1
)

echo.
echo Done. The installer is in the release\ folder:
echo     ZapretHub-1.0.4-Setup.exe
echo.
pause
