"""Rebind the BuffSelect Goenitz graph's dead Skill5/Skill7 BBParameters to the fighter
template's finisher/ultimate blackboard vars so the 3rd+ cast cycle has a live Skill object.

INPUT:  --cache DIR (read-only; must hold assetbundles/prefabs_ai_buffselect with md5
        bafa7295bef1bb60ab324f8a8a694515 and a matching assetbundles.info entry).
        --output DIR receives the candidate bundle (md5-named) + derived assetbundles.info +
        skillref-report.json; it must live outside the cache and nothing is installed.
        --check --cache DIR is read-only state probing (no writes).
ADAPTATION: graph BuffSelect_Goenitz_1_Normal (pid -1522408046949386238) -- node 44/47
        skill refs Skill7 -> UltimateSkill/d205d8a4-0ca8-430d-98f1-a683ba566c05, node 59
        Skill5 -> FinishSkill01/7240f1da-a860-4121-85c6-43f3ff3c06a8 (BBParameters resolve by
        _targetVariableID then _name, so both fields change: 4 parameters, 8 JSON fields).
PRESERVATION: append-copy writer -- only the graph object moves (byteStart/byteSize, fileSize
        @24 BE); the other 18 objects stay byte-identical; UnityFS flags, node table and resS
        are untouched; the buffselect_goenitz_1_normal_mob container alias keeps pointing at
        the graph; the Actor|get_isHoldAnyUpdate gate and the 3 Goenitz|set_actvieCollider
        refs are asserted intact; assetbundles.info swaps exactly this bundle's md5. The
        output md5 is pinned to 1f6a3ad5347347e81446a1f162cf7dc2 and a cache already carrying
        it is reported already-adapted with no writes.

usage: python build_buffselect_goenitz_skill_refs.py --cache DIR --output DIR
       python build_buffselect_goenitz_skill_refs.py --check --cache DIR
"""
import argparse
import hashlib
import json
import os
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_buffselect_ai_alias as A
import read_unity_typed_fields as T
from build_buffselect_tooltip import rebuild_bundle

BUNDLE_NAME = "prefabs_ai_buffselect"
GRAPH_PID = -1522408046949386238
GRAPH_NAME = "BuffSelect_Goenitz_1_Normal"
INPUT_MD5 = "bafa7295bef1bb60ab324f8a8a694515"
OUTPUT_MD5 = "1f6a3ad5347347e81446a1f162cf7dc2"
ALIAS_KEY = "assets/resources_assetbundles/prefabs/ai/buffselect/buffselect_goenitz_1_normal_mob.asset"
RENAMES = {
    "Skill7": ("UltimateSkill", "d205d8a4-0ca8-430d-98f1-a683ba566c05"),
    "Skill5": ("FinishSkill01", "7240f1da-a860-4121-85c6-43f3ff3c06a8"),
}
RENAMED_FROM = {"UltimateSkill": "Skill7", "FinishSkill01": "Skill5"}
EXPECTED_COUNTS = {"Skill7": 2, "Skill5": 2}


def fail(msg):
    sys.exit("build_buffselect_goenitz_skill_refs: %s" % msg)


def graph_json_span(body):
    start = body.find(b'{"type":"NodeCanvas')
    if start < 0 or body.find(b'{"type":"NodeCanvas', start + 1) >= 0:
        fail("graph JSON start not unique")
    len_pos = start - 4
    n = struct.unpack_from("<i", body, len_pos)[0]
    if n <= 0 or len_pos + 4 + n > len(body):
        fail("graph JSON length field broken")
    return len_pos, start, n


def check(cache):
    src = os.path.join(cache, "assetbundles", hashlib.md5(BUNDLE_NAME.encode()).hexdigest())
    state = hashlib.md5(open(src, "rb").read()).hexdigest()
    if state == OUTPUT_MD5:
        print(json.dumps({"state": "already-adapted", "md5": state}))
        return 0
    if state == INPUT_MD5:
        print(json.dumps({"state": "pristine", "md5": state}))
        return 3
    fail("cache bundle md5 %s is neither pristine %s nor adapted %s" % (state, INPUT_MD5, OUTPUT_MD5))


