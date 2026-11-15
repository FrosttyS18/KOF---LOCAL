"""Import the monster closure of the nine Time Attack challenges (ChallengeStageTable).

Derivation is pointer-exact, never by proximity: each challengeStage row's EFFECTIVE trigger
path names a prefab in the prefabs_eventsystem_trigger_timeattack bundle -- `flowTrigger` on
pre-adapt rows, `triggerName` after tools/adapt_timeattack_pc.py moved it there (the PC
adaptation for the LoadingProcess callback path); both modes yield the same nine standalone
roots. The root GameObject (m_Name == path basename) is walked through
component->Transform->children PPtrs only, and the NodeCanvas.BehaviourTree MonoBehaviour
linked to that subtree supplies the Monster.* tokens those graphs spawn
(tools/read_unity_serialized.py parses the bundle canonically). Every challenge's tokens must
resolve in the project tables or the mobile source, or the run aborts.

The closure then follows tools/import_dungeon_monsters.py semantics, reusing its helpers without
editing them: PC rows win when both sides carry the monsterIndexString (divergences logged,
never overwritten); skills come from each profile's skillNIndex slots PLUS the chained Skill.*
names the consumed rows' own prefab bundles carry (tools/read_unityfs.py decompresses each
monster's bundle; every real #N version of a resolved name, in the project tables or the mobile
source, joins the closure -- Skill.* names that resolve to no row anywhere are reported as
orphans, never fabricated); MonsterGrowthTable needs the whole growthType set;
MonsterLevelStatTable needs (levelStatType, level) for every challenge's monsterLevel;
AiGroupTable needs (aiGroup, the challenge's aiGrade). Name tags get their real mobile texts via
strings_add; tags with no text anywhere stay absent and are reported.

The prefab bundle of EVERY required monster -- mobile rows and rows already in the project
tables alike, since a missing file breaks the nine challenges just the same -- must be in the
client's assetbundles.info and cache, or the run aborts listing them all before any write.
Bundle GameObjects that look like TimeAttack assets but have no flowTrigger in the table
(TimeAttack_Mukai, TimeAttack_WWE -- past events) are reported only and demand nothing.

The zone changes close too: the graphs' ActionChangeScene nodes switch areas by STRING --
native ActionChangeScene$$OnExecute 0x1812BAB60 runs ResourceMapTable.Find(m_mapIndexString)
and a null row skips the whole scene-load block (the v1023 black screen; live-measured
'Comedown_Japan_Festival_A_N_TimeAttack' -> null -> Failure). close_trigger_maps(src,
data_dir) reads the real graph JSON inside the graphs pointer-linked to each of the nine
roots, never a generic m_mapIndexString scan, resolves every name against the project tables
first and the mobile source otherwise, preflights each target's scene bundle
(bg_<resourceMapScene>) in the client manifest AND as a physical file in the PC cache -- for
every target, already-present ones included -- and appends the missing ResourceMap rows
(triggerPositionX verbatim). The graph JSON is decoded as a whole bounded blob (u32 length
prefix before the first '{', strict utf-8) whose every top-level node is typed exactly
NodeCanvas.BehaviourTrees.*, then walked recursively for $type ActionChangeScene, so nested
or malformed objects can never disappear silently. import_dungeons.main can call
close_trigger_maps directly; the CLI runs the same preflight before any monster write.

Append-only, preflight-then-write: missing source table, unresolvable reference, conflicting
duplicate key or planned-row collision abort before any write, leaving the data dir untouched.
Idempotent by construction.

usage: import_timeattack_dependencies.py <kofas_server folder> [--data DIR]
"""
import argparse
import hashlib
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import import_dungeon_monsters as guards  # as_int/keyed/dup_guard/same_row/skill_indexes, no edits
import read_unity_serialized  # canonical SerializedFile v22 + pointer graph walk
import read_unityfs  # raw decompression for the chained Skill.* scan of monster prefab bundles


SKILL_TOKEN = re.compile(rb"Skill\.[A-Za-z0-9_.]+(?:#[0-9]+)?")


CACHE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "game", "storage", "cache"))
dg = guards.base  # import_dungeons: fields_of/load_data/merge/mobile_rows/mobile_texts


