"""Shift the Sura fever bar Container down for the PC client (TEMP outputs only; v1032+).

Native contract (root Ghidra proofs NATIVE/root-sura-hud-placement1032-full.log and
NATIVE/root-sura-selection-placement1032-full.log): ActionUnitUILoad.<LoadUI>b__0
@0x1812fa7b0 parents the prefab under V_BattleInterface/Static/Top and calls
UnityExts.SafeSetIdentify @0x18191e710, which resets position, scale and rotation on the ROOT
Transform only, without iterating children; UIUnit_FeverTime.InitializeUIData @0x4D1180
never repositions Container. The serialized root localPosition (0, 360) therefore does not
survive instantiation, and the durable serialized layout is the root's single top-level
child:

  UIUnit_LimitSliderBar  T#-6347033605064691425  pos=(0, 360)     <- reset at runtime
  +-(only child) Container T#1062708448127383798  pos=(-5, 21.1)  <- edit target
     +-- root (34,-125) > Label_Progress/Percent_Text, Backgorund (typo) > sprSkull,
         objBackground > objDeco_left/right; ProgressGroup; ProgressGroup (1) >
         Background/Foreground/sprThumb > sprTime/sprBG

The change is exactly one 4-byte float: Container Transform m_LocalPosition.y += --dy
(restricted to -120 <= dy < 0 so the bar only moves DOWN). Resolution is a pointer/tree
walk, never a global match; the asserts pin the measured geometry (root y 360, exactly one
top-level child named Container at (-5, 21.1)). Verifier copies build_pc_status_icons_off:
candidate must reparse with identical nodes/info/rows, stream equal to the original except
inside the 4-byte float window, assetbundles.info swapping exactly one md5, input file
byte-stable across the run. Outputs (candidate bundle + candidate assetbundles.info +
report) go to --output only; the cache is never touched. dy=-60 was checked in the live
PC Sura stage 8: the boss name and fever bar remain separately visible at 1280x720.
"""
import argparse
import hashlib
import json
import math
import os
import struct
import sys

BUNDLE_NAME = "prefabs_ui_data_ui_unit_uiunit_limitsliderbar"
ROOT_GO_NAME = "UIUnit_LimitSliderBar"
CONTAINER_GO_NAME = "Container"
ROOT_EXPECTED_Y = 360.0
CONTAINER_EXPECTED = (-5.0, 21.1)
TOL = 0.05
DY_MIN, DY_MAX = -120.0, 0.0


