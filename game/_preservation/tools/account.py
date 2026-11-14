"""Switch the game between saved accounts without losing one. The game must be closed (it writes its prefs on exit).

An account is two files: the server's save (server/state/save.json: fighters, items, story, missions) and the
client's prefs (storage/cache/kofallstar.prefs: settings, sign-in, tutorial flags). Saved accounts are pairs in
server/state/backup: save-<name>.json + kofallstar-<name>.prefs (new_game.py and the test scripts make them too).

  python tools/account.py              list the saved accounts; marks the one in place and your own ("home")
  python tools/account.py use NAME     put saved account NAME in place, e.g. test-20261026-exp
  python tools/account.py home         put your own account back
  python tools/account.py unlimited on|off   endless AP, gold, rubies, currencies and items for the account in place
                                       (save.json "unlimited", server/gameapi.py UNLIMITED_*; test accounts have it)
  python tools/account.py allcores on|off    every spot of every fighter's core board unlocked (save.json "allCores")
  python tools/account.py spcards on|off     one of every special (SP) battle card (save.json "allSpecialCards")

Before an account is replaced it is saved as save-<date-time>.json (+ prefs), unless an identical pair exists, so
nothing played is lost. The first switch away from your own account remembers it as "home" (backup/home.txt);
`home` puts it back and forgets that. Nothing is printed from the prefs (it holds a previous owner's sign-in email).
"""
import filecmp, json, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SAVE = os.path.join(ROOT, "server", "state", "save.json")
PREFS = os.path.abspath(os.path.join(ROOT, "..", "storage", "cache", "kofallstar.prefs"))
BACKUP = os.path.join(ROOT, "server", "state", "backup")
HOME = os.path.join(BACKUP, "home.txt")


def game_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq KOF ALLSTAR.exe"], capture_output=True, text=True).stdout
    return "KOF ALLSTAR.exe" in out


def pair(name):
    return os.path.join(BACKUP, f"save-{name}.json"), os.path.join(BACKUP, f"kofallstar-{name}.prefs")


def saved():
    """names of the saved pairs, oldest first"""
    names = [f[5:-5] for f in os.listdir(BACKUP) if f.startswith("save-") and f.endswith(".json")]
    return sorted((n for n in names if os.path.exists(pair(n)[1])), key=lambda n: os.path.getmtime(pair(n)[0]))


def in_place():
    """the saved pair identical to the account in place, or None"""
    if not (os.path.exists(SAVE) and os.path.exists(PREFS)):
        return None
    for n in reversed(saved()):
        s, p = pair(n)
        if filecmp.cmp(s, SAVE, shallow=False) and filecmp.cmp(p, PREFS, shallow=False):
            return n
    return None


def keep():
    """save the account in place unless an identical pair exists -> its name"""
    name = in_place()
    if name is None:
        name = time.strftime("%Y%m%d-%H%M%S")
        s, p = pair(name)
        shutil.copy2(SAVE, s)
        shutil.copy2(PREFS, p)
        print(f"kept the account in place as {name}")
    return name


def home():
    return open(HOME, encoding="utf-8").read().strip() if os.path.exists(HOME) else None


def use(name):
    s, p = pair(name)
    if not (os.path.exists(s) and os.path.exists(p)):
        sys.exit(f"no saved account {name} (server/state/backup/save-{name}.json + kofallstar-{name}.prefs)")
    if game_running():
        sys.exit("close the game first (it writes its prefs on exit)")
    kept = keep() if os.path.exists(SAVE) else None
    if home() is None and kept is not None:
        open(HOME, "w", encoding="utf-8").write(kept)   # the account in place before the first switch is yours
    shutil.copy2(s, SAVE)
    shutil.copy2(p, PREFS)
    if name == home():
        os.remove(HOME)
    print(f"account in place: {name}" + ("" if home() else "  (your own)"))


def describe(name):
    try:
        st = json.load(open(pair(name)[0], encoding="utf-8"))
    except ValueError:                          # e.g. save-20261030-194429: all zero bytes
        return f"{name:26s} unreadable (damaged save file)"
    made = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.get("created", 0) / 1000))
    return (f"{name:26s} made {made}  rank EXP {st.get('exp', 0):4}  stages cleared {len(st.get('stages', {})):3}"
            + ("  unlimited" if st.get("unlimited") else ""))


def switch(key, on, what):
    if game_running():
        sys.exit("close the game first (the server rewrites save.json while it plays)")
    st = json.load(open(SAVE, encoding="utf-8"))
    st[key] = on
    json.dump(st, open(SAVE, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"{what} {'on' if on else 'off'} for the account in place (from its next sign-in)")


def unlimited(on):
    switch("unlimited", on, "unlimited resources")


def main():
    args = sys.argv[1:]
    if args[:1] == ["use"] and len(args) == 2:
        name = os.path.basename(args[1])               # also takes new_game.py's "server/state/backup/save-<x>.json"
        name = name[5:] if name.startswith("save-") else name
        use(name[:-5] if name.endswith(".json") else name)
    elif args[:1] == ["unlimited"] and args[1:] in (["on"], ["off"]):
        unlimited(args[1] == "on")
    elif args[:1] == ["allcores"] and args[1:] in (["on"], ["off"]):
        switch("allCores", args[1] == "on", "every fighter's core board fully unlocked")
    elif args[:1] == ["spcards"] and args[1:] in (["on"], ["off"]):
        switch("allSpecialCards", args[1] == "on", "one of every special (SP) battle card")
    elif args == ["home"]:
        if home() is None:
            print("your own account is in place already")
        else:
            use(home())
    elif not args:
        here, mine = in_place(), home() or in_place()
        for n in saved():
            print(describe(n) + ("  <- in place" if n == here else "") + ("  (your own)" if n == mine else ""))
        if here is None:
            print("in place: an account not saved yet (it is kept when you switch)")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
