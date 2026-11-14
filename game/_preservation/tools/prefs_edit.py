"""Edit named keys of a NMRestApi.PlayerPrefs file (base64(AES-CBC(JSON)), e.g. a test copy in server/state/backup).
Only the named keys are shown or changed: the file can hold personal data, so it is never printed whole.
usage: prefs_edit.py <prefs file> [--show KEY] [--del KEY] [--set KEY=VALUE] ...   (options may repeat)"""
import base64
import json
import sys

from Crypto.Cipher import AES

KEY, IV = b"KoFallStaR!@PC#$", b"PC%^wInDoWsPrEfs"


def load(path):
    data = AES.new(KEY, AES.MODE_CBC, IV).decrypt(base64.b64decode(open(path, "rb").read()))
    return json.loads(data[:-data[-1]].decode("utf-8"))


def save(path, prefs):
    raw = json.dumps(prefs, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    pad = 16 - len(raw) % 16
    open(path, "wb").write(base64.b64encode(AES.new(KEY, AES.MODE_CBC, IV).encrypt(raw + bytes([pad]) * pad)))


def main():
    path, args = sys.argv[1], sys.argv[2:]
    prefs, changed = load(path), False
    for opt, val in zip(args[::2], args[1::2]):
        if opt == "--show":
            print(val, "=", repr(prefs.get(val)))
        elif opt == "--del":
            changed |= prefs.pop(val, None) is not None
            print("deleted" if changed else "absent", val)
        elif opt == "--set":
            k, v = val.split("=", 1)
            prefs[k], changed = v, True
            print("set", k)
    if changed:
        save(path, prefs)


if __name__ == "__main__":
    main()
