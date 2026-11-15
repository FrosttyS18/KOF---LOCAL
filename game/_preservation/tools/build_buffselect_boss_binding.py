"""Deterministic stdlib builder: give the BuffSelect boss Intro spawn its Boss blackboard name.

Root-proven cause (native-analysis/buff-v1025-binding.md, turn 153): every BuffSelect stage
graph overrides the BossGradeMonster module's task-1000 spawn with an m_saveBlackboard
BBParameter that carries NO _name. ActionSpawnMonsterWrap.DataMigration (0x18132B1F0) natively
copies m_saveBlackboard._name into saveAs._name and rebinds by name -- an empty name CLEARS
saveAs, so the spawn never saves the boss into the "Boss" blackboard variable, which matches
node 1001 (COMPARE_ANI, inverted) passing on a null target and node 1002 (COMPARE_HP) failing
on it. The observed symptom is the boss spawning and dying fine while the stage never
completes; that this name restoration fixes completion is the working hypothesis -- the name
copy is native-proven, the "Boss" variable's runtime value has not been measured yet. The
module (prefabs_eventsystem_trigger_triggermodule_battle, PPtr (2, 1743311889433446508), the
graph MB's Unity object-reference index 13 -- _subTree._value in the JSON) ships the default
itself: m_saveBlackboard/saveAs both {"_name": "Boss"}.

This tool restores ONLY that name: in each stage root's graph JSON
(BuffSelect_01..50 in prefabs_eventsystem_trigger_event_buffselect_n), the single
ActionSpawnMonsterWrap task whose m_spawnList carries the Intro spawn gets
m_saveBlackboard.m_value._name = the module's default "Boss" (validated from the module bundle,
never hardcoded). $type stays first and every other JSON value, the wave tasks' intentionally
empty bindings, the COMPARE_HP valueFloat, nodes, connections and the MonoBehaviour's
object-reference array are byte-preserved. The patched bodies are appended 8-aligned to the
SerializedFile; only those rows' byteStart/byteSize and the header fileSize change -- every
other object keeps its exact bytes and original offsets (the old bodies stay as unaddressed
bytes, same approach as build_buffselect_ai_alias). The JSON must round-trip byte-identically
through the compact separators before patching, so the new text differs from the original by
exactly the inserted ,"_name":"Boss" -- a structured deep-diff asserting that single addition
runs on every stage, and the whole candidate is re-parsed canonically from a TEMP copy before
anything is written. The UnityFS re-emit is stored mode 0 exactly like the reviewed alias
builder; outputs (rebuilt bundle under its md5 filename + derived assetbundles.info +
report.json) go ONLY to --output, never the cache, which is opened read-only and hash-checked
against the manifest before and after the run.

usage: build_buffselect_boss_binding.py --cache DIR --output DIR [--stage 810101]
  --cache   the client's storage/cache directory (read-only)
  --output  TEMP output directory (must live outside the cache)
  --stage   patch only this questEventStageIndex (default: all 50, 810101..810150)
"""
import argparse
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import read_unity_serialized as U
import import_timeattack_dependencies as T
import build_buffselect_ai_alias as A

BUNDLE_NAME = "prefabs_eventsystem_trigger_event_buffselect_n"
MODULE_BUNDLE = "prefabs_eventsystem_trigger_triggermodule_battle"
MODULE_FID, MODULE_PID = 2, 1743311889433446508
STAGE_FIRST, STAGE_LAST = 810101, 810150
BB_ACTOR_TYPE = "NodeCanvas.Framework.BBParameter`1[[Actor, Assembly-CSharp, Version=1.2.0.0, Culture=neutral, PublicKeyToken=null]]"
DATA = os.path.normpath(os.path.join(HERE, "..", "server", "tables", "data"))


def fail(msg):
    sys.exit("build_buffselect_boss_binding: %s" % msg)


