"""KOF ALLSTAR Offline launcher: start the local server, start the game, stop the server when the game closes.

usage: pythonw launcher.pyw [--fullscreen]
Runs from the package folder (setup\\ next to game\\ and python\\). No console window; errors show a message box.
"""
import ctypes
import importlib.util
import os
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = os.path.join(ROOT, "game")
EXE = os.path.join(GAME, "KOF ALLSTAR.exe")
SERVER_DIR = os.path.join(GAME, "_preservation", "server")
LOGS = os.path.join(SERVER_DIR, "logs")
PYTHON = os.path.join(ROOT, "python", "python.exe")
PORT = 18080
NO_WINDOW = 0x08000000                      # CREATE_NO_WINDOW
TITLE = "KOF ALLSTAR Offline"


def message(text, error=True):
    ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x10 if error else 0x40)


def port_open(port=PORT):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def game_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq KOF ALLSTAR.exe", "/NH"], capture_output=True, text=True,
                         creationflags=NO_WINDOW).stdout
    return "KOF ALLSTAR.exe" in out


def start_server():
    """Start kofserver.py hidden; None when one is already listening (it is reused and left running)."""
    if port_open():
        return None
    os.makedirs(LOGS, exist_ok=True)
    log = open(os.path.join(LOGS, "server.log"), "w", encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    proc = subprocess.Popen([PYTHON, os.path.join(SERVER_DIR, "kofserver.py")], cwd=SERVER_DIR, stdout=log,
                            stderr=subprocess.STDOUT, env=env, creationflags=NO_WINDOW)
    for _ in range(60):                     # up to 30 s (the first start compiles the server)
        if port_open():
            return proc
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    proc.kill()
    raise RuntimeError("The local server did not start. See:\n" + os.path.join(LOGS, "server.log"))


def show_login_banner():
    """The Preservation Progress banner (a CHECK-IN LOG tab) opens only on the day's first sign-in: make every one
    count (tools/login_banner.py)."""
    try:
        sys.path.insert(0, os.path.join(GAME, "_preservation", "tools"))
        import login_banner
        login_banner.reset(os.path.join(GAME, "storage", "cache", "kofallstar.prefs"))
    except Exception:                       # noqa: BLE001 - the banner is optional
        pass


def start_game(fullscreen):
    # The exe's manifest asks for administrator (for the anti-cheat driver the patch replaced): run it un-elevated.
    env = dict(os.environ, __COMPAT_LAYER="RunAsInvoker")
    if fullscreen:
        args = ["-screen-fullscreen", "1"]
    else:
        args = ["-screen-fullscreen", "0", "-screen-width", "1280", "-screen-height", "720"]
    args += ["-logFile", os.path.join(LOGS, "player.log")]
    game = subprocess.Popen([EXE] + args, cwd=GAME, env=env)
    try:
        spec = importlib.util.spec_from_file_location("kof_client_compat", os.path.join(ROOT, "setup", "client_compat.py"))
        compat = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(compat)
        compat.apply_reward_compat(game, os.path.join(GAME, "GameAssembly.dll"))
    except Exception:
        if game.poll() is None:
            game.terminate()
            game.wait(5)
        raise
    return game


def main():
    if not os.path.isfile(EXE):
        return message("The game was not found:\n" + EXE)
    if game_running():
        return message("KOF ALLSTAR is already running.", error=False)
    server = None
    try:
        server = start_server()
        show_login_banner()
        game = start_game("--fullscreen" in sys.argv)
        game.wait()
        time.sleep(1)
        while game_running():               # in case the exe handed over to another process
            time.sleep(2)
    except Exception as e:                  # noqa: BLE001 - shown to the player
        message(str(e))
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(10)
            except subprocess.TimeoutExpired:
                server.kill()


if __name__ == "__main__":
    main()
