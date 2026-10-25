@echo off
REM ============================================================
REM  Stop Zapret Hub if the window is stuck
REM  ASCII only on purpose - Cyrillic in .bat breaks cmd.exe
REM ============================================================
setlocal

echo Stopping Zapret Hub...
taskkill /IM "Zapret Hub.exe" /T >nul 2>&1
taskkill /IM electron.exe /T >nul 2>&1
echo Done.
pause
