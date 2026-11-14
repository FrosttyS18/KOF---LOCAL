"""Build replacement master-data tables for the offline server.

The original tables are AES-encrypted with a key only Netmarble's server knew. This writes our own tables
in the format the client expects, encrypted with the key the local server hands out (server/keys.json):

    file = AES-128-CBC(key, iv, PKCS7)( zip{ one entry: payload } )
    payload = protobuf: repeated field 1 = row message (schema from server/tables/schema.json)
    hash   = md5(payload) hex, listed in table.kof / lang_<lang>.kof by the server (server/tables/hashes.json)

Output goes to storage/cache/table/offline_common and offline_lang_<lang> (the patched client reads those;
the original encrypted tables stay untouched). Every other table gets an empty placeholder file there: an
unlisted table is loaded as plain data with no hash, so the client skips it and it stays empty.

Sources (server/tables/data/):
  <TableClass>.json        {"rows": [{field: value, ...}, ...]}   field names without the leading "_"
  strings_<lang>.json      {"tag": "text", ...}                    real text, overrides everything else
Localized strings go into the SystemTable string set: the 256 real BuildSystem strings from the built-in
bundle, every System.* tag found in the client code (placeholder text derived from the tag), then strings_<lang>.json.

usage: python build_tables.py [--lang en]
"""
import hashlib, io, json, os, re, struct, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "server"))
import kofcrypto

ROOT = os.path.dirname(HERE)
SERVER = os.path.join(ROOT, "server")
TABLES = os.path.join(SERVER, "tables")
DATA = os.path.join(TABLES, "data")
CACHE = os.path.abspath(os.path.join(ROOT, "..", "storage", "cache"))
ORIG = os.path.join(CACHE, "table")

SCHEMA = json.load(open(os.path.join(TABLES, "schema.json"), encoding="utf-8"))
LANG_TABLE = "SystemTable"  # localized System.* strings were shipped in lang_<lang>/systemtable.bin


# ---------------------------------------------------------------- protobuf encoding
def varint(n):
    if n < 0:
        n += 1 << 64
    out = bytearray()
    while True:
        b = n & 0x7F; n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def key(num, wire):
    return varint(num << 3 | wire)


SCALAR_VARINT = {"int", "uint", "long", "ulong", "short", "ushort", "byte", "sbyte", "bool"}


def encode_value(ftype, value, num, wire):
    """Encode one field occurrence (not repeated)."""
    if ftype == "string":
        b = str(value).encode("utf-8")
        return key(num, 2) + varint(len(b)) + b
    if ftype == "float":
        return key(num, 5) + struct.pack("<f", float(value))
    if ftype == "double":
        return key(num, 1) + struct.pack("<d", float(value))
    if ftype in SCALAR_VARINT or wire == 0:
        return key(num, 0) + varint(int(value))
    if ftype in SCHEMA["protos"]:
        b = encode_row(ftype, value)
        return key(num, 2) + varint(len(b)) + b
    raise ValueError(f"cannot encode type {ftype}")


def is_default(v):
    return v in (0, 0.0, "", False, None) or v == [] or v == {}


def encode_row(proto, row):
    fields = {f["name"].lstrip("_"): f for f in SCHEMA["protos"][proto]["fields"]}
    out = bytearray()
    for name, value in row.items():
        f = fields.get(name)
        if f is None:
            raise KeyError(f"{proto}: unknown field {name!r}; known: {sorted(fields)}")
        if is_default(value):
            continue
        num, wire, ftype = f["num"], f["wire"], f["type"]
        m = re.match(r"(?:readonly )?RepeatedField<(.+)>", ftype)
        if m:
            inner = m.group(1)
            if inner in SCALAR_VARINT and wire == 2:  # packed
                body = b"".join(varint(int(v)) for v in value)
                out += key(num, 2) + varint(len(body)) + body
            elif inner in ("float",) and wire == 2:
                body = b"".join(struct.pack("<f", float(v)) for v in value)
                out += key(num, 2) + varint(len(body)) + body
            else:
                for v in value:
                    out += encode_value(inner, v, num, wire)
        else:
            out += encode_value(ftype, value, num, wire)
    return bytes(out)


def encode_table(proto, rows):
    out = bytearray()
    for r in rows:
        b = encode_row(proto, r)
        out += key(1, 2) + varint(len(b)) + b
    return bytes(out)


# ---------------------------------------------------------------- container: zip + AES
def pack_file(payload, entry, k):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(entry, payload)
    return kofcrypto.encrypt(buf.getvalue(), (bytes.fromhex(k["key"]), bytes.fromhex(k["iv"])))


