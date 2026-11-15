"""Rebuild the BuffSelect lobby tooltip bundle for the PC client (TEMP outputs only; v1026+).

Native contract (root-confirmed): the lobby tooltip ROOT is repositioned dynamically by
HandleMessage 0x1805226C0 (telegram 0x3DF from OnClickSlot 0x181AAB2F0) and
UIUnit_SimpleTextToolTip.SetData never touches pivots or localPositions, so serialized child
pivots persist. Field decoding reuses the validated read_unity_typed_fields (root: 3131/3131
objects decode with consumed == size). Exactly three in-place 4-byte edits inside the
Non-Scroll branch of the tooltip prefab:
  m_lblText (NonScroll)  UIWidget.mPivot     8 -> 6
  m_sprTextBg            UIWidget.mPivot     8 -> 6
  m_sprTextBg Transform  m_LocalPosition.x  18.0 -> -18.0
Width 630 and the SCROLL branch stay untouched. The UnityFS writer keeps both nodes
(names/offsets/sizes/flags), the .resS bytes, every row (pathID/offset/size/typeSlot/classID)
and the whole stream except those three 4-byte ranges; blockinfo = [16B hash][blockCount]
[ALL >IIH block records][>I nodeCount][ALL >qqI+name node descriptors]; assetbundles.info
swaps exactly one md5. Outputs go to --output only; the cache is never touched.
"""
import argparse
import hashlib
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_buffselect_ai_alias as A
import read_unity_serialized as U
import read_unity_typed_fields as T

BUNDLE_NAME = "prefabs_ui_data_ui_game_v_buffselectdungeonlobby"
VIEW_GO_NAME = "V_BuffSelectDungeonLobby"
NOSCROLL_LABEL = "m_lblText (NonScroll)"
NOSCROLL_BG = "m_sprTextBg"


def fail(msg):
    print("error: %s" % msg, file=sys.stderr)
    sys.exit(1)


def pick(records, path_suffix):
    for r in records:
        if r["path"] == path_suffix or r["path"].endswith("." + path_suffix):
            return r
    return None


def rebuild_bundle(raw, flags, nodes, stream):
    new_flags = (flags & ~0x3F) | 0
    descriptors = bytearray()
    node_entries = bytearray()
    blocks_out = bytearray()
    count = 0
    for n_off, n_size, n_flags, n_name in nodes:
        piece = bytes(stream[n_off:n_off + n_size])
        if len(piece) != n_size:
            fail("node bytes do not reconstruct to their declared size")
        for i in range(0, n_size, A.BLOCK_SIZE):
            b = piece[i:i + A.BLOCK_SIZE]
            descriptors += struct.pack(">IIH", len(b), len(b), 0)
            blocks_out += b
            count += 1
        node_entries += struct.pack(">qqI", n_off, n_size, n_flags) + n_name.encode() + b"\0"
    new_bi = bytearray(16) + struct.pack(">I", count) + descriptors \
        + struct.pack(">i", len(nodes)) + node_entries
    u1 = raw.index(b"\0", 12)
    u2 = raw.index(b"\0", u1 + 1)
    out = bytearray(raw[:12])
    out += raw[12:u2 + 1]
    size_at = len(out)
    out += struct.pack(">QIII", 0, len(new_bi), len(new_bi), new_flags)
    while len(out) % 16:
        out += b"\0"
    out += new_bi
    if new_flags & 0x200:
        while len(out) % 16:
            out += b"\0"
    out += blocks_out
    struct.pack_into(">Q", out, size_at, len(out))
    return bytes(out)


