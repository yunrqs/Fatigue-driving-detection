@echo off
setlocal
rem One-click launcher. Real work lives in start.ps1; this wrapper only keeps the
rem window open when something fails, so a double-click shows the reason.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
set "START_EXIT_CODE=%ERRORLEVEL%"

rem 0 is a clean exit. The rest are the codes Windows reports for Ctrl+C
rem (-1073741510 / 3221225786 / 130): the user stopped the frontend on purpose,
rem so pausing for a keypress there is just noise.
if "%START_EXIT_CODE%"=="0" exit /b 0
if "%START_EXIT_CODE%"=="-1073741510" exit /b 0
if "%START_EXIT_CODE%"=="3221225786" exit /b 0
if "%START_EXIT_CODE%"=="130" exit /b 0

echo.
echo [start.cmd] Startup failed with exit code %START_EXIT_CODE%.
echo Backend logs: backend\outputs\dev\
echo.
pause
exit /b %START_EXIT_CODE%
