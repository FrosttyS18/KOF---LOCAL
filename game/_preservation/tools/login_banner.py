"""Make the next sign-in count as the day's first, so the CHECK-IN LOG (and its Preservation Progress tab,
tools/gen_progress.py) opens at every sign-in: removes PlayerPrefs "FirstLogin" from kofallstar.prefs.
Run with the game closed (tools/relaunch.ps1 and the package launcher do it before starting the game).
usage: login_banner.py [prefs file]   (default: the game's storage/cache/kofallstar.prefs)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prefs_edit  # noqa: E402

DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "storage", "cache", "kofallstar.prefs")


def reset(path=DEFAULT):
    if not os.path.isfile(path):
        return False
    prefs = prefs_edit.load(path)
    if "FirstLogin" not in prefs:
        return False
    del prefs["FirstLogin"]
    prefs_edit.save(path, prefs)
    return True


if __name__ == "__main__":
    print("FirstLogin cleared" if reset(*(sys.argv[1:2] or [DEFAULT])) else "nothing to clear")