def dumps(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def deep_diff(a, b, path="$", out=None):
    """Every difference between two JSON trees as (path, kind, old, new); ordered by walk."""
    if out is None:
        out = []
    if type(a) is not type(b):
        out.append((path, "type", a, b))
    elif isinstance(a, dict):
        for k in a:
            if k not in b:
                out.append((path + "." + k, "removed", a[k], None))
            else:
                deep_diff(a[k], b[k], path + "." + k, out)
        for k in b:
            if k not in a:
                out.append((path + "." + k, "added", None, b[k]))
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append((path, "len", len(a), len(b)))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                deep_diff(x, y, "%s[%d]" % (path, i), out)
    elif a != b:
        out.append((path, "value", a, b))
    return out


def module_default_boss_name(cache, manifest):
    """(boss name, module bundle path, module node CAB) -- the default the module itself ships."""
    src = os.path.join(cache, "assetbundles", hashlib.md5(MODULE_BUNDLE.encode()).hexdigest())
    if not os.path.isfile(src):
        fail("no cached bundle for %s" % MODULE_BUNDLE)
    raw = open(src, "rb").read()
    md5 = hashlib.md5(raw).hexdigest()
    hit = [v for n, v in manifest if n == MODULE_BUNDLE]
    if not hit or hit[0] != md5:
        fail("%s: assetbundles.info hash does not match the cached file" % MODULE_BUNDLE)
    _, _, mbs, _, _ = U.index_bundle(src)
    if MODULE_PID not in mbs or U.GRAPH_MARKER not in mbs[MODULE_PID]["payload"]:
        fail("module graph pathID %d not found in %s" % (MODULE_PID, MODULE_BUNDLE))
    graph = T._graph_json(mbs[MODULE_PID]["payload"])
    names = set()

    def walk(node):
        if isinstance(node, dict):
            sb, sa = node.get("m_saveBlackboard"), node.get("saveAs")
            if isinstance(sb, dict) and isinstance(sa, dict):
                n1, n2 = sb.get("_name"), sa.get("_name")
                if isinstance(n1, str) and n1 and n1 == n2:
                    names.add(n1)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(graph)
    if names != {"Boss"}:
        fail("module default blackboard names %s, expected exactly {'Boss'}" % sorted(names))
    node_name = A.bundle_layout(src)["nodes"][0][3]
    return names.pop(), src, node_name


def check_module_external(info, module_node_name):
    """The graph MB's module PPtr must point through THIS bundle's external table at the module
    bundle's node, not merely carry fileID 2 with the expected pathID."""
    externals = info.get("externals") or []
    if MODULE_FID > len(externals):
        fail("external fileID %d exceeds the bundle's %d externals" % (MODULE_FID, len(externals)))
    target = externals[MODULE_FID - 1]
    if module_node_name not in target:
        fail("external %d is %r, which does not reference the module node %s"
             % (MODULE_FID, target, module_node_name))


def stage_graphs(cache, manifest, stages):
    """[(stageIndex, base, mbPid, graph dict)] for the requested stages, with root-uniqueness guards."""
    src = os.path.join(cache, "assetbundles", hashlib.md5(BUNDLE_NAME.encode()).hexdigest())
    if not os.path.isfile(src):
        fail("no cached bundle for %s" % BUNDLE_NAME)
    raw = open(src, "rb").read()
    input_md5 = hashlib.md5(raw).hexdigest()
    input_sha = hashlib.sha256(raw).hexdigest()
    hit = [v for n, v in manifest if n == BUNDLE_NAME]
    if not hit or hit[0] != input_md5:
        fail("assetbundles.info hash does not match the cached bundle file")
    _, gos, mbs, trs, _ = U.index_bundle(src)
    out = []
    for stage in stages:
        row = next((r for r in stages_table() if r.get("questEventStageIndex") == stage), None)
        if row is None or not str(row.get("singleTriggerName", "")).rsplit("/", 1)[1]:
            fail("stage %d has no singleTriggerName" % stage)
        base = row["singleTriggerName"].rsplit("/", 1)[1]
        roots = [p for p, g in gos.items() if g["name"] == base]
        if len(roots) != 1:
            fail("stage %d: %d root GameObjects named %s" % (stage, len(roots), base))
        sub = U.subtree_gameobjects(gos, trs, roots[0])
        cand = [(p, m) for p, m in mbs.items() if m["go_pid"] in sub and U.GRAPH_MARKER in m["payload"]]
        if len(cand) != 1:
            fail("stage %d: %d graph MonoBehaviours under root %s" % (stage, len(cand), base))
        p, m = cand[0]
        out.append({"stage": stage, "base": base, "pid": p, "graph": T._graph_json(m["payload"])})
    return src, raw, input_md5, input_sha, out


_STAGES_TABLE = None


def stages_table():
    global _STAGES_TABLE
    if _STAGES_TABLE is None:
        path = os.path.join(DATA, "QuestEventStageTable.json")
        _STAGES_TABLE = json.load(open(path, encoding="utf-8"))["rows"]
    return _STAGES_TABLE


def locate_intro_task(graph):
    """(nodeIndex, taskKey, field entry) of the single Intro-spawning ActionSpawnMonsterWrap."""
    hits = []
    for ni, node in enumerate(graph.get("nodes", [])):
        for task, fields in (node.get("m_taskVariables") or {}).items():
            if not task.startswith("ActionSpawnMonsterWrap("):
                continue
            values = {f.get("m_variableName"): f for f in fields}
            spawns = ((values.get("m_spawnList") or {}).get("m_value") or {}).get("$content", [])
            if any(s.get("m_spawnType") == "Intro" for s in spawns):
                hits.append((ni, task, values.get("m_saveBlackboard")))
    if len(hits) != 1:
        fail("expected exactly one Intro ActionSpawnMonsterWrap per stage, found %d" % len(hits))
    ni, task, field = hits[0]
    if field is None:
        fail("Intro task %s carries no m_saveBlackboard field at all" % task)
    return ni, task, field


def build_body(body, boss, stage):
    """Patch one MonoBehaviour body: new body bytes, the original graph object, the new one."""
    go_len = struct.unpack_from("<i", body, 28)[0]
    if not 0 <= go_len <= 64:
        fail("stage %d: implausible MonoBehaviour name length" % stage)
    payload_off = 28 + 4 + go_len + ((4 - go_len % 4) % 4)
    payload = body[payload_off:]
    js = payload.find(b"{")
    if js < 4:
        fail("stage %d: no JSON blob in the graph payload" % stage)
    jlen = struct.unpack_from("<I", payload, js - 4)[0]
    end = js + jlen
    if end > len(payload):
        fail("stage %d: JSON blob length overruns the payload" % stage)
    orig_text = payload[js:end]
    orig = json.loads(orig_text)
    if dumps(orig) != orig_text:
        fail("stage %d: graph JSON does not round-trip through the compact serializer" % stage)
    ni, task, field = locate_intro_task(orig)
    value = field["m_value"]
    if field.get("m_type") != BB_ACTOR_TYPE or value.get("$type") != BB_ACTOR_TYPE:
        fail("stage %d: m_saveBlackboard is not a BBParameter<Actor>" % stage)
    if "_name" in value:
        if value["_name"] == boss:
            fail("stage %d: already adapted (m_saveBlackboard._name == %r); refusing to rewrite"
                 % (stage, boss))
        fail("stage %d: m_saveBlackboard carries unexpected _name %r -- refusing to guess"
             % (stage, value["_name"]))
    refs_base = (end + 3) // 4 * 4
    count = struct.unpack_from("<i", payload, refs_base)[0]
    if not 0 < count <= 4096:
        fail("stage %d: implausible object-reference count %d" % (stage, count))
    refs_end = refs_base + 4 + 12 * count
    if refs_end > len(payload):
        fail("stage %d: object-reference array overruns the payload" % stage)
    refs_blob = payload[refs_base:refs_end]
    post = payload[refs_end:]
    sub = orig["nodes"][ni].get("_subTree") or {}
    idx = sub.get("_value")
    if not isinstance(idx, int) or not 0 <= idx < count:
        fail("stage %d: _subTree._value %r is not a reference index" % (stage, idx))
    fid, pid = struct.unpack_from("<Iq", refs_blob, 4 + 12 * idx)
    if (fid, pid) != (MODULE_FID, MODULE_PID):
        fail("stage %d: reference %d is (%d, %d), not the BossGradeMonster module"
             % (stage, idx, fid, pid))

    patched = json.loads(orig_text)
    pfield = None
    for f in patched["nodes"][ni]["m_taskVariables"][task]:
        if f.get("m_variableName") == "m_saveBlackboard":
            pfield = f
    pfield["m_value"]["_name"] = boss
    new_json = dumps(patched)
    diff = deep_diff(orig, patched)
    if len(diff) != 1 or diff[0][1] != "added" or not diff[0][0].endswith("].m_value._name") \
            or diff[0][3] != boss:
        fail("stage %d: structured diff is not exactly the one added _name: %r" % (stage, diff))
    new_end = payload_off + js + len(new_json)
    pad = (4 - new_end % 4) % 4
    new_body = body[:payload_off] + payload[:js - 4] + struct.pack("<I", len(new_json)) \
        + new_json + b"\0" * pad + refs_blob + post
    return new_body, orig, patched, task


def main():
    ap = argparse.ArgumentParser(description="restore the BuffSelect boss Intro blackboard name "
                                             "(outputs to TEMP only; never touches the cache)")
    ap.add_argument("--cache", required=True, help="the client's storage/cache directory (read-only)")
    ap.add_argument("--output", required=True, help="TEMP output directory for the rebuilt files")
    ap.add_argument("--stage", type=int, help="patch only this questEventStageIndex (default: all 50)")
    args = ap.parse_args()
    cache = os.path.abspath(args.cache)
    out_dir = os.path.abspath(args.output)
    if os.path.commonpath([cache, out_dir]) == cache:
        fail("output directory must not live inside the cache")
    stages = [args.stage] if args.stage is not None else list(range(STAGE_FIRST, STAGE_LAST + 1))
    if any(s < STAGE_FIRST or s > STAGE_LAST for s in stages):
        fail("--stage must be one of %d..%d" % (STAGE_FIRST, STAGE_LAST))

    index = open(os.path.join(cache, "assetbundles.info"), "rb").read()
    manifest = A.parse_index(index)
    boss, module_src, module_node = module_default_boss_name(cache, manifest)
    src, raw, input_md5, input_sha, targets = stage_graphs(cache, manifest, stages)

    lay = A.bundle_layout(src)
    info = lay["info"]
    if info["fileVersion"] != 22:
        fail("fileVersion %r, expected 22" % info["fileVersion"])
    if len(lay["nodes"]) != 1 or lay["nodes"][0][0] != 0:
        fail("unsupported bundle shape: nodes %r" % (lay["nodes"],))
    n_off, n_size, n_flags, n_name = lay["nodes"][0]
    if n_name.endswith((".resS", ".resource")) or lay["flags"] & 128:
        fail("unsupported bundle shape (resource node or blocks-info-at-end)")
    if sum(1 for r in lay["rows"].values() if r[5] == 142) != 1:
        fail("expected exactly one AssetBundle object")
    check_module_external(info, module_node)
    data_offset = info["dataOffset"]

    stream = bytearray(lay["stream"])
    patches = []
    for t in targets:
        row = lay["rows"].get(t["pid"])
        if row is None or row[5] != 114:
            fail("stage %d: graph object %d is not a MonoBehaviour" % (t["stage"], t["pid"]))
        body = bytes(stream[data_offset + row[1]:data_offset + row[1] + row[3]])
        new_body, orig, patched, task = build_body(body, boss, t["stage"])
        pad8 = (8 - len(stream) % 8) % 8
        append_at = len(stream) + pad8
        stream += b"\0" * pad8 + new_body
        struct.pack_into("<q", stream, row[0], append_at - data_offset)
        struct.pack_into("<I", stream, row[2], len(new_body))
        patches.append({"stage": t["stage"], "base": t["base"], "pid": t["pid"], "task": task,
                        "old": (row[1], row[3]), "new": (append_at - data_offset, len(new_body)),
                        "orig": orig, "patched": patched, "new_body": new_body})
    struct.pack_into(">q", stream, 24, len(stream))
    stream = bytes(stream)

    blocks = [stream[i:i + A.BLOCK_SIZE] for i in range(0, len(stream), A.BLOCK_SIZE)]
    new_bi = bytearray(16) + struct.pack(">I", len(blocks))
    for b in blocks:
        new_bi += struct.pack(">IIH", len(b), len(b), 0)
    new_bi += struct.pack(">i", 1) + struct.pack(">qqI", 0, len(stream), n_flags) \
        + n_name.encode() + b"\0"
    new_flags = (lay["flags"] & ~0x3F) | 0
    u1 = raw.index(b"\0", 12)
    u2 = raw.index(b"\0", u1 + 1)
    out = bytearray(raw[:12]) + raw[12:u2 + 1]
    size_at = len(out)
    out += struct.pack(">QIII", 0, len(new_bi), len(new_bi), new_flags)
    while len(out) % 16:
        out += b"\0"
    out += new_bi
    if new_flags & 0x200:
        while len(out) % 16:
            out += b"\0"
    for b in blocks:
        out += b
    struct.pack_into(">Q", out, size_at, len(out))
    out_md5 = hashlib.md5(out).hexdigest()

    import tempfile
    probe_fd, probe = tempfile.mkstemp(prefix="buffselect_binding_verify_")
    os.write(probe_fd, out)
    os.close(probe_fd)
    try:
        back = A.bundle_layout(probe)
        by_pid = {p["pid"]: p for p in patches}
        for pid, r in lay["rows"].items():
            br = back["rows"][pid]
            if pid in by_pid:
                if br[1] != by_pid[pid]["new"][0] or br[3] != by_pid[pid]["new"][1] \
                        or br[4] != r[4] or br[5] != r[5]:
                    fail("verification: patched row %d diverges" % pid)
                body = back["stream"][back["info"]["dataOffset"] + br[1]:
                                     back["info"]["dataOffset"] + br[1] + br[3]]
                if body != by_pid[pid]["new_body"]:
                    fail("verification: patched body %d diverges" % pid)
            else:
                if br[1] != r[1] or br[3] != r[3] or br[4] != r[4] or br[5] != r[5]:
                    fail("verification: untouched row %d moved" % pid)
                if back["stream"][back["info"]["dataOffset"] + br[1]:
                        back["info"]["dataOffset"] + br[1] + br[3]] \
                        != lay["stream"][data_offset + r[1]:data_offset + r[1] + r[3]]:
                    fail("verification: untouched body %d changed" % pid)
        _, gos2, mbs2, trs2, _ = U.index_bundle(probe)
        for p in patches:
            m = mbs2[p["pid"]]
            g2 = T._graph_json(m["payload"])
            _ni, _task, field = locate_intro_task(g2)
            if field["m_value"].get("_name") != boss:
                fail("verification: stage %d reparse lacks the Boss name" % p["stage"])
            for node in g2["nodes"]:
                for task, fields in (node.get("m_taskVariables") or {}).items():
                    if not task.startswith("ActionSpawnMonsterWrap("):
                        continue
                    values = {f.get("m_variableName"): f for f in fields}
                    spawns = ((values.get("m_spawnList") or {}).get("m_value") or {}).get("$content", [])
                    if any(s.get("m_spawnType") == "Intro" for s in spawns):
                        continue
                    sb = (values.get("m_saveBlackboard") or {}).get("m_value") or {}
                    if sb.get("_name"):
                        fail("verification: wave task %s gained a binding name" % task)
    finally:
        os.remove(probe)
    if hashlib.md5(open(src, "rb").read()).hexdigest() != input_md5:
        fail("input file changed during the run; outputs are invalid")

    value_at = index.index(input_md5.encode(), index.index(BUNDLE_NAME.encode()))
    new_index = bytearray(index)
    new_index[value_at:value_at + 32] = out_md5.encode()
    if [(n, v) for n, v in A.parse_index(bytes(new_index)) if n != BUNDLE_NAME] \
            != [(n, v) for n, v in manifest if n != BUNDLE_NAME]:
        fail("assetbundles.info verification failed")
    os.makedirs(out_dir, exist_ok=True)
    report = {"bundle": BUNDLE_NAME, "boss_name": boss, "module": {"bundle": MODULE_BUNDLE,
              "file_id": MODULE_FID, "path_id": MODULE_PID},
              "patched": [{k: p[k] for k in ("stage", "base", "pid", "task", "old", "new")}
                          for p in patches],
              "input": {"md5": input_md5, "sha256": input_sha, "size": len(raw)},
              "output": {"md5": out_md5, "size": len(out), "blocks": len(blocks), "mode": 0},
              "index_hash_swapped": {"from": input_md5, "to": out_md5}}
    open(os.path.join(out_dir, hashlib.md5(BUNDLE_NAME.encode()).hexdigest()), "wb").write(out)
    open(os.path.join(out_dir, "assetbundles.info"), "wb").write(new_index)
    json.dump(report, open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)
    print("verified: %d stage graphs patched (m_saveBlackboard._name -> %r), "
          "%d other objects byte-identical" % (len(patches), boss, len(lay["rows"]) - len(patches)))
    print("bundle %d -> %d bytes, %d stored blocks | index hash %s -> %s"
          % (len(raw), len(out), len(blocks), input_md5, out_md5))
    print("outputs: %s" % out_dir)


if __name__ == "__main__":
    main()
