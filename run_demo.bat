@echo off
REM One-laptop demo: rendezvous server + two peers, each in its own window,
REM then both dashboards open in the browser. Close the windows to stop.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py) || (set PY=python)
start "rendezvous server" cmd /k %PY% rendezvous_server.py
timeout /t 1 /nobreak >nul
start "peer alice" cmd /k %PY% peer.py --name alice --http-port 8080
start "peer bob"   cmd /k %PY% peer.py --name bob   --http-port 8081
timeout /t 2 /nobreak >nul
start "" http://localhost:8080
start "" http://localhost:8081