# ---------------------------------------------------------------- string sources
def builtin_strings(lang):
    path = os.path.join(TABLES, f"buildsystem_{lang}.txt")
    out = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            if "\t" in line:
                tag, text = line.rstrip("\n").split("\t", 1)
                out[tag] = text
    return out


def placeholder(tag):
    """'System.IDCreate.NicknameMsg.Name' -> 'IDCreate NicknameMsg' (the original text is lost).
    Screen titles read as words: 'System.TopMenuText.FighterList.Name' -> 'Fighter List'."""
    parts = tag.split(".")[1:]
    if parts and parts[-1] in ("Name", "Desc", "Msg", "Text"):
        parts = parts[:-1]
    if len(parts) == 2 and parts[0] == "TopMenuText":
        return re.sub(r"(?<=[a-zA-Z])(?=[A-Z][a-z])", " ", parts[1])
    return " ".join(parts) or tag


def code_tags():
    lits = json.load(open(os.path.join(ROOT, "dump", "stringliteral.json"), encoding="utf-8"))
    rx = re.compile(r"^System\.[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)+$")
    return sorted({l["value"] for l in lits if rx.match(l["value"])})


def strings_for(lang):
    s = {t: placeholder(t) for t in code_tags()}
    real = builtin_strings(lang)
    s.update(real)
    extra = os.path.join(DATA, f"strings_{lang}.json")
    user = json.load(open(extra, encoding="utf-8")) if os.path.exists(extra) else {}
    s.update(user)
    return s, len(real), len(user)


# ---------------------------------------------------------------- main
def main():
    lang = sys.argv[sys.argv.index("--lang") + 1] if "--lang" in sys.argv else "en"
    keys = json.load(open(os.path.join(SERVER, "keys.json"), encoding="utf-8"))
    names = json.load(open(os.path.join(SERVER, "table_names.json"), encoding="utf-8"))  # file stem -> class
    out_common = os.path.join(CACHE, "table", "offline_common")
    out_lang = os.path.join(CACHE, "table", f"offline_lang_{lang}")
    os.makedirs(out_common, exist_ok=True)
    os.makedirs(out_lang, exist_ok=True)
    hashes = {"common": {}, "lang": {}, "prohibited": {}}

    # placeholders for every table the client will look for
    for src, dst in ((os.path.join(ORIG, "common"), out_common), (os.path.join(ORIG, f"lang_{lang}"), out_lang)):
        for f in os.listdir(src):
            open(os.path.join(dst, f), "wb").close()

    # rebuilt common tables
    built = []
    for f in sorted(os.listdir(DATA)) if os.path.isdir(DATA) else []:
        m = re.match(r"^(\w+Table)\.json$", f)
        if not m:
            continue
        table = m.group(1)
        info = SCHEMA["tables"].get(table)
        if info is None:
            print(f"  skip {f}: no table class {table}"); continue
        rows = json.load(open(os.path.join(DATA, f), encoding="utf-8"))["rows"]
        payload = encode_table(info["proto"], rows)
        stem = table.lower()
        open(os.path.join(out_common, stem + ".bin"), "wb").write(pack_file(payload, stem + ".bytes", keys["data_table"]))
        hashes["common"][table] = hashlib.md5(payload).hexdigest()
        built.append(f"{table} ({len(rows)} rows)")
        # a rebuilt table with a language companion (lang_<lang>/<table>.bin) is loaded together with it:
        # give it a valid (empty) string set instead of the 0-byte placeholder, which would fail to decrypt
        if os.path.exists(os.path.join(ORIG, f"lang_{lang}", stem + ".bin")) and table != LANG_TABLE:
            empty = encode_table("DataLocalizingProto", [])
            open(os.path.join(out_lang, stem + ".bin"), "wb").write(pack_file(empty, stem + ".bytes", keys["localizing"]))
            hashes["lang"][table] = hashlib.md5(empty).hexdigest()

    # localized strings -> SystemTable string set (DataLocalizingProto rows: 2 tag, 4 text)
    strings, n_real, n_user = strings_for(lang)
    payload = encode_table("DataLocalizingProto", [{"tag": t, "dst": x} for t, x in sorted(strings.items())])
    stem = LANG_TABLE.lower()
    open(os.path.join(out_lang, stem + ".bin"), "wb").write(pack_file(payload, stem + ".bytes", keys["localizing"]))
    hashes["lang"][LANG_TABLE] = hashlib.md5(payload).hexdigest()

    json.dump(hashes, open(os.path.join(TABLES, "hashes.json"), "w"), indent=1)
    import make_tablepacks
    make_tablepacks.main()
    print(f"common tables rebuilt: {', '.join(built) or 'none'}")
    print(f"{LANG_TABLE} strings: {len(strings)} ({n_real} real built-in, {n_user} from strings_{lang}.json, rest placeholders)")


if __name__ == "__main__":
    main()
