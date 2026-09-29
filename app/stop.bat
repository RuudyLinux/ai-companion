@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set PORT=8000
set PIDFILE=%~dp0.server.pid

set LISTENPID=
for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess"`) do set LISTENPID=%%A

if defined LISTENPID (
    echo Stopping server on port %PORT%, PID !LISTENPID! ...
    taskkill /F /T /PID !LISTENPID! >NUL 2>&1
    if exist "%PIDFILE%" del "%PIDFILE%" >NUL 2>&1
    echo Server stopped.
    exit /b 0
)

if exist "%PIDFILE%" (
    set /p PID=<"%PIDFILE%"
    tasklist /FI "PID eq !PID!" 2>NUL | find "!PID!" >NUL
    if not errorlevel 1 (
        echo Nothing listening on %PORT%, but PID !PID! from .server.pid is still alive -- stopping it.
        taskkill /F /T /PID !PID! >NUL 2>&1
        del "%PIDFILE%" >NUL 2>&1
        echo Server stopped.
        exit /b 0
    )
    del "%PIDFILE%" >NUL 2>&1
)

echo No server running on port %PORT%.

endlocal
