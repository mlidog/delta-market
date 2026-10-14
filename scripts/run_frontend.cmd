@echo off
rem ---------------------------------------------------------------------------
rem Start the Vite dev server for the dashboard (http://127.0.0.1:5173).
rem NOTE: ASCII-only on purpose. cmd.exe reads .cmd files with the OEM code page
rem (GBK on Chinese Windows), so UTF-8 Chinese comments here would break parsing.
rem ---------------------------------------------------------------------------
cd /d "%~dp0.."
if not exist "logs" mkdir "logs"

rem Do not start a second instance if 5173 is already listening.
netstat -ano | findstr /r /c:":5173 .*LISTENING" >nul 2>&1
if errorlevel 1 goto start_frontend
echo [%date% %time%] port 5173 already in use, skip start >> "logs\frontend.log"
exit /b 0

:start_frontend
echo. >> "logs\frontend.log"
echo [%date% %time%] starting frontend dev server >> "logs\frontend.log"
cd frontend
call npm.cmd run dev -- --host 127.0.0.1 >> "..\logs\frontend.log" 2>&1
