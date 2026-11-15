"""Hide the combat-screen Wifi/Battery indicator for the PC client (TEMP outputs only; v1027+).

The indicator is the GameObject 'PhoneInfo' (root of UIUnit_DeviceInfo with children
Wifi/LTE/Disconnect/Battery) inside prefabs_ui_data_ui_game_v_battleinterface; the PC client
is platform 19 with a v22 type tree. The change is exactly ONE serialized byte:
PhoneInfo.m_IsActive true -> false. Disabling the root stops the UIUnit_DeviceInfo
OnEnable/UpdateDeviceInfo cycle wholesale, so no per-child state (Wifi/LTE/Disconnect toggle)
can re-enable pieces; whether any native parent force-activates this root is NOT proven and
stays declared-uncertain until live validation.

Resolution is pointer-exact, never first-global-match: the UIView_BattleInterface
MonoBehaviour (its own GO must be the battle view) -> m_deviceInfo PPtr -> UIUnit_DeviceInfo
MonoBehaviour -> m_GameObject PPtr -> GO named 'PhoneInfo'. Decoding reuses the validated
read_unity_typed_fields (consumed == size required on every object read); the UnityFS writer
is reused from build_buffselect_tooltip.rebuild_bundle unchanged (whole stream as stored
blocks, nodes/resS/rows preserved). The verifier requires the candidate stream to equal the
original with exactly the one byte changed, rows/nodes/info identical, and assetbundles.info
swapping exactly one md5. Outputs go to --output only; the cache is never touched.
"""
import argparse
import hashlib
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_buffselect_ai_alias as A
import read_unity_typed_fields as T
from build_buffselect_tooltip import rebuild_bundle

BUNDLE_NAME = "prefabs_ui_data_ui_game_v_battleinterface"
VIEW_GO_NAME = "V_BattleInterface"
UNIT_TYPE_FIELD = "m_deviceInfo"
INFO_GO_NAME = "PhoneInfo"


def fail(msg):
    print("error: %s" % msg, file=sys.stderr)
    sys.exit(1)


def pick(records, path_suffix):
    for r in records:
        if r["path"] == path_suffix or r["path"].endswith("." + path_suffix):
            return r
    return None


def main():
    ap = argparse.ArgumentParser(description="PC combat Wifi/Battery indicator off "
                                             "(TEMP outputs only; never touches the cache)")
    ap.add_argument("--cache", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--apply", action="store_true")
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
    _d, gos, mbs, trs, _i = __import__("read_unity_serialized").index_bundle(src)

    def decode(pid):
        row = rows[pid]
        records, consumed = T.decode_object(stream[row["offset"]:row["offset"] + row["size"]],
                                            types[row["typeSlot"]]["nodes"])
        if consumed != row["size"]:
            fail("object %d decodes %d of %d bytes" % (pid, consumed, row["size"]))
        return records

    view_pid = unit_mb = None
    for pid, row in rows.items():
        if row["classID"] != 114:
            continue
        node_names = [n["name"] for n in types[row["typeSlot"]]["nodes"]]
        if UNIT_TYPE_FIELD not in node_names:
            continue
        records = decode(pid)
        go = pick(records, "m_GameObject.m_PathID")
        unit = pick(records, UNIT_TYPE_FIELD + ".m_PathID")
        if go and unit and gos.get(go["value"], {}).get("name") == VIEW_GO_NAME \
                and unit["value"] in mbs:
            view_pid, unit_mb = pid, unit["value"]
            break
    if view_pid is None:
        fail("UIView_BattleInterface.m_deviceInfo not resolved")
    unit_records = decode(unit_mb)
    unit_go = pick(unit_records, "m_GameObject.m_PathID")
    if unit_go is None or unit_go["value"] not in gos:
        fail("UIUnit_DeviceInfo GameObject not resolved")
    if gos[unit_go["value"]]["name"] != INFO_GO_NAME:
        fail("UIUnit_DeviceInfo GO is %r, expected %r"
             % (gos[unit_go["value"]]["name"], INFO_GO_NAME))
    info_pid = unit_go["value"]

    active = pick(decode(info_pid), "m_IsActive")
    if active is None or active["size"] != 1:
        fail("PhoneInfo m_IsActive record missing")
    absolute = rows[info_pid]["offset"] + active["offset"]
    if active["value"] is not True or stream[absolute:absolute + 1] != b"\x01":
        fail("PhoneInfo m_IsActive is already false or bytes diverge; aborting")

    edit = {"pid": info_pid, "field": "m_IsActive", "absolute": absolute,
            "old": True, "new": False, "what": "PhoneInfo m_IsActive 1->0"}
    report = {"bundle": BUNDLE_NAME, "input_md5": input_md5,
              "view_pid": view_pid, "deviceinfo_mb": unit_mb, "phoneinfo_go": info_pid,
              "planned_edits": [edit], "apply": args.apply,
              "scope": "single byte PhoneInfo.m_IsActive true->false in the combat UI bundle; "
                       "training interface and scale fallback NOT touched",
              "uncertain": "no proof any native parent cannot force-activate this root; "
                           "requires live validation after install"}
    if not args.apply:
        print(json.dumps(report, indent=1))
        print("check only; nothing written")
        return

    expected = bytearray(stream)
    expected[absolute:absolute + 1] = b"\x00"
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
        fail("candidate rows differ")
    if bytes(tback["stream"]) != bytes(expected):
        fail("candidate stream differs from the patched original (length or bytes); aborting")
    real_diffs = [i for i in range(len(stream)) if stream[i] != tback["stream"][i]]
    if real_diffs != [absolute]:
        fail("candidate differs from the ORIGINAL outside the single m_IsActive byte: %r" % real_diffs[:4])
    if hashlib.md5(open(src, "rb").read()).hexdigest() != input_md5:
        fail("input file changed during the run; outputs are invalid")

    report["candidate_bundle"] = bundle_out
    report["candidate_md5"] = out_md5
    report["reparse"] = ("nodes/info/rows identical; stream == original with exactly one "
                         "byte changed at the PhoneInfo m_IsActive offset; manifest swaps "
                         "exactly one md5")
    open(os.path.join(out_dir, "statusicons-report.json"), "w", encoding="utf-8").write(
        json.dumps(report, indent=1))
    print(json.dumps({"candidate": bundle_out, "md5": out_md5, "edits": [edit["what"]]}))


if __name__ == "__main__":
    main()
