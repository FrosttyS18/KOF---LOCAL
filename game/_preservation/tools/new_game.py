"""Start over as a brand-new player: the next sign-in creates a new account and plays the first-time start.

- server/state/save.json is moved to server/state/backup/save-<time>.json (restore it by moving it back);
- the client's own prefs (storage/cache/kofallstar.prefs, AES with keys from NMRestApi.PlayerPrefs.Load) get
  CompleteBattleTutorial and TutorialSkipState removed (AutoSelectSupport off): SceneLogin.DisplayNext sends an account without a nickname
  to the battle tutorial (scene 4) only while CompleteBattleTutorial is not 1, otherwise straight to the nickname.
  A copy of the prefs file is kept next to the save backup;
- server/state/options.json gets the flow, which decides whether the new account starts main tutorial 101;
- the starter trio follows the flow: gen_starters.py --flow and build_tables.py are rerun.
Flows: 2023 (default) = nickname -> starter -> story chapter 1 "First Step" (main tutorial 101, tools/gen_story.py);
2018 = the battle tutorial (tools/gen_tutorial.py) -> nickname -> starter -> lobby.
The game must be closed (it rewrites the prefs file on exit). Only these keys are touched; nothing is printed
from the prefs (it holds a previous owner's sign-in email).

usage: python new_game.py [--flow 2023|2018] [--keep-save] [--normal]     --keep-save: only reset the flags
The new account is a test player with endless AP, gold, rubies and items (server/gameapi.py UNLIMITED_*);
--normal makes it a regular one (start money and the real costs).
"""
import base64, json, os, shutil, subprocess, sys, time

from Crypto.Cipher import AES

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PREFS = os.path.abspath(os.path.join(ROOT, "..", "storage", "cache", "kofallstar.prefs"))
SAVE = os.path.join(ROOT, "server", "state", "save.json")
OPTIONS = os.path.join(ROOT, "server", "state", "options.json")   # gameapi.new_player_flow
BACKUP = os.path.join(ROOT, "server", "state", "backup")
KEY, IV = b"KoFallStaR!@PC#$", b"PC%^wInDoWsPrEfs"   # SecureKey.Decrypt(file, key, iv) in PlayerPrefs.Load


def game_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq KOF ALLSTAR.exe"], capture_output=True, text=True).stdout
    return "KOF ALLSTAR.exe" in out


def load_prefs():
    data = AES.new(KEY, AES.MODE_CBC, IV).decrypt(base64.b64decode(open(PREFS, "rb").read()))
    return json.loads(data[:-data[-1]].decode("utf-8"))


def save_prefs(prefs):
    raw = json.dumps(prefs, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    pad = 16 - len(raw) % 16
    enc = AES.new(KEY, AES.MODE_CBC, IV).encrypt(raw + bytes([pad]) * pad)
    open(PREFS, "wb").write(base64.b64encode(enc))


def main():
    flow = sys.argv[sys.argv.index("--flow") + 1] if "--flow" in sys.argv else "2023"
    if flow not in ("2023", "2018"):
        sys.exit("--flow is 2023 or 2018")
    if game_running():
        sys.exit("close the game first (it writes its prefs on exit)")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    os.makedirs(BACKUP, exist_ok=True)
    if "--keep-save" not in sys.argv and os.path.exists(SAVE):
        shutil.move(SAVE, os.path.join(BACKUP, f"save-{stamp}.json"))
        print(f"account moved to server/state/backup/save-{stamp}.json")
    shutil.copy2(PREFS, os.path.join(BACKUP, f"kofallstar-{stamp}.prefs"))
    prefs = load_prefs()
    prefs["CompleteBattleTutorial"] = "1" if flow == "2023" else "0"
    prefs.pop("TutorialSkipState", None)
    # the install's prefs have Auto-Select Support on (previous owner): it skips SELECT SUPPORTER and its guide
    prefs["AutoSelectSupport"] = "0"
    save_prefs(prefs)
    assert load_prefs()["CompleteBattleTutorial"] == prefs["CompleteBattleTutorial"]
    options = json.load(open(OPTIONS, encoding="utf-8")) if os.path.exists(OPTIONS) else {}
    options["newPlayerFlow"] = flow
    # a test player: endless AP, gold, rubies and items (gameapi.UNLIMITED_*); --normal plays with the real amounts
    options["unlimitedNewAccounts"] = "--normal" not in sys.argv
    json.dump(options, open(OPTIONS, "w", encoding="utf-8"), indent=1)
    for cmd in (["gen_starters.py", "--flow", flow], ["build_tables.py"]):  # the client reads the tables at start
        run = subprocess.run([sys.executable, "-I", os.path.join(HERE, cmd[0])] + cmd[1:], capture_output=True,
                             text=True, encoding="utf-8", errors="replace")
        if run.returncode:
            sys.exit(f"{cmd[0]} failed: {run.stdout}{run.stderr}")
        print(run.stdout.strip().splitlines()[0 if cmd[0] == "gen_starters.py" else -1])
    print(f"new-player flow {flow}: the next new account starts with "
          + ("the nickname, then story chapter 1" if flow == "2023" else "the battle tutorial"))


if __name__ == "__main__":
    main()