def main():
    ap = argparse.ArgumentParser(description="rebind the Goenitz graph's dead skill refs to "
                                             "the fighter template finisher/ultimate vars")
    ap.add_argument("--cache", required=True)
    ap.add_argument("--output")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    cache = os.path.abspath(args.cache)
    if args.check:
        sys.exit(check(cache))
    if not args.output:
        fail("--output is required unless --check")
    out_dir = os.path.abspath(args.output)
    if os.path.commonpath([cache, out_dir]) == cache:
        fail("output inside cache")
    src = os.path.join(cache, "assetbundles", hashlib.md5(BUNDLE_NAME.encode()).hexdigest())
    raw = open(src, "rb").read()
    input_md5 = hashlib.md5(raw).hexdigest()
    if input_md5 == OUTPUT_MD5:
        print(json.dumps({"state": "already-adapted", "md5": input_md5}))
        return
    if input_md5 != INPUT_MD5:
        fail("input md5 %s != pinned %s" % (input_md5, INPUT_MD5))
    index = open(os.path.join(cache, "assetbundles.info"), "rb").read()
    entries = A.parse_index(index)
    hit = [e for e in entries if e[0] == BUNDLE_NAME]
    if not hit or hit[0][1] != input_md5:
        fail("assetbundles.info does not match the cached bundle")
    value_at = index.index(input_md5.encode(), index.index(BUNDLE_NAME.encode()))

    tb = T.load_typed_bundle(src)
    stream, rows = tb["stream"], tb["rows"]
    lay = A.bundle_layout(src)
    d = lay["info"]["dataOffset"]
    row = rows.get(GRAPH_PID) or fail("graph row missing")
    body = stream[row["offset"]:row["offset"] + row["size"]]
    len_pos, text_pos, n = graph_json_span(body)
    text = body[text_pos:text_pos + n]

    new_text = text
    for old, (new, guid) in RENAMES.items():
        old_pair = ('"_name":"%s","_targetVariableID":"' % old).encode()
        if new_text.count(old_pair) != EXPECTED_COUNTS[old]:
            fail("pattern %r occurs %d times (expected %d)"
                 % (old_pair, new_text.count(old_pair), EXPECTED_COUNTS[old]))
        new_text = new_text.replace(old_pair, ('"_name":"%s","_targetVariableID":"' % new).encode())
        # swap the GUID that immediately follows this renamed _name field
        parts = new_text.split(('"_name":"%s","_targetVariableID":"' % new).encode())
        rebuilt = parts[0]
        for p in parts[1:]:
            end = p.find(b'"')
            rebuilt += ('"_name":"%s","_targetVariableID":"' % new).encode() + guid.encode() + p[end:]
        new_text = rebuilt
    delta = len(new_text) - len(text)
    if delta <= 0 or delta % 4:
        fail("unexpected text delta %d" % delta)
    old_end = text_pos + n
    old_pad = (-old_end) % 4
    if body[old_end:old_end + old_pad] != b"\0" * old_pad:
        fail("old padding not zeros")
    new_pad = (-(len_pos + 4 + len(new_text))) % 4
    new_body = body[:len_pos] + struct.pack("<i", len(new_text)) + new_text \
        + b"\0" * new_pad + body[old_end + old_pad:]

    stream = bytearray(stream)
    pad = (8 - len(stream) % 8) % 8
    append_at = len(stream) + pad
    stream += b"\0" * pad + new_body
    struct.pack_into(">q", stream, 24, len(stream))
    struct.pack_into("<q", stream, lay["rows"][GRAPH_PID][0], append_at - d)
    struct.pack_into("<I", stream, lay["rows"][GRAPH_PID][2], len(new_body))
    stream = bytes(stream)

    n_off, n_size, n_flags, n_name = lay["nodes"][0]
    out = rebuild_bundle(raw, lay["flags"], [(n_off, len(stream), n_flags, n_name)], stream)
    out_md5 = hashlib.md5(out).hexdigest()
    if out_md5 != OUTPUT_MD5:
        fail("output md5 %s != pinned %s" % (out_md5, OUTPUT_MD5))
    new_index = bytearray(index)
    new_index[value_at:value_at + 32] = out_md5.encode()
    idx2 = A.parse_index(bytes(new_index))
    if dict(idx2)[BUNDLE_NAME] != out_md5 or \
            [(a, b) for a, b in idx2 if a != BUNDLE_NAME] != [(a, b) for a, b in entries if a != BUNDLE_NAME]:
        fail("index verification failed")

    fd, probe = tempfile.mkstemp(prefix="goenitz_skill_verify_")
    os.write(fd, out)
    os.close(fd)
    try:
        tb2 = T.load_typed_bundle(probe)
        lay2 = A.bundle_layout(probe)
        expected_nodes = [(n_off, len(stream), n_flags, n_name)]
        if [tuple(x) for x in lay2["nodes"]] != expected_nodes:
            fail("node table changed: %r != %r" % (lay2["nodes"], expected_nodes))
        for pid in rows:
            if pid == GRAPH_PID:
                continue
            if tb2["rows"][pid] != rows[pid]:
                fail("row %d changed" % pid)
        for pid, r0 in rows.items():
            if pid == GRAPH_PID:
                continue
            r1 = tb2["rows"][pid]
            if stream[r0["offset"]:r0["offset"] + r0["size"]] != \
                    tb2["stream"][r1["offset"]:r1["offset"] + r1["size"]]:
                fail("object %d bytes changed" % pid)
        new_row = tb2["rows"][GRAPH_PID]
        gbody = tb2["stream"][new_row["offset"]:new_row["offset"] + new_row["size"]]
        if b"Actor|get_isHoldAnyUpdate" not in gbody:
            fail("Actor gate missing")
        if gbody.count(b"Goenitz|set_actvieCollider") != 3:
            fail("collider refs changed")
        if gbody.count(b'"_name":"Skill7"') or gbody.count(b'"_name":"Skill5"'):
            fail("old skill refs remain")
        for new, guid in RENAMES.values():
            if gbody.count(('"_name":"%s","_targetVariableID":"%s"' % (new, guid)).encode()) \
                    != EXPECTED_COUNTS[RENAMED_FROM[new]]:
                fail("rename %s not applied" % new)
        pid142 = [p for p, r in tb2["rows"].items() if r["classID"] == 142][0]
        r142 = tb2["rows"][pid142]
        c = A.parse_container(tb2["stream"][r142["offset"]:r142["offset"] + r142["size"]])
        if struct.unpack("<iiiq", dict(c["entries"])[ALIAS_KEY])[3] != GRAPH_PID:
            fail("alias container broken")
        diffs = []
        g0 = json.loads(text.decode("utf-8", "replace"))
        g1 = json.loads(new_text.decode("utf-8", "replace"))

        def scan(a, b, path):
            if isinstance(a, dict) and isinstance(b, dict):
                for k in a:
                    scan(a[k], b[k], path + "." + k)
            elif isinstance(a, list) and isinstance(b, list):
                for i, (x, y) in enumerate(zip(a, b)):
                    scan(x, y, path + "[%d]" % i)
            elif a != b:
                diffs.append((path, a, b))
        scan(g0, g1, "$")
        if len(diffs) != 8 or not all(p.endswith(("_name", "_targetVariableID"))
                                      and isinstance(a, str) for p, a, b in diffs):
            fail("semantic diff not exactly 8 ref fields: %s" % diffs[:8])
    finally:
        os.remove(probe)
    if hashlib.md5(open(src, "rb").read()).hexdigest() != input_md5:
        fail("input changed during run")

    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, hashlib.md5(BUNDLE_NAME.encode()).hexdigest()), "wb").write(out)
    open(os.path.join(out_dir, "assetbundles.info"), "wb").write(bytes(new_index))
    json.dump({"bundle": BUNDLE_NAME, "input_md5": input_md5, "output_md5": out_md5,
               "renames": [{"old": o, "new": n, "guid": g, "count": EXPECTED_COUNTS[o]}
                           for o, (n, g) in RENAMES.items()],
               "graph": {"pid": GRAPH_PID, "old_size": row["size"], "new_size": len(new_body)},
               "verify": "19 objects strict; 18 byte-identical; gate+colliders+alias intact; diff==8 fields"},
              open(os.path.join(out_dir, "skillref-report.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps({"candidate_md5": out_md5, "renames": EXPECTED_COUNTS, "output": out_dir}))


if __name__ == "__main__":
    main()
