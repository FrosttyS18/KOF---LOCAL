"""Rebuild storage/cache/tablepacks.info from the table files on disk.

The client deletes this index when the selected server name changes (TableUpdateManager.ResetTablePackInfo).
Format: repeated tag 58 (field 7) TablePack{1 pack, 2 version, 3 TableEntry{1 name, 2 size, 3 md5 hex}, 4 reset}.
The local server reports the same VERSION in version.kof, so the client treats the packs as current.

usage: python make_tablepacks.py [--lang en]
"""
import hashlib, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.abspath(os.path.join(HERE, "..", "..", "storage", "cache"))
VERSION = 1025


def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F; n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n: return bytes(out)


def ld(field, payload):
    return varint(field << 3 | 2) + varint(len(payload)) + payload


def entry(name, path):
    data = open(path, "rb").read()
    return ld(1, name.encode()) + varint(2 << 3) + varint(len(data)) + ld(3, hashlib.md5(data).hexdigest().encode())


def pack(name, folder):
    body = ld(1, name.encode()) + varint(2 << 3) + varint(VERSION)
    files = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
    for f in files:
        body += ld(3, entry(f, os.path.join(folder, f)))
    return ld(7, body), len(files)


def main():
    lang = sys.argv[sys.argv.index("--lang") + 1] if "--lang" in sys.argv else "en"
    out = b""
    # the patched client reads rebuilt tables from table/offline_* (see patch_client.py / build_tables.py)
    for name, folder in (("table", "table/offline_common"), ("lang_global", f"table/offline_lang_{lang}"),
                         ("prohibited", "table/prohibited")):
        blob, n = pack(name, os.path.join(CACHE, folder))
        out += blob
        print(f"  {name:12} v{VERSION}  {n} files  ({folder})")
    path = os.path.join(CACHE, "tablepacks.info")
    open(path, "wb").write(out)
    print("wrote", path, len(out), "bytes")


if __name__ == "__main__":
    main()