def main():
    ap = argparse.ArgumentParser(description="scoped BuffSelect lobby NonScroll tooltip fix "
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
    if not (len(nodes) == 1 or (len(nodes) == 2 and nodes[1][3].endswith(".resS")
                                and nodes[1][0] == nodes[0][1])):
        fail("unsupported bundle layout (%d nodes)" % len(nodes))
    tb = T.load_typed_bundle(src)
    stream = tb["stream"]
    rows = tb["rows"]
    types = tb["types"]
    _d, gos, mbs, trs, _i = U.index_bundle(src)

    def decode(pid):
        row = rows[pid]
        records, consumed = T.decode_object(stream[row["offset"]:row["offset"] + row["size"]],
                                            types[row["typeSlot"]]["nodes"])
        if consumed != row["size"]:
            fail("object %d decodes %d of %d bytes" % (pid, consumed, row["size"]))
        return records

    view_pid = tip_mb = None
    for pid, row in rows.items():
        if row["classID"] != 114:
            continue
        node_names = [n["name"] for n in types[row["typeSlot"]]["nodes"]]
        if "m_unitTooltip" not in node_names:
            continue
        records = decode(pid)
        go = pick(records, "m_GameObject.m_PathID")
        tip = pick(records, "m_unitTooltip.m_PathID")
        if go and tip and gos.get(go["value"], {}).get("name") == VIEW_GO_NAME:
            view_pid, tip_mb = pid, tip["value"]
            break
    if view_pid is None:
        fail("view MonoBehaviour not resolved")
    if tip_mb not in mbs:
        fail("m_unitTooltip target is not a local MonoBehaviour")
    tip_go = mbs[tip_mb]["go_pid"]

    def find_descendant(go_pid, want, depth=0):
        if depth > 4:
            return None
        transform = next((c for c in gos[go_pid]["components"] if c in trs), None)
        if transform is None:
            return None
        for ch in trs[transform]["children"]:
            if ch not in trs:
                continue
            child_go = trs[ch]["go_pid"]
            if gos[child_go]["name"] == want:
                return child_go
            found = find_descendant(child_go, want, depth + 1)
            if found is not None:
                return found
        return None

    label_go = find_descendant(tip_go, NOSCROLL_LABEL)
    bg_go = find_descendant(tip_go, NOSCROLL_BG)
    if label_go is None or bg_go is None:
        fail("NonScroll label/background not found under the tooltip root")

    def widget_pid(go_pid):
        for pid, mb in mbs.items():
            if mb["go_pid"] != go_pid:
                continue
            node_names = [n["name"] for n in types[rows[pid]["typeSlot"]]["nodes"]]
            if "mPivot" not in node_names:
                continue
            decode(pid)
            return pid
        return None

    label_pid = widget_pid(label_go)
    bg_pid = widget_pid(bg_go)
    if label_pid is None or bg_pid is None:
        fail("NonScroll widgets carry no UIWidget component")
    bg_transform = next((c for c in gos[bg_go]["components"] if c in trs), None)
    if bg_transform is None:
        fail("background has no Transform")

    edits = []
    for pid, what in ((label_pid, NOSCROLL_LABEL), (bg_pid, NOSCROLL_BG)):
        record = pick(decode(pid), "mPivot")
        if record["value"] != 8 or record["size"] != 4:
            fail("%s mPivot is %r, expected 8" % (what, record["value"]))
        edits.append({"pid": pid, "field": "mPivot", "size": 4, "old": 8, "new": 6,
                      "absolute": rows[pid]["offset"] + record["offset"],
                      "what": "%s mPivot 8->6" % what})
    x_record = pick(decode(bg_transform), "m_LocalPosition.x")
    if x_record["value"] != 18.0 or x_record["size"] != 4:
        fail("background localPosition.x is %r, expected 18.0" % x_record["value"])
    edits.append({"pid": bg_transform, "field": "m_LocalPosition.x", "size": 4,
                  "old": 18.0, "new": -18.0, "float": True,
                  "absolute": rows[bg_transform]["offset"] + x_record["offset"],
                  "what": "%s Transform localPosition.x 18.0->-18.0" % NOSCROLL_BG})

    geometry = {"tooltip_go": tip_go,
                "label": {"go": label_go, "pid": label_pid},
                "background": {"go": bg_go, "pid": bg_pid, "transform": bg_transform}}
    report = {"bundle": BUNDLE_NAME, "input_md5": input_md5, "geometry": geometry,
              "planned_edits": edits, "apply": args.apply,
              "scope": "NonScroll label+background pivots 8->6 and background x 18->-18; "
                       "width 630 and SCROLL branch intentionally untouched"}
    if not args.apply:
        print(json.dumps(report, indent=1))
        print("check only; nothing written")
        return

    expected = bytearray(stream)
    for e in edits:
        fmt = "<f" if e.get("float") else "<i"
        if bytes(expected[e["absolute"]:e["absolute"] + 4]) != struct.pack(fmt, e["old"]):
            fail("field %s changed on disk before write" % e["what"])
        expected[e["absolute"]:e["absolute"] + 4] = struct.pack(fmt, e["new"])
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
    if tback["stream"] != bytes(expected):
        fail("candidate stream differs from the patched original (length or bytes); aborting")
    if hashlib.md5(open(src, "rb").read()).hexdigest() != input_md5:
        fail("input file changed during the run; outputs are invalid")

    report["candidate_bundle"] = bundle_out
    report["candidate_md5"] = out_md5
    report["field_deltas"] = [{"pid": e["pid"], "field": e["field"],
                               "absolute": e["absolute"], "old": e["old"], "new": e["new"]}
                              for e in edits]
    report["reparse"] = ("nodes/info/rows identical; stream differs only inside the three "
                         "4-byte ranges; manifest swaps exactly one md5")
    open(os.path.join(out_dir, "tooltip-report.json"), "w", encoding="utf-8").write(
        json.dumps(report, indent=1))
    print(json.dumps({"candidate": bundle_out, "md5": out_md5,
                      "edits": [e["what"] for e in edits]}))


if __name__ == "__main__":
    main()
