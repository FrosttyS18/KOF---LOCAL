"""Rebuild the BuffSelect Goenitz AI bundle for the PC actor (TEMP outputs only; nothing installed).

Native contract (root, turn 199 candidate + proposal 200): the boss of floor 5+ is a CHARACTER
actor (CharacterManager path, m_characterData NULL/NPC), but its AI graph
BuffSelect_Goenitz_1_Normal reflects over hard-typed members: node10's CheckProperty_Multiplatform
looks up "Monster|get_isHoldAnyUpdate" and nodes 6/36 call "Goenitz|set_actvieCollider" three
times. CheckProperty init resolves the method by reflected type and fails for a Character agent
(root: init FALSE, node10 Failure at the root path while FindWithTag/FindObject actions
succeeded, so the BT does tick). Both members are DECLARED on Actor (get_isHoldAnyUpdate RVA
0x180FF4B30, set_actvieCollider 0x180FF4F00; Character : Actor, Monster : Actor), so switching
only the gate type segment to "Actor" lets this check accept the Character agent. The three
Goenitz collider references remain unchanged; this does not prove the entire boss AI works. Gates, HP phases, skills, nodes, connections, blackboard variables and the
objectReferences list stay byte-identical.

Edit style: NO JSON re-encode. The graph MonoBehaviour body carries the JSON as one
[i32 utf8len][bytes] string; the tool does ONE strict literal replacement ("Monster|" ->
"Actor|", -2 bytes), rewrites the i32 length, recomputes the string's align-4 zero padding
explicitly (old pad asserted zero; suffix glued at oldTextEnd+oldPad), and keeps prefix/suffix
verbatim. The three Goenitz|set_actvieCollider refs are verified verbatim on both sides.
The adapted body is APPENDED 8-aligned at the end of the SerializedFile (the build_alias
append pattern): only the big-endian i64 fileSize @+24, the row's byteStart (8B) and byteSize
(4B) change inside the old stream; every other object's row and bytes stay identical, and the
old graph body remains as unaddressed bytes. The m_Container alias key
(buffselect_goenitz_1_normal_mob.asset -> same pathID) and every other AssetInfo are preserved
byte-identically. assetbundles.info swaps exactly this bundle's 32-char md5; the tooltip (31fb..)
and trigger (7ed8..) hashes stay untouched.

Guards before any write: single serialized node, v22/platform 19 (bundle_layout), input bundle
md5 must be the currently installed 4b9f1b7c5bec30bcea2d259c5f237191, container key resolves to
pathID -1522408046949386238 with m_Name BuffSelect_Goenitz_1_Normal, the gate literal occurs
EXACTLY once and the graph is not already adapted -- a source that is already adapted or
otherwise unexpected aborts without guessing. The assetbundles.info swap is ANCHORED to this
bundle's exact entry (name-resolved via A.parse_index, value verified == input md5) and the
derived manifest is re-parsed and must differ in EXACTLY that one entry. Outputs go
only to --output: the rebuilt bundle under its original md5 bundle-name filename, the derived
assetbundles.info, and report.json. Two runs are byte-identical; the cache input is re-hashed
after the run.

usage: build_buffselect_goenitz_pc.py --cache DIR --output DIR
"""
import argparse
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # the embedded python's _pth never adds the script's own folder
import build_buffselect_ai_alias as A
from build_buffselect_tooltip import rebuild_bundle

BUNDLE_NAME = "prefabs_ai_buffselect"
CONTAINER_KEY = "assets/resources_assetbundles/prefabs/ai/buffselect/buffselect_goenitz_1_normal.asset"
ALIAS_KEY = "assets/resources_assetbundles/prefabs/ai/buffselect/buffselect_goenitz_1_normal_mob.asset"
GRAPH_PID = -1522408046949386238
GRAPH_NAME = "BuffSelect_Goenitz_1_Normal"
INPUT_MD5 = "4b9f1b7c5bec30bcea2d259c5f237191"
REPLACEMENTS = [
    (b"Monster|get_isHoldAnyUpdate|System.Boolean", b"Actor|get_isHoldAnyUpdate|System.Boolean", 1),
]
# Review 199 FINAL: scope is the node10 GATE ONLY. The three Goenitz|set_actvieCollider refs
# stay verbatim (they never failed; gimmicks keep their original semantics).


def fail(msg):
    sys.exit("build_buffselect_goenitz_pc: %s" % msg)


