"""Point CameraSet 401 -- GameDefine.modeDuelCameraIndex, the duel camera every duel-mode
battle resolves through NativeCameraInitialize (sub_151D570) -- at the PC client's true
InGameCameraVS prefab.

Root-measured cause (native-analysis, Temp/codex-kofas-zcode-bridge-review): the VM snapshot
root-prove-mode-duel-camera-index-1029.json shows NativeCameraInitialize resolving the Prove
(duel) camera through GameDefine.modeDuelCameraIndex = 401 -- NOT through the 30 Prove stages'
QuestEventStage cameraSetStart/cameraSetBoss rows, so the earlier 101->401 QuestEventStage
rewrite was a refuted hypothesis and QuestEventStageTable is never touched here. CameraSet
401 points at Prefabs/Camera/Camera_InGame_VS, whose root GameObject carries only the generic
InGameCamera stack, so CameraManager.InGameCameras never holds an InGameCameraVS and
Controller_Single_Duel.m_vsCamera (+0x30) stays null (root-prove-stuck-controller-1029.json:
vsCamera null while the model, moving wall and interface slots are live) until
<NextRound>d__55.MoveNext (sub_1527180) dereferences it and throws NullReferenceException
(ghidra-camerainit.log, ghidra-nextround.log). The cached prefabs_camera bundle ships
Camera_InGame_VS_2, whose root GameObject (container key
assets/resources_assetbundles/prefabs/camera/camera_ingame_vs_2.prefab) carries the
InGameCameraVS MonoBehaviour with the orbit fields the duel controller drives; the minimal
data fix is the single cameraSetPrefab string on row 401.

This tool never writes the master: default mode only CHECKS; --output DIR writes a TEMP
candidate CameraSetTable.json (the one-field adaptation; all 9 rows, every other field and
their order preserved) plus a report. Accepted row-401 states are exactly the original
(Camera_InGame_VS) and the adapted (Camera_InGame_VS_2; a re-run finds zero changes).
Anything else aborts before any candidate is emitted, as do a row count other than 9, a
missing or duplicated cameraSetIndex 401, a prefab diverging from the pinned strings, an
--output that resolves inside the repository, the data dir or the cache, and any asset
verification failure: the bundle revision digest pinned below, the container root pointing at
the pinned GameObject, the GameObject/MonoBehaviour linkage in both directions, the pinned
type slot and script id, the required InGameCameraVS fields, and a full typed decode
(consumed == object size) for every checked object.

usage: adapt_prove_pc_camera.py [--data DIR] [--cache DIR] [--output DIR]
"""
import argparse
import copy
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import read_unity_typed_fields

DATA = os.path.normpath(os.path.join(HERE, "..", "server", "tables", "data"))
CACHE = os.path.abspath(os.path.join(HERE, "..", "..", "storage", "cache"))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

TABLE = "CameraSetTable"
ROW_COUNT = 9
VS_INDEX = 401
VS_PREFAB = "Prefabs/Camera/Camera_InGame_VS"
VS2_PREFAB = "Prefabs/Camera/Camera_InGame_VS_2"

CAMERA_BUNDLE = "prefabs_camera"
BUNDLE_REVISION = "b97365fbc5c9222a61f5c82dcf5c5601"
CONTAINER_KEY = "assets/resources_assetbundles/prefabs/camera/camera_ingame_vs_2.prefab"
GO_PID = 790132068239761591
GO_NAME = "Camera_InGame_VS_2"
MB_PID = -7120731629022708784
MB_SLOT = 13
MB_SCRIPT_ID = "72a6d5ac551842473380949ebaa14f20"
REQUIRED_FIELDS = ("m_fMaxDist", "m_fMinDist", "m_nearOrbit.m_PathID", "m_farOrbit.m_PathID")


class Divergence(Exception):
    pass