def fail(msg):
    sys.exit(f"import_timeattack_dependencies: {msg}")


def bundle_manifest():
    d = open(os.path.join(CACHE, "assetbundles.info"), "rb").read()
    i, names = 0, set()
    while i + 4 <= len(d):
        n = struct.unpack_from("<i", d, i)[0]
        name = d[i + 4:i + 4 + n].decode()
        i += 4 + n
        n2 = struct.unpack_from("<i", d, i)[0]
        val = d[i + 4:i + 4 + n2].decode()
        i += 4 + n2
        if len(val) == 32:
            names.add(name)
    return names


def bundle_file(name):
    return os.path.join(CACHE, "assetbundles", hashlib.md5(name.encode()).hexdigest())


def bundle_of_prefab(path):
    parts = path.split("/")
    return "_".join(parts[:-1]).lower() if len(parts) > 1 else None


BT_NAMESPACE = "NodeCanvas.BehaviourTrees."


def _graph_json(payload):
    """Bounded decode of the serialized graph. The graph blob is a little-endian u32 length
    prefix immediately before its '{' (verified on all nine live graphs -- one candidate per
    payload, e.g. 55353 bytes at offset 8). The strict-utf-8 JSON root is the serialized
    GraphSource (canvasGroups/connections/derivedData/localBlackboard/nodes/primeNode) with
    no $type of its own; the graph's BehaviourTree typing is asserted exactly here instead:
    EVERY top-level node must carry a $type of the real namespace NodeCanvas.BehaviourTrees.*
    (checked on all nine originals). An object that has "nodes" but fails that exact typing
    aborts loudly -- the walker never moves on to another candidate to work around it -- and
    so does a payload with no valid candidate at all: an action can never disappear
    silently."""
    start = payload.find(b"{")
    while start >= 4:
        size = struct.unpack_from("<I", payload, start - 4)[0]
        if 0 < size and start + size <= len(payload):
            try:
                graph = json.loads(payload[start:start + size].decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                graph = None
            if isinstance(graph, dict) and "nodes" in graph:
                nodes = graph.get("nodes")
                if (not isinstance(nodes, list) or not nodes
                        or not all(isinstance(n, dict) and isinstance(n.get("$type"), str)
                                   and n["$type"].startswith(BT_NAMESPACE) for n in nodes)):
                    fail("graph root is not a NodeCanvas.BehaviourTrees graph (nodes mistyped)")
                return graph
        start = payload.find(b"{", start + 1)
    fail("graph payload carries no length-prefixed BehaviourTree JSON (malformed or truncated)")


def _walk_action_change_scenes(node, out):
    """Every object whose $type is exactly ActionChangeScene (namespace-prefixed form
    allowed), recursing the whole decoded graph -- nested actions cannot disappear."""
    if isinstance(node, dict):
        value = node.get("$type")
        if isinstance(value, str) and value.split(".")[-1] == "ActionChangeScene":
            out.append(node)
        for v in node.values():
            _walk_action_change_scenes(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_action_change_scenes(v, out)


def effective_triggers(data_dir):
    """[(stageIndex, effective trigger path, monsterLevel, aiGrade)] from the project's
    ChallengeStageTable -- flowTrigger on pre-adapt rows, triggerName after the PC move."""
    dg.DATA = data_dir
    schema = json.load(open(dg.SCHEMA, encoding="utf-8"))
    stages = dg.load_data("ChallengeStageTable")["rows"]
    guards.dup_guard(stages, lambda r: r.get("challengeStageIndex"),
                     dg.fields_of(schema, "ChallengeStageTable"), "ChallengeStageTable (project)")
    flow = []
    for r in stages:
        path = r.get("flowTrigger") or r.get("triggerName") or ""
        if not path:
            fail(f"ChallengeStageTable: stage {r.get('challengeStageIndex')} carries neither "
                 f"flowTrigger nor triggerName")
        flow.append((guards.as_int(r.get("challengeStageIndex"), "challengeStageIndex"), path,
                     guards.as_int(r.get("monsterLevel"), "monsterLevel"),
                     guards.as_int(r.get("aiGrade"), "aiGrade")))
    if not flow:
        fail("ChallengeStageTable: no rows")
    bare = [idx for idx, path, _, _ in flow if "/" not in path]
    if bare:
        fail(f"trigger path without a bundle directory in stages {bare}")
    return flow


def _trigger_map_targets(flow, manifest):
    """Every ActionChangeScene m_mapIndexString in the graphs pointer-linked to the nine
    roots: the full serialized graph JSON is decoded bounded (length-prefixed blob, strict
    utf-8) and walked recursively, so nested or malformed actions can never disappear
    silently -- any deviation aborts. No token scan, no m_mapIndexString from other types."""
    bundles = {}
    targets, per_root = set(), {}
    for idx, path, _, _ in flow:
        b = bundle_of_prefab(path)
        if b not in bundles:
            if b not in manifest or not os.path.isfile(bundle_file(b)):
                fail(f"bundle {b} (from the trigger path) is not in the client manifest/cache")
            _, gos, mbs, trs, _ = read_unity_serialized.index_bundle(bundle_file(b))
            bundles[b] = (gos, mbs, trs)
        gos, mbs, trs = bundles[b]
        base = path.split("/")[-1]
        roots = [p for p, g in gos.items() if g["name"] == base]
        if not roots:
            fail(f"stage {idx}: root GameObject {base!r} not found in bundle {b}")
        names = set()
        for rp in roots:
            sub = read_unity_serialized.subtree_gameobjects(gos, trs, rp)
            for pid, m in mbs.items():
                if m["go_pid"] not in sub or read_unity_serialized.GRAPH_MARKER not in m["payload"]:
                    continue
                actions = []
                _walk_action_change_scenes(_graph_json(m["payload"]), actions)
                for node in actions:
                    name = node.get("m_mapIndexString")
                    if not isinstance(name, str) or not name:
                        fail(f"stage {idx}: ActionChangeScene without m_mapIndexString -- refusing")
                    names.add(name)
        per_root[idx] = sorted(names)
        targets |= names
    return targets, per_root


def _plan_trigger_maps(src, data_dir, manifest=None):
    """Preflight-only zone-map closure: names, rows to add, collisions and scene bundles --
    no write happens until _apply_trigger_maps."""
    dg.DATA = data_dir
    schema = json.load(open(dg.SCHEMA, encoding="utf-8"))
    if "ResourceMapTable" not in schema["tables"]:
        fail("ResourceMapTable: not in schema.json")
    if not os.path.isfile(os.path.join(src, "tabel", "ResourceMapTable.json")):
        fail("mobile source lacks tabel/ResourceMapTable.json")
    flow = effective_triggers(data_dir)
    manifest = manifest if manifest is not None else bundle_manifest()
    targets, per_root = _trigger_map_targets(flow, manifest)
    rm_fields = dg.fields_of(schema, "ResourceMapTable")
    mst_rows = dg.load_data("ResourceMapTable")["rows"]
    mob_rows = dg.mobile_rows(src, "ResourceMapTable")
    mst = guards.dup_guard([r for r in mst_rows if r.get("resourceMapIndexString") in targets],
                           lambda r: r.get("resourceMapIndexString"), rm_fields,
                           "ResourceMapTable (project)")
    need = sorted(targets - set(mst))
    mob = guards.dup_guard([r for r in mob_rows if r.get("resourceMapIndexString") in set(need)],
                           lambda r: r.get("resourceMapIndexString"), rm_fields,
                           "ResourceMapTable (mobile)")
    mst_ids = {guards.as_int(r.get("resourceMapIndex"), "resourceMapIndex") for r in mst_rows}
    all_by_str = dict(mst)
    all_by_str.update(mob)
    for t in sorted(targets):
        row = all_by_str.get(t)
        if row is None:
            fail(f"ResourceMapTable: zone map {t} in neither the project tables nor the mobile source")
        scene = row.get("resourceMapScene") or ""
        bg = "bg_" + scene.lower()
        if not scene or bg not in manifest or not os.path.isfile(bundle_file(bg)):
            fail(f"ResourceMapTable {t}: scene bundle {bg!r} missing from the client manifest/cache "
                 f"-- refusing (never announce an asset without its file)")
    adds = []
    for t in need:
        row = mob[t]
        rid = guards.as_int(row.get("resourceMapIndex"), "resourceMapIndex")
        if rid in mst_ids:
            fail(f"ResourceMapTable: resourceMapIndex {rid} ({t}) collides with an existing project row")
        adds.append(row)
    return {"adds": adds, "targets": sorted(targets), "per_root": per_root}


def _apply_trigger_maps(src, data_dir, plan):
    dg.DATA = data_dir
    schema = json.load(open(dg.SCHEMA, encoding="utf-8"))
    return len(dg.merge(schema, "ResourceMapTable", plan["adds"], "resourceMapIndex", src, []))


def close_trigger_maps(src, data_dir):
    """Zone-map closure reusable from import_dungeons.main: preflights everything (real
    graph JSON, source rows, collisions, scene bundles) and only then appends the missing
    ResourceMapTable rows. -> {"added": n, "count": len(targets), "names": [...]}"""
    plan = _plan_trigger_maps(src, data_dir)
    return {"added": _apply_trigger_maps(src, data_dir, plan),
            "count": len(plan["targets"]), "names": plan["targets"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("src", help="kofas_server folder (with tabel/ and tabel_teks/)")
    parser.add_argument("--data", default=os.path.normpath(os.path.join(HERE, "..", "server",
                                                                        "tables", "data")),
                        help="tables data dir to update (default: the project's)")
    args = parser.parse_args()
    src, data = args.src, args.data
    if not os.path.isdir(os.path.join(src, "tabel")):
        fail(f"{src} has no tabel/ -- usage: import_timeattack_dependencies.py <kofas_server folder> [--data DIR]")
    if not os.path.isfile(os.path.join(data, "ChallengeStageTable.json")):
        fail(f"{data} carries no ChallengeStageTable.json")
    schema = json.load(open(dg.SCHEMA, encoding="utf-8"))
    dg.DATA = data

    for table in ("ChallengeStageTable", "MonsterTable", "MonsterSkillTable", "MonsterGrowthTable",
                  "MonsterLevelStatTable", "AiGroupTable"):
        if table not in schema["tables"]:
            fail(f"{table}: not in schema.json")
        if table != "ChallengeStageTable" and not os.path.isfile(os.path.join(src, "tabel", table + ".json")):
            fail(f"mobile source lacks tabel/{table}.json")
    fields = {t: dg.fields_of(schema, t) for t in ("MonsterTable", "MonsterSkillTable",
                                                   "MonsterGrowthTable", "MonsterLevelStatTable",
                                                   "AiGroupTable")}

    stages = dg.load_data("ChallengeStageTable")["rows"]
    guards.dup_guard(stages, lambda r: r.get("challengeStageIndex"),
                     dg.fields_of(schema, "ChallengeStageTable"), "ChallengeStageTable (project)")
    flow = effective_triggers(data)

    manifest = bundle_manifest()
    bundle_names = sorted({bundle_of_prefab(ft) for _, ft, _, _ in flow})
    for b in bundle_names:
        if b not in manifest or not os.path.isfile(bundle_file(b)):
            fail(f"bundle {b} (from the trigger path) is not in the client manifest/cache")
    maps_plan = _plan_trigger_maps(src, data, manifest)

    monsters_of_stage, orphans, indexed = {}, [], {}
    for b in bundle_names:
        data_stream, gos, mbs, trs, info = read_unity_serialized.index_bundle(bundle_file(b))
        indexed[b] = info
        for idx, ft, _, _ in flow:
            if bundle_of_prefab(ft) != b:
                continue
            base = ft.split("/")[-1]
            roots = [p for p, g in gos.items() if g["name"] == base]
            if not roots:
                fail(f"stage {idx}: root GameObject {base!r} not found in bundle {b}")
            go_pids = set()
            for rp in roots:
                go_pids |= read_unity_serialized.subtree_gameobjects(gos, trs, rp)
            holders, mons = read_unity_serialized.graph_monsters(mbs, go_pids)
            if not holders:
                fail(f"stage {idx}: no NodeCanvas.BehaviourTree linked under {base!r}")
            if not mons:
                fail(f"stage {idx}: graph under {base!r} carries no Monster.* token")
            monsters_of_stage[idx] = (base, len(go_pids), len(holders), sorted(mons))
        wanted = {ft.split("/")[-1] for _, ft, _, _ in flow if bundle_of_prefab(ft) == b}
        for p, g in gos.items():
            name = g["name"]
            if name.startswith("TimeAttack") and name not in wanted:
                sub = read_unity_serialized.subtree_gameobjects(gos, trs, p)
                _, mons = read_unity_serialized.graph_monsters(mbs, sub)
                if mons:
                    orphans.append({"bundle": b, "root": name, "monsters": sorted(mons)})

    mon_strings = sorted({m for _, _, _, mons in monsters_of_stage.values() for m in mons})
    mob_rows = dg.mobile_rows(src, "MonsterTable")
    guards.dup_guard([r for r in mob_rows if r.get("monsterIndexString") in set(mon_strings)],
                     lambda r: r.get("monsterIndexString"), fields["MonsterTable"],
                     "MonsterTable (mobile)")
    mob = {r.get("monsterIndexString"): r for r in mob_rows if r.get("monsterIndexString") in set(mon_strings)}
    pc_rows = dg.load_data("MonsterTable")["rows"]
    pc = guards.dup_guard([r for r in pc_rows if r.get("monsterIndexString") in set(mon_strings)],
                          lambda r: r.get("monsterIndexString"), fields["MonsterTable"],
                          "MonsterTable (project)")
    gap = [m for m in mon_strings if m not in pc and m not in mob]
    if gap:
        fail(f"MonsterTable: challenge monsters in neither the project tables nor the mobile "
             f"source: {gap[:10]} (total {len(gap)})")

    row_of, divergent = {}, []
    for m in mon_strings:
        if m in pc and m in mob and not guards.same_row(pc[m], mob[m], fields["MonsterTable"]):
            divergent.append(f"MonsterTable {m}")
        row_of[m] = pc.get(m) or mob[m]

    missing_bundles = []
    for m in mon_strings:
        b = bundle_of_prefab(row_of[m].get("monsterPrefab", ""))
        if not b or b not in manifest or not os.path.isfile(bundle_file(b)):
            missing_bundles.append({"monsterIndexString": m, "prefab": row_of[m].get("monsterPrefab"),
                                    "bundle": b, "alreadyInProjectTables": m in pc})
    if missing_bundles:
        fail(f"monster prefab bundles missing from the client manifest/cache -- a challenge monster "
             f"without its file breaks the nine challenges just the same: {missing_bundles}")
    mon_add = [mob[m] for m in mon_strings if m in row_of and m not in pc]

    skill_blobs = {}
    bundle_tokens = set()
    for r in row_of.values():
        b = bundle_of_prefab(r.get("monsterPrefab", ""))
        if b not in skill_blobs:
            skill_blobs[b] = read_unityfs.load(bundle_file(b))
        bundle_tokens |= {t.decode() for t in SKILL_TOKEN.findall(skill_blobs[b])}

    def skill_base(name):
        return str(name or "").split("#")[0]

    base_ids = {}
    for r in dg.load_data("MonsterSkillTable")["rows"] + dg.mobile_rows(src, "MonsterSkillTable"):
        base_ids.setdefault(skill_base(r.get("monsterSkillIndexString")), set()).add(
            r.get("monsterSkillIndex"))
    chained = set()
    for t in bundle_tokens:
        chained |= base_ids.get(skill_base(t), set())
    orphan_skills = sorted(t for t in bundle_tokens if skill_base(t) not in base_ids)

    slot_skills = set()
    for r in row_of.values():
        slot_skills |= guards.skill_indexes(r)
    skills = set(slot_skills) | chained
    skill_set = set(skills)
    mst_skill = guards.dup_guard([r for r in dg.load_data("MonsterSkillTable")["rows"]
                                  if r.get("monsterSkillIndex") in skill_set],
                                 lambda r: r.get("monsterSkillIndex"), fields["MonsterSkillTable"],
                                 "MonsterSkillTable (project)")
    ref_skill = guards.dup_guard([r for r in dg.mobile_rows(src, "MonsterSkillTable")
                                  if r.get("monsterSkillIndex") in skill_set],
                                 lambda r: r.get("monsterSkillIndex"), fields["MonsterSkillTable"],
                                 "MonsterSkillTable (mobile)")
    gap = sorted(s for s in skills if s not in mst_skill and s not in ref_skill)
    if gap:
        fail(f"MonsterSkillTable: skill ids in neither the project tables nor the mobile source: {gap[:10]}")
    skill_add = [ref_skill[s] for s in sorted(skills) if s not in mst_skill]

    need_growth = {guards.as_int(r.get("growthType"), "growthType") for r in row_of.values()}
    mst_growth_rows = [r for r in dg.load_data("MonsterGrowthTable")["rows"]
                       if guards.as_int(r.get("growthType"), "growthType") in need_growth]
    ref_growth_rows = [r for r in dg.mobile_rows(src, "MonsterGrowthTable")
                       if guards.as_int(r.get("growthType"), "growthType") in need_growth]
    mst_growth = guards.dup_guard(mst_growth_rows, lambda r: r.get("monsterGrowthIndex"),
                                  fields["MonsterGrowthTable"], "MonsterGrowthTable (project)")
    ref_growth = guards.dup_guard(ref_growth_rows, lambda r: r.get("monsterGrowthIndex"),
                                  fields["MonsterGrowthTable"], "MonsterGrowthTable (mobile)")
    have_types = ({guards.as_int(r.get("growthType"), "growthType") for r in mst_growth_rows}
                  | {guards.as_int(r.get("growthType"), "growthType") for r in ref_growth_rows})
    gap = sorted(need_growth - have_types)
    if gap:
        fail(f"MonsterGrowthTable: growthType {gap} in neither the project tables nor the mobile source")
    growth_add = [r for r in ref_growth_rows if r.get("monsterGrowthIndex") not in mst_growth]

    ltypes = {guards.as_int(r.get("levelStatType"), "levelStatType") for r in row_of.values()}
    levels = {lvl for _, _, lvl, _ in flow}
    lkey = lambda r: ((guards.as_int(r.get("levelStatType"), "levelStatType"),
                       guards.as_int(r.get("monsterLevel"), "monsterLevel"))
                      if r.get("levelStatType") is not None else None)
    mst_lstat = guards.dup_guard([r for r in dg.load_data("MonsterLevelStatTable")["rows"]
                                  if lkey(r) and lkey(r)[0] in ltypes], lkey,
                                 fields["MonsterLevelStatTable"], "MonsterLevelStatTable (project)")
    ref_lstat = guards.dup_guard([r for r in dg.mobile_rows(src, "MonsterLevelStatTable")
                                  if lkey(r) and lkey(r)[0] in ltypes], lkey,
                                 fields["MonsterLevelStatTable"], "MonsterLevelStatTable (mobile)")
    need_lstat = {(t, l) for t in ltypes for l in levels}
    gap = sorted(p for p in need_lstat if p not in mst_lstat and p not in ref_lstat)
    if gap:
        fail(f"MonsterLevelStatTable: (levelStatType, level) {gap} in neither place")
    lstat_add = [r for r in dg.mobile_rows(src, "MonsterLevelStatTable")
                 if lkey(r) in need_lstat and lkey(r) not in mst_lstat]

    need_ai = set()
    for idx, _, _, ai in flow:
        for m in monsters_of_stage[idx][3]:
            if m in row_of:
                need_ai.add((guards.as_int(row_of[m].get("aiGroup"), "aiGroup"), ai))
    akey = lambda r: ((guards.as_int(r.get("aiGroup"), "aiGroup"),
                       guards.as_int(r.get("aiGrade"), "aiGrade"))
                      if r.get("aiGroup") is not None else None)
    mst_ai = guards.dup_guard([r for r in dg.load_data("AiGroupTable")["rows"] if akey(r) in need_ai],
                              akey, fields["AiGroupTable"], "AiGroupTable (project)")
    ref_ai = guards.dup_guard([r for r in dg.mobile_rows(src, "AiGroupTable") if akey(r) in need_ai],
                              akey, fields["AiGroupTable"], "AiGroupTable (mobile)")
    gap = sorted(p for p in need_ai if p not in mst_ai and p not in ref_ai)
    if gap:
        fail(f"AiGroupTable: (aiGroup, aiGrade) {gap} in neither the project tables nor the mobile source")
    ai_add = [r for r in dg.mobile_rows(src, "AiGroupTable") if akey(r) in need_ai and akey(r) not in mst_ai]

    for table, key_field, rows_add in (
            ("MonsterTable", "monsterIndex", mon_add),
            ("MonsterSkillTable", "monsterSkillIndex", skill_add),
            ("MonsterGrowthTable", "monsterGrowthIndex", growth_add),
            ("MonsterLevelStatTable", "monsterLevelStatIndex", lstat_add),
            ("AiGroupTable", "aiGroupIndex", ai_add)):
        have = guards.keyed(dg.load_data(table)["rows"], lambda r: r.get(key_field))
        for r in rows_add:
            old = have.get(r.get(key_field))
            if old is not None and not guards.same_row(old, r, fields[table]):
                fail(f"{table}: {key_field} {r.get(key_field)} already exists with different "
                     f"content -- refusing to append")

    strings = json.load(open(os.path.join(data, "strings_en.json"), encoding="utf-8"))
    texts = dg.mobile_texts(src, "MonsterTable")
    tags = {v for rows_add in (mon_add, skill_add) for r in rows_add
            for k, v in r.items() if k.endswith("Tag") and isinstance(v, str)}
    no_text = sorted(t for t in tags if t not in strings and t not in texts)

    counts = {table: len(dg.merge(schema, table, rows_add, key_field, src, ["MonsterTable"]))
              for table, key_field, rows_add in (
                  ("MonsterTable", "monsterIndex", mon_add),
                  ("MonsterSkillTable", "monsterSkillIndex", skill_add),
                  ("MonsterGrowthTable", "monsterGrowthIndex", growth_add),
                  ("MonsterLevelStatTable", "monsterLevelStatIndex", lstat_add),
                  ("AiGroupTable", "aiGroupIndex", ai_add))}
    maps_added = _apply_trigger_maps(src, data, maps_plan)
    for idx in sorted(monsters_of_stage):
        base, n_go, n_h, mons = monsters_of_stage[idx]
        print(f"stage {idx} {base}: subtree={n_go} graphs={n_h} monsters={len(mons)}")
    print(" | ".join(f"{t} +{n}" for t, n in counts.items())
          + f" | challenge monsters: {len(mon_strings)} distinct "
            f"({sum(len(monsters_of_stage[i][3]) for i in monsters_of_stage)} stage refs)")
    with_maps = [i for i in sorted(maps_plan["per_root"]) if maps_plan["per_root"][i]]
    print(f"ResourceMapTable +{maps_added} zone maps ({len(maps_plan['targets'])} targets from "
          f"{len(with_maps)}/9 roots: {maps_plan['targets']})")
    print(f"skills: {len(slot_skills)} skillNIndex slot refs + {len(chained - slot_skills)} reached "
          f"only through the bundles' chained Skill.* names "
          f"({len(bundle_tokens)} names scanned, {len(chained)} ids all real versions)")
    if orphan_skills:
        print(f"orphan Skill.* names in the monsters' own bundles (no row in any source, reported "
              f"only, nothing fabricated): {len(orphan_skills)} (first: {orphan_skills[:5]})")
    if orphans:
        print("orphans (no flowTrigger in ChallengeStageTable, reported only): "
              + ", ".join(f"{o['root']}={len(o['monsters'])} mons" for o in orphans))
    if divergent:
        print(f"divergent keys kept from the project tables, mobile row not merged over it: "
              f"{len(divergent)} (e.g. {divergent[:5]})")
    if no_text:
        print(f"strings: {len(no_text)} tags carry no text in any source and stay absent "
              f"(first: {no_text[:3]})")


if __name__ == "__main__":
    main()