def json_span(body):
    """(len_field_pos, text_pos, text) of the graph's JSON string field, found canonicamente."""
    start = body.find(b'{\x22type\x22:\x22NodeCanvas')
    if start < 0 or body.find(b'{\x22type\x22:\x22NodeCanvas', start + 1) >= 0:
        fail("graph JSON start not unique")
    len_pos = start - 4
    n = struct.unpack_from("<i", body, len_pos)[0]
    if n <= 0 or len_pos + 4 + n > len(body) or body[len_pos + 4:len_pos + 4 + n] != body[start:start + n]:
        fail("graph JSON length field does not describe the text")
    return len_pos, start, n


def verify(in_lay, out_path, new_len_delta):
    """Full canonical reparse of the candidate; every contract clause checked, nothing assumed."""
    out_lay = A.bundle_layout(out_path)
    if len(out_lay["nodes"]) != 1 or out_lay["nodes"][0][2] != in_lay["nodes"][0][2] \
            or out_lay["nodes"][0][3] != in_lay["nodes"][0][3]:
        fail("verify: node descriptor changed")
    d0, d1 = in_lay["info"]["dataOffset"], out_lay["info"]["dataOffset"]
    if d0 != d1:
        fail("verify: dataOffset changed")
    if set(in_lay["rows"]) != set(out_lay["rows"]):
        fail("verify: pathID set changed")
    target = GRAPH_PID
    for pid, r0 in in_lay["rows"].items():
        r1 = out_lay["rows"][pid]
        if r0[4] != r1[4] or r0[5] != r1[5]:
            fail("verify: typeID/classID changed for %d" % pid)
        if pid == target:
            continue
        if (r0[1], r0[3]) != (r1[1], r1[3]):
            fail("verify: row offsets changed for %d" % pid)
        if in_lay["stream"][d0 + r0[1]:d0 + r0[1] + r0[3]] != out_lay["stream"][d1 + r1[1]:d1 + r1[1] + r1[3]]:
            fail("verify: payload bytes changed for %d" % pid)
    r0, r1 = in_lay["rows"][target], out_lay["rows"][target]
    if r1[3] != r0[3] + new_len_delta or r1[3] <= 0:
        fail("verify: target byteSize delta wrong")
    if out_lay["stream"][d0 + r0[1]:d0 + r0[1] + r0[3]] != in_lay["stream"][d0 + r0[1]:d0 + r0[1] + r0[3]]:
        fail("verify: old graph body not preserved verbatim")
    # old-stream byte diffs confined to fileSize i64 @24 + target row byteStart/byteSize fields
    changed = {i for i in range(len(in_lay["stream"])) if in_lay["stream"][i] != out_lay["stream"][i]}
    allowed = set(range(24, 32)) | set(range(r0[0], r0[0] + 8)) | set(range(r0[2], r0[2] + 4))
    if not changed <= allowed:
        fail("verify: old-stream diffs outside the three fields: %s" % sorted(changed - allowed)[:6])
    # semantic graph diff: exactly the four _baseInfo tokens
    import json as J
    def graph_of(lay, row):
        body = lay["stream"][d1 + row[1]:d1 + row[1] + row[3]]
        lp, tp, n = json_span(body)
        return J.loads(body[tp:tp + n].decode("utf-8", "replace"))
    g0, g1 = graph_of(in_lay, r0), graph_of(out_lay, r1)
    if len(g1["nodes"]) != len(g0["nodes"]) or len(g1["nodes"]) != 64:
        fail("verify: node count changed")
    diffs = []

    def scan(a, b, path):
        if isinstance(a, dict) and isinstance(b, dict):
            if set(a) != set(b):
                diffs.append((path, "keys"))
                return
            for k in a:
                scan(a[k], b[k], path + "." + k)
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                diffs.append((path, "len"))
                return
            for i, (x, y) in enumerate(zip(a, b)):
                scan(x, y, path + "[%d]" % i)
        elif a != b:
            diffs.append((path, a, b))
    scan(g0, g1, "$")
    ok = all(d[1] == "Monster|get_isHoldAnyUpdate|System.Boolean"
             and d[2] == "Actor|get_isHoldAnyUpdate|System.Boolean"
             for d in diffs if len(d) == 3)
    if len(diffs) != 1 or not ok or not diffs[0][0].endswith("_baseInfo"):
        fail("verify: semantic diff is not exactly the one gate _baseInfo: %s" % diffs[:6])
    # the three collider refs stay byte-identical in the new text (review 199 scope)
    def body_of(lay, row):
        return lay["stream"][d1 + row[1]:d1 + row[1] + row[3]]
    if body_of(out_lay, out_lay["rows"][target]).count(b"Goenitz|set_actvieCollider") != 3 \
            or b"Actor|set_actvieCollider" in body_of(out_lay, out_lay["rows"][target]):
        fail("verify: collider refs not preserved verbatim")
    # container preserved byte-identically, alias included
    def container_of(lay):
        row = next(x for x in lay["rows"].values() if x[5] == 142)
        body = lay["stream"][d1 + row[1]:d1 + row[1] + row[3]]
        return A.parse_container(body)
    c0, c1 = container_of(in_lay), container_of(out_lay)
    if c0["entries"] != c1["entries"] or c0["name"] != c1["name"] \
            or c0["preloads"] != c1["preloads"] or c0["remainder"] != c1["remainder"]:
        fail("verify: AssetBundle container changed")
    if dict(c1["entries"]).get(ALIAS_KEY) is None or \
            struct.unpack("<iiiq", dict(c1["entries"])[ALIAS_KEY])[3] != GRAPH_PID:
        fail("verify: alias key no longer points at the graph pathID")
    return r1, diffs