def fail(msg):
    print("error: %s" % msg, file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="Sura fever bar Container Y shift (TEMP only)")
    ap.add_argument("--cache", required=True, help="client assetbundles cache root")
    ap.add_argument("--tools", default=None,
                    help="repo game/_preservation/tools (default: derived from --cache)")
    ap.add_argument("--output", required=True, help="TEMP output dir (must be outside the cache)")
    ap.add_argument("--dy", type=float, required=True,
                    help="Container localPosition.y delta (downward: -120 <= dy < 0)")
    ap.add_argument("--apply", action="store_true", help="write candidate outputs (default: dry-run)")
    args = ap.parse_args()

    if not math.isfinite(args.dy):
        fail("dy must be a finite float, got %r" % args.dy)
    if not (DY_MIN <= args.dy < DY_MAX):
        fail("dy %r outside the allowed downward range [%g, %g)" % (args.dy, DY_MIN, DY_MAX))

    cache = os.path.abspath(args.cache)
    out_dir = os.path.abspath(args.output)
    tools = os.path.abspath(args.tools) if args.tools else \
        os.path.abspath(os.path.join(cache, "..", "..", "_preservation", "tools"))
    if os.path.commonpath([cache, out_dir]) == cache:
        fail("output directory must not live inside the cache")
    sys.path.insert(0, tools)
    import build_buffselect_ai_alias as A
    import read_unity_serialized as U
    import read_unity_typed_fields as T
    from build_buffselect_tooltip import rebuild_bundle

    src = os.path.join(cache, "assetbundles", hashlib.md5(BUNDLE_NAME.encode()).hexdigest())
    if not os.path.isfile(src):
        fail("no cached bundle for %s" % BUNDLE_NAME)
    raw = open(src, "rb").read()
    input_md5 = hashlib.md5(raw).hexdigest()
    index = open(os.path.join(cache, "assetbundles.info"), "rb").read()
    entries = A.parse_index(index)
    hit = [e for e in entries if e[0] == BUNDLE_NAME]
    if not hit or hit[0][1] != input_md5:
        fail("assetbundles.info does not match the cached bundle")
    value_at = index.index(input_md5.encode(), index.index(BUNDLE_NAME.encode()))

    lay = A.bundle_layout(src)
    nodes = lay["nodes"]
    if not (nodes[0][0] == 0 and (len(nodes) == 1 or
                                  (len(nodes) == 2 and nodes[1][3].endswith(".resS")
                                   and nodes[1][0] == nodes[0][1]))):
        fail("unsupported bundle layout (nodes %r)" % (nodes,))
    tb = T.load_typed_bundle(src)
    if tb["info"].get("platform") not in (19, None):
        fail("platform %r is not the PC build" % tb["info"].get("platform"))
    stream = tb["stream"]
    rows, types = tb["rows"], tb["types"]
    _d, gos, _m, trs, _i = U.index_bundle(src)

    def decode(pid):
        row = rows[pid]
        records, consumed = T.decode_object(stream[row["offset"]:row["offset"] + row["size"]],
                                            types[row["typeSlot"]]["nodes"])
        if consumed != row["size"]:
            fail("object %d decodes %d of %d bytes" % (pid, consumed, row["size"]))
        return records

    def pick(records, path_suffix):
        for r in records:
            if r["path"] == path_suffix or r["path"].endswith("." + path_suffix):
                return r
        return None

    def transform_of(go_pid):
        return next((c for c in gos[go_pid]["components"] if c in trs), None)

    root_go = next((pid for pid, g in gos.items() if g["name"] == ROOT_GO_NAME), None)
    if root_go is None:
        fail("no %s GameObject in bundle" % ROOT_GO_NAME)
    root_tr = transform_of(root_go)
    if root_tr is None:
        fail("root has no Transform")
    root_rec = pick(decode(root_tr), "m_LocalPosition.y")
    if root_rec is None or abs(root_rec["value"] - ROOT_EXPECTED_Y) > TOL:
        fail("root localPosition.y is %r, expected %.1f" %
             (root_rec and root_rec["value"], ROOT_EXPECTED_Y))

    children = [c for c in trs[root_tr]["children"] if c in trs]
    if len(children) != 1:
        fail("root has %d transform children, expected exactly 1" % len(children))
    child_tr = children[0]
    child_go = trs[child_tr]["go_pid"]
    if gos[child_go]["name"] != CONTAINER_GO_NAME:
        fail("single top-level child is %r, expected %r" %
             (gos[child_go]["name"], CONTAINER_GO_NAME))
    recs = decode(child_tr)
    x_rec, y_rec = pick(recs, "m_LocalPosition.x"), pick(recs, "m_LocalPosition.y")
    if x_rec is None or y_rec is None or y_rec["size"] != 4:
        fail("Container m_LocalPosition records not resolved")
    if abs(x_rec["value"] - CONTAINER_EXPECTED[0]) > TOL or \
       abs(y_rec["value"] - CONTAINER_EXPECTED[1]) > TOL:
        fail("Container localPosition is (%r, %r), expected (%.1f, %.1f)" %
             (x_rec["value"], y_rec["value"], *CONTAINER_EXPECTED))

    old_y = y_rec["value"]
    new_y = old_y + args.dy
    absolute = rows[child_tr]["offset"] + y_rec["offset"]
    window = list(range(absolute, absolute + 4))
    if bytes(stream[absolute:absolute + 4]) != struct.pack("<f", old_y):
        fail("Container localPosition.y bytes on disk diverge from the decoded value")
    edit = {"pid": child_tr, "field": "m_LocalPosition.y", "size": 4, "float": True,
            "old": old_y, "new": new_y, "absolute": absolute,
            "what": "Container localPosition.y %.4f -> %.4f (dy %g)" % (old_y, new_y, args.dy)}
    report = {
        "bundle": BUNDLE_NAME, "input_md5": input_md5, "apply": args.apply, "dy": args.dy,
        "root": {"go": root_go, "transform": root_tr, "localPositionY": root_rec["value"],
                 "runtime": "position/scale/rotation reset to identity by SafeSetIdentify (root only)"},
        "container": {"go": child_go, "transform": child_tr, "name": gos[child_go]["name"],
                      "localPosition": [x_rec["value"], old_y]},
        "planned_edits": [edit],
        "scope": "single 4-byte float edit on the Container Transform; root reset semantics "
                 "preserved; every other object, node and byte untouched",
        "uncertain": "dy=%g is the root's pick for the first visual check, not a validated " \
                     "value; live in-game confirmation pending after install" % args.dy,
    }
    if not args.apply:
        report["status"] = "dry-run"
        print(json.dumps(report, indent=1))
        print("check only; nothing written")
        return

    expected = bytearray(stream)
    struct.pack_into("<f", expected, absolute, new_y)
    if len(expected) != len(stream):
        fail("stream size changed")
    out = rebuild_bundle(raw, lay["flags"], nodes, bytes(expected))
    out_md5 = hashlib.md5(out).hexdigest()
    new_index = bytearray(index)
    new_index[value_at:value_at + 32] = out_md5.encode()
    idx2 = A.parse_index(bytes(new_index))
    if dict(idx2)[BUNDLE_NAME] != out_md5 or \
            [(n, v) for n, v in idx2 if n != BUNDLE_NAME] != \
            [(n, v) for n, v in entries if n != BUNDLE_NAME]:
        fail("index verification failed")

    os.makedirs(out_dir, exist_ok=True)
    bundle_out = os.path.join(out_dir, hashlib.md5(BUNDLE_NAME.encode()).hexdigest())
    open(bundle_out, "wb").write(out)
    open(os.path.join(out_dir, "assetbundles.info"), "wb").write(bytes(new_index))

    back = A.bundle_layout(bundle_out)
    tback = T.load_typed_bundle(bundle_out)
    if [tuple(n) for n in back["nodes"]] != [tuple(n) for n in nodes]:
        fail("candidate node table differs")
    if back["info"] != lay["info"]:
        fail("candidate info differs")
    if tback["rows"] != rows:
        fail("candidate rows (pathID/offset/size/typeSlot/classID) differ")
    if bytes(tback["stream"]) != bytes(expected):
        fail("candidate stream differs from the patched original (length or bytes); aborting")
    real_diffs = [i for i in range(len(stream)) if stream[i] != tback["stream"][i]]
    if not real_diffs or not set(real_diffs) <= set(window):
        fail("candidate differs from the ORIGINAL outside the 4-byte float window: %r"
             % real_diffs[:8])
    if bytes(tback["stream"][absolute:absolute + 4]) != struct.pack("<f", new_y):
        fail("candidate float at the edit offset is not the planned value")
    if hashlib.md5(open(src, "rb").read()).hexdigest() != input_md5:
        fail("input file changed during the run; outputs are invalid")

    report["candidate_bundle"] = bundle_out
    report["candidate_md5"] = out_md5
    report["reparse"] = ("nodes/info/rows identical; stream == original with the only diffs "
                         "inside the 4-byte m_LocalPosition.y window; manifest swaps exactly "
                         "one md5; input bundle byte-stable")
    open(os.path.join(out_dir, "sura-hud-report.json"), "w", encoding="utf-8").write(
        json.dumps(report, indent=1))
    print(json.dumps({"candidate": bundle_out, "md5": out_md5, "edits": [edit["what"]],
                      "diff_bytes": real_diffs}))


if __name__ == "__main__":
    main()
