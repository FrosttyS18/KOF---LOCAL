@echo off
title KOF ALLSTAR Offline - Local server
rem Starts the local offline server in this window, then the game. Keep this window open while you play;
rem close it or press Ctrl+C to stop the server.
rem First run on this PC: restore the game's Windows settings (graphics, sign-in email, ...) from the package.
reg query "HKCU\Software\Netmarble Corp.\KOF ALLSTAR" >nul 2>&1 || reg import "%~dp0setup\game_settings.reg" >nul 2>&1
cd /d "%~dp0game\_preservation\server"
set PY="%~dp0python\python.exe"
%PY% -c "import socket,sys; sys.exit(socket.socket().connect_ex((\"127.0.0.1\",18080))==0)"
if errorlevel 1 (
  echo The local server is already running on port 18080. Starting the game.
  start "" "%~dp0python\pythonw.exe" "%~dp0setup\launcher.pyw" %*
  exit /b
)
echo Starting the local server on port 18080, then the game. Close this window or press Ctrl+C to stop the server.
set PYTHONIOENCODING=utf-8
start "" /b %PY% -c "import socket,time,subprocess,sys; [time.sleep(0.5) for _ in range(60) if socket.socket().connect_ex((\"127.0.0.1\",18080))]; subprocess.Popen([sys.argv[1], sys.argv[2]] + sys.argv[3:])" "%~dp0python\pythonw.exe" "%~dp0setup\launcher.pyw" %*
%PY% kofserver.py
pause
