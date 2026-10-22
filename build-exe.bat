@echo off
REM ============================================================
REM  Build Zapret Hub into a single installer (Electron + React)
REM  Requires: npm install
REM  ASCII only on purpose - Cyrillic in .bat breaks cmd.exe
REM ============================================================
setlocal

cd /d "%~dp0"

echo [1/4] Checking dependencies...
where npm >nul 2>&1
if errorlevel 1 (
    echo npm not found. Install Node.js 20 LTS first: https://nodejs.org/
    pause
    exit /b 1
)

echo [2/4] Installing packages...
call npm install
if errorlevel 1 (
    echo npm install failed
    pause
    exit /b 1
)

echo [3/4] Typechecking and building...
call npm run build
if errorlevel 1 (
    echo Build failed. See the messages above.
    pause
    exit /b 1
)

echo [4/4] Packaging installer...
call npx electron-builder --win --config
if errorlevel 1 (
    echo Packaging failed. See the messages above.
    pause
    exit /b 1
)

echo.
echo Done. The installer is in the release\ folder:
echo     ZapretHub-1.0.2-Setup.exe
echo.
pause