def load_table(data_dir):
    path = os.path.join(data_dir, TABLE + ".json")
    if not os.path.isfile(path):
        raise Divergence("missing table %s in %s" % (TABLE, data_dir))
    doc = json.load(open(path, encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("rows"), list):
        raise Divergence("%s is not a {\"rows\": [...]} document" % path)
    return doc


def classify(doc):
    """(row, state) for the single cameraSetIndex 401; fail-closed on a table revision this
    tool was never reviewed against."""
    rows = doc["rows"]
    if len(rows) != ROW_COUNT:
        raise Divergence("%s carries %d rows, expected %d" % (TABLE, len(rows), ROW_COUNT))
    hits = [r for r in rows if r.get("cameraSetIndex") == VS_INDEX]
    if not hits:
        raise Divergence("%s lacks cameraSetIndex %d" % (TABLE, VS_INDEX))
    if len(hits) > 1:
        raise Divergence("cameraSetIndex %d appears %d times" % (VS_INDEX, len(hits)))
    prefab = hits[0].get("cameraSetPrefab")
    if prefab == VS_PREFAB:
        return hits[0], "original"
    if prefab == VS2_PREFAB:
        return hits[0], "adapted"
    raise Divergence("cameraSet %d prefab %r is neither the original %r nor the adapted %r"
                     % (VS_INDEX, prefab, VS_PREFAB, VS2_PREFAB))


def bundle_manifest(cache):
    """{bundle name: content digest} from assetbundles.info's length-prefixed name/value
    pairs (values that are 32 hex chars are digests); a malformed manifest aborts instead
    of yielding a partial map."""
    with open(os.path.join(cache, "assetbundles.info"), "rb") as f:
        d = f.read()
    i, out = 0, {}
    while i + 4 <= len(d):
        n = struct.unpack_from("<i", d, i)[0]
        if not 0 <= n <= 4096 or i + 8 + n > len(d):
            raise Divergence("malformed assetbundles.info at offset %d" % i)
        name = d[i + 4:i + 4 + n].decode("utf-8", "replace")
        i += 4 + n
        n2 = struct.unpack_from("<i", d, i)[0]
        if not 0 <= n2 <= 4096 or i + 4 + n2 > len(d):
            raise Divergence("malformed assetbundles.info at offset %d" % i)
        val = d[i + 4:i + 4 + n2].decode("utf-8", "replace")
        i += 4 + n2
        if len(val) == 32:
            out[name] = val
    return out


def _decode_row(tb, pid, what):
    """Typed decode of one object against its own type tree, requiring a full body consume
    (a partial decode means the tree and the object disagree; nothing downstream is trustworthy)."""
    row = tb["rows"].get(pid)
    if row is None:
        raise Divergence("%s pid %d absent from bundle" % (what, pid))
    body = tb["stream"][row["offset"]:row["offset"] + row["size"]]
    records, consumed = read_unity_typed_fields.decode_object(body, tb["types"][row["typeSlot"]]["nodes"])
    if consumed != row["size"]:
        raise Divergence("%s pid %d decode consumed %d of %d bytes"
                         % (what, pid, consumed, row["size"]))
    return row, {r["path"]: r["value"] for r in records}


def _container_targets(vals):
    """{container asset path: pathID} from the AssetBundle object's m_Container map records;
    each entry's second is a preload struct whose asset PPtr carries the target pathID."""
    entries = {}
    for path, value in vals.items():
        if not path.startswith("m_Container.Array.data["):
            continue
        elem = path[:path.index("]") + 1]
        entries.setdefault(elem, {})[path[len(elem) + 1:]] = value
    return {e["first"]: e["second.asset.m_PathID"] for e in entries.values()
            if "first" in e and "second.asset.m_PathID" in e}


def verify_camera_asset(cache):
    """The adapted prefab must exist in the pinned prefabs_camera revision exactly as measured:
    container root -> Camera_InGame_VS_2 GameObject -> InGameCameraVS MonoBehaviour (slot,
    script id, orbit fields) -> back to the GameObject. Returns the report dict."""
    if not os.path.isdir(cache):
        raise Divergence("cache dir %s does not exist; --cache must point at the client cache"
                         % cache)
    manifest = bundle_manifest(cache)
    revision = manifest.get(CAMERA_BUNDLE)
    if revision is None:
        raise Divergence("bundle %r missing from assetbundles.info" % CAMERA_BUNDLE)
    if revision != BUNDLE_REVISION:
        raise Divergence("bundle %r revision %s != pinned %s; re-verify the asset before "
                         "re-pinning" % (CAMERA_BUNDLE, revision, BUNDLE_REVISION))
    path = os.path.join(cache, "assetbundles",
                        hashlib.md5(CAMERA_BUNDLE.encode()).hexdigest())
    if not os.path.isfile(path):
        raise Divergence("bundle file %r not cached" % path)
    digest = hashlib.md5(open(path, "rb").read()).hexdigest()
    if digest != BUNDLE_REVISION:
        raise Divergence("bundle file digest %s != manifest/pinned %s" % (digest, BUNDLE_REVISION))

    tb = read_unity_typed_fields.load_typed_bundle(path)
    container_pids = [p for p, r in tb["rows"].items()
                      if tb["types"][r["typeSlot"]]["classID"] == 142]
    if not container_pids:
        raise Divergence("bundle carries no AssetBundle container object")
    _, vals = _decode_row(tb, container_pids[0], "AssetBundle container")
    targets = _container_targets(vals)
    if targets.get(CONTAINER_KEY) != GO_PID:
        raise Divergence("container entry %r -> %r, expected GameObject pid %d"
                         % (CONTAINER_KEY, targets.get(CONTAINER_KEY), GO_PID))

    go_row, go_vals = _decode_row(tb, GO_PID, "GameObject")
    if go_row["classID"] != 1:
        raise Divergence("GameObject pid %d is classID %d" % (GO_PID, go_row["classID"]))
    if go_vals.get("m_Name") != GO_NAME:
        raise Divergence("container root %d is %r, expected %r"
                         % (GO_PID, go_vals.get("m_Name"), GO_NAME))
    components = {v for p, v in go_vals.items()
                  if p.startswith("m_Component.Array.data[") and p.endswith(".m_PathID")}
    if MB_PID not in components:
        raise Divergence("InGameCameraVS component %d absent from %s (components %s)"
                         % (MB_PID, GO_NAME, sorted(components)))

    mb_row, mb_vals = _decode_row(tb, MB_PID, "MonoBehaviour")
    if mb_row["classID"] != 114:
        raise Divergence("MonoBehaviour pid %d is classID %d" % (MB_PID, mb_row["classID"]))
    if mb_row["typeSlot"] != MB_SLOT:
        raise Divergence("MonoBehaviour pid %d sits in type slot %d, expected the pinned slot %d"
                         % (MB_PID, mb_row["typeSlot"], MB_SLOT))
    slot = tb["types"][MB_SLOT]
    if slot["classID"] != 114 or slot["scriptID"] != MB_SCRIPT_ID:
        raise Divergence("type slot %d is classID %d scriptID %r, expected 114 %r"
                         % (MB_SLOT, slot["classID"], slot["scriptID"], MB_SCRIPT_ID))
    if mb_vals.get("m_GameObject.m_PathID") != GO_PID:
        raise Divergence("MonoBehaviour %d points at GameObject %r, expected %d"
                         % (MB_PID, mb_vals.get("m_GameObject.m_PathID"), GO_PID))
    missing = [f for f in REQUIRED_FIELDS if f not in mb_vals]
    if missing:
        raise Divergence("InGameCameraVS fields missing from slot %d: %s" % (MB_SLOT, missing))

    return {"bundle": CAMERA_BUNDLE, "revision": BUNDLE_REVISION, "file": path,
            "container": CONTAINER_KEY,
            "gameObject": {"pathID": GO_PID, "name": GO_NAME, "components": len(components)},
            "monobehaviour": {"pathID": MB_PID, "typeSlot": MB_SLOT, "scriptID": MB_SCRIPT_ID,
                              "fields": {f: mb_vals[f] for f in REQUIRED_FIELDS}}}


def serialize(doc):
    """The tables' on-disk form (import_dungeons.save_data's indent=1 as last written on
    Windows): CRLF line breaks, UTF-8, no trailing newline."""
    return json.dumps(doc, indent=1, ensure_ascii=False).replace("\n", "\r\n").encode("utf-8")


def guard_output(out_dir, forbidden):
    """The candidate exists to be reviewed and installed from outside; it must never land
    inside the repository, the data dir it was built from, or the cache."""
    for f in forbidden:
        try:
            inside = os.path.commonpath([out_dir, f]) == f
        except ValueError:
            continue
        if inside:
            raise Divergence("--output %s resolves inside forbidden path %s" % (out_dir, f))


def main():
    parser = argparse.ArgumentParser(description="CameraSet 401 VS -> VS_2 candidate builder "
                                                 "for the Prove duel camera (read-only unless "
                                                 "--output; see module docstring)")
    parser.add_argument("--data", default=DATA, help="tables data dir holding CameraSetTable.json "
                                                     "(default: project master)")
    parser.add_argument("--cache", default=CACHE, help="client cache root with assetbundles/ and "
                                                       "assetbundles.info (default: project cache)")
    parser.add_argument("--output", default=None, help="TEMP dir for the candidate table plus "
                                                       "report; default: check only, write nothing")
    args = parser.parse_args()
    data_dir = os.path.abspath(args.data)
    cache_dir = os.path.abspath(args.cache)
    try:
        doc = load_table(data_dir)
        row, state = classify(doc)
        asset = verify_camera_asset(cache_dir)
        candidate = copy.deepcopy(doc)
        for r in candidate["rows"]:
            if r.get("cameraSetIndex") == VS_INDEX:
                r["cameraSetPrefab"] = VS2_PREFAB
        report = {
            "table": TABLE,
            "rows": len(doc["rows"]),
            "cameraSetIndex": VS_INDEX,
            "state": state,
            "changes": [{"field": "cameraSetPrefab", "from": VS_PREFAB, "to": VS2_PREFAB}]
                      if state == "original" else [],
            "asset": asset,
        }
        if args.output:
            out_dir = os.path.abspath(args.output)
            guard_output(out_dir, [REPO_ROOT, data_dir, cache_dir])
            os.makedirs(out_dir, exist_ok=True)
            open(os.path.join(out_dir, TABLE + ".json"), "wb").write(serialize(candidate))
            open(os.path.join(out_dir, TABLE + "-report.json"), "wb").write(serialize(report))
        print(json.dumps(report))
        return 0
    except (Divergence, OSError, ValueError) as e:
        print("adapt_prove_pc_camera: aborting, nothing written: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
