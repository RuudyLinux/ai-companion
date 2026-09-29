@echo off
setlocal
cd /d "%~dp0"

set HOST=127.0.0.1
set PORT=8000
set PIDFILE=%~dp0.server.pid

if exist "%PIDFILE%" (
    set /p OLDPID=<"%PIDFILE%"
    tasklist /FI "PID eq %OLDPID%" 2>NUL | find "%OLDPID%" >NUL
    if not errorlevel 1 (
        echo Server already running with PID %OLDPID%. Run stop.bat first.
        exit /b 1
    )
    del "%PIDFILE%" >NUL 2>&1
)

if not exist "venv\Scripts\python.exe" (
    echo venv not found at venv\Scripts\python.exe -- create it first.
    exit /b 1
)

echo Starting AI Companion server on http://%HOST%:%PORT% ...
del "server.log" >NUL 2>&1
del "server.err.log" >NUL 2>&1
start "" /B cmd /c "venv\Scripts\python.exe -m uvicorn main:app --host %HOST% --port %PORT% > server.log 2> server.err.log"

rem Poll for something to actually bind the port instead of a fixed sleep --
rem model loading (emotion/voice) can take a few seconds on first start.
set LISTENPID=
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$deadline = (Get-Date).AddSeconds(30); $result = $null; while ((Get-Date) -lt $deadline) { $c = Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if ($c) { $result = $c.OwningProcess; break }; Start-Sleep -Milliseconds 500 }; $result"`) do set LISTENPID=%%P

if defined LISTENPID (
    echo %LISTENPID%>"%PIDFILE%"
    echo Server started, PID %LISTENPID%.
    echo Open: http://%HOST%:%PORT%
) else (
    echo Server did not come up on %PORT% within 30s -- check server.err.log
    exit /b 1
)

endlocal
