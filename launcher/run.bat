@echo off
REM ============================================================
REM  Run Zapret Hub straight from the source folder
REM  Double-click this file - no commands to type
REM
REM  What it does, in order:
REM    1. checks that Node.js is installed
REM    2. installs packages if node_modules is missing
REM    3. builds the app if out\ is missing
REM    4. starts the app
REM
REM  ASCII only on purpose - Cyrillic in .bat breaks cmd.exe
REM ============================================================
setlocal
cd /d "%~dp0.."

echo [1/4] Checking Node.js...
where node >nul 2>&1
if errorlevel 1 (
    echo.
    echo Node.js was not found.
    echo Install Node.js 20 LTS from https://nodejs.org/ and run this file again.
    echo.
    pause
    exit /b 1
)

echo [2/4] Checking packages...
if not exist "node_modules" (
    echo Installing packages, this takes a minute...
    call npm install
    if errorlevel 1 (
        echo.
        echo npm install failed. Check the messages above.
        echo.
        pause
        exit /b 1
    )
)

echo [3/4] Checking the build...
if not exist "out\main\index.js" (
    if not exist "out\renderer\index.html" (
        echo Building the app...
        call npm run build
        if errorlevel 1 (
            echo.
            echo Build failed. Check the messages above.
            echo.
            pause
            exit /b 1
        )
    )
)

echo [4/4] Starting Zapret Hub...
echo.
echo The app window opens in a moment.
echo This window stays open while the app runs - closing it closes the app too.
echo.
call npx electron .
echo.
echo The app has closed.
pause
