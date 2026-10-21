@echo off
REM One-laptop demo: rendezvous server + three peers (alice, bob, carol), each in
REM its own window, then alice's dashboard opens in the browser. No admin needed.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py) || (set PY=python)
start "rendezvous server" cmd /k %PY% rendezvous_server.py
timeout /t 1 /nobreak >nul
start "peer alice" cmd /k %PY% peer.py --name alice --http-port 8080
start "peer bob"   cmd /k %PY% peer.py --name bob   --http-port 8081
start "peer carol" cmd /k %PY% peer.py --name carol --http-port 8082
timeout /t 2 /nobreak >nul
start "" http://localhost:8080