def main():
    ap = argparse.ArgumentParser(description="one gate reflection type-token edit (Monster|->Actor|) "
                                             "on the Goenitz AI graph, appended-copy style "
                                             "(TEMP outputs only; never touches the cache)")
    ap.add_argument("--cache", required=True, help="the client's storage/cache directory (read-only)")
    ap.add_argument("--output", required=True, help="TEMP output directory for the rebuilt files")
    args = ap.parse_args()
    cache = os.path.abspath(args.cache)
    out_dir = os.path.abspath(args.output)
    if os.path.commonpath([cache, out_dir]) == cache:
        fail("output directory must not live inside the cache")
    src = os.path.join(cache, "assetbundles", hashlib.md5(BUNDLE_NAME.encode()).hexdigest())
    if not os.path.isfile(src):
        fail("no cached bundle for %s" % BUNDLE_NAME)
    raw = open(src, "rb").read()
    input_md5 = hashlib.md5(raw).hexdigest()
    if input_md5 != INPUT_MD5:
        fail("input md5 %s is not the installed %s -- refusing to guess" % (input_md5, INPUT_MD5))

    lay = A.bundle_layout(src)
    if len(lay["nodes"]) != 1:
        fail("bundle carries %d nodes; single-node only" % len(lay["nodes"]))
    d = lay["info"]["dataOffset"]
    r142 = next((x for x in lay["rows"].values() if x[5] == 142), None)
    if r142 is None:
        fail("no AssetBundle object")
    container = A.parse_container(lay["stream"][d + r142[1]:d + r142[1] + r142[3]])
    entries = dict(container["entries"])
    if CONTAINER_KEY not in entries:
        fail("container lacks the base graph key")
    if struct.unpack("<iiiq", entries[CONTAINER_KEY])[3] != GRAPH_PID:
        fail("base key does not resolve to pathID %d" % GRAPH_PID)
    row = lay["rows"].get(GRAPH_PID)
    if row is None:
        fail("graph object row missing")
    body = lay["stream"][d + row[1]:d + row[1] + row[3]]
    n_len = struct.unpack_from("<i", body, 28)[0]
    if body[32:32 + n_len].decode("utf-8", "replace") != GRAPH_NAME:
        fail("graph m_Name is not %s" % GRAPH_NAME)

    len_pos, text_pos, text_n = json_span(body)
    text = body[text_pos:text_pos + text_n]
    new_text = text
    for old, new, count in REPLACEMENTS:
        if text.count(old) != count or b"Actor|" + old.split(b"|", 1)[1] in text:
            fail("literal %r occurs %d times (expected %d) or already adapted -- aborting"
                 % (old, text.count(old), count))
        new_text = new_text.replace(old, new)
    # the three collider refs must survive verbatim (review 199 scope)
    if new_text.count(b"Goenitz|set_actvieCollider") != 3:
        fail("Goenitz|set_actvieCollider count changed -- aborting")
    delta = len(new_text) - len(text)
    if delta != -2:
        fail("text delta %d is not -2" % delta)
    # explicit padding recompute: the string field is [i32 len][utf8][align-4 zeros]
    old_text_end = text_pos + text_n
    old_pad = (-old_text_end) % 4
    if body[old_text_end:old_text_end + old_pad] != b"\0" * old_pad:
        fail("old string padding is not zero bytes -- refusing to guess layout")
    new_pad = (-(len_pos + 4 + len(new_text))) % 4
    new_body = (body[:len_pos] + struct.pack("<i", len(new_text)) + new_text
                + b"\0" * new_pad + body[old_text_end + old_pad:])
    if len(new_body) != len(body) + delta - old_pad + new_pad:
        fail("body length recompute mismatch")

    stream = bytearray(lay["stream"])
    pad = (8 - len(stream) % 8) % 8
    append_at = len(stream) + pad
    stream += b"\0" * pad + new_body
    struct.pack_into(">q", stream, 24, len(stream))                      # BE i64 fileSize @+24
    struct.pack_into("<q", stream, row[0], append_at - d)               # byteStart (dataOffset-relative)
    struct.pack_into("<I", stream, row[2], len(new_body))
    n_off, n_size, n_flags, n_name = lay["nodes"][0]
    out = rebuild_bundle(raw, lay["flags"], [(n_off, len(stream), n_flags, n_name)], bytes(stream))
    out_md5 = hashlib.md5(out).hexdigest()

    index = open(os.path.join(cache, "assetbundles.info"), "rb").read()
    # anchor the swap to THIS bundle's entry: name-resolve via parse_index, verify value == input
    entries = A.parse_index(index)
    hit = [(n, v) for n, v in entries if n == BUNDLE_NAME]
    if len(hit) != 1 or hit[0][1] != input_md5:
        fail("assetbundles.info entry for %s is %r, expected the input md5" % (BUNDLE_NAME, hit))
    name_at = index.find(BUNDLE_NAME.encode())
    value_at = index.find(input_md5.encode(), name_at)
    if value_at < 0 or index.find(BUNDLE_NAME.encode(), name_at + 1) >= 0:
        fail("cannot anchor the hash swap to this bundle's single entry")
    new_index = bytearray(index)
    new_index[value_at:value_at + 32] = out_md5.encode()
    # re-parse the derived manifest: exactly one entry changed, and it is this bundle's
    new_entries = A.parse_index(bytes(new_index))
    if [e for e in new_entries if e[0] != BUNDLE_NAME] != [e for e in entries if e[0] != BUNDLE_NAME] \
            or dict(new_entries)[BUNDLE_NAME] != out_md5:
        fail("derived assetbundles.info verification failed")

    # full verification from a TEMP copy -- never the cache, and the output dir stays absent on abort
    import tempfile
    probe_fd, probe = tempfile.mkstemp(prefix="goenitz_pc_verify_")
    os.write(probe_fd, out)
    os.close(probe_fd)
    try:
        r1, diffs = verify(lay, probe, len(new_body) - len(body))
    finally:
        os.remove(probe)
    if hashlib.md5(open(src, "rb").read()).hexdigest() != input_md5:
        fail("input file changed during the run")

    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, hashlib.md5(BUNDLE_NAME.encode()).hexdigest()), "wb").write(out)
    open(os.path.join(out_dir, "assetbundles.info"), "wb").write(new_index)
    json.dump({"bundle": BUNDLE_NAME, "graph": {"pid": GRAPH_PID, "name": GRAPH_NAME,
                                                "old_byte_start": row[1], "old_byte_size": row[3],
                                                "new_byte_start": r1[1], "new_byte_size": r1[3]},
               "edits": [{"path": d[0], "old": d[1], "new": d[2]} for d in diffs],
               "textDelta": delta, "input": {"md5": input_md5, "size": len(raw)},
               "output": {"md5": out_md5, "size": len(out)},
               "index_hash_swapped": {"from": input_md5, "to": out_md5}},
              open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8"), indent=1)
    print("verified: gate _baseInfo Monster|->Actor| (1 path); 3 collider refs verbatim; 64 nodes; "
          "container+alias intact")
    print("NOTE: this is the minimal fix the data supports (NECESSARY candidate); sufficiency for "
          "the boss attacking is NOT claimed without a live run.")
    print("graph %d: %d@%d -> %d@%d appended (text %d bytes)" % (GRAPH_PID, row[3], row[1],
                                                                 r1[3], r1[1], delta))
    print("bundle %d -> %d bytes | index hash %s -> %s" % (len(raw), len(out), input_md5, out_md5))
    print("outputs: %s" % out_dir)


if __name__ == "__main__":
    main()
