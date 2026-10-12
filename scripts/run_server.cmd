@echo off
rem ---------------------------------------------------------------------------
rem Start the backend server (used by the Windows startup entry).
rem NOTE: this file is deliberately ASCII-only. cmd.exe reads .cmd files using
rem the OEM code page (GBK on Chinese Windows), so UTF-8 Chinese comments here
rem would get mangled and break parsing.
rem ---------------------------------------------------------------------------
cd /d "%~dp0.."
if not exist "logs" mkdir "logs"

rem If port 8000 is already listening the backend is already running: do not
rem start a second instance (duplicate collectors would double the API cost).
netstat -ano | findstr /r /c:":8000 .*LISTENING" >nul 2>&1
if errorlevel 1 goto start_server
echo [%date% %time%] port 8000 already in use, skip start >> "logs\server.log"
exit /b 0

:start_server
echo. >> "logs\server.log"
echo [%date% %time%] starting backend >> "logs\server.log"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 >> "logs\server.log" 2>&1
