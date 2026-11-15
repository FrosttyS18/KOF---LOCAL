"""Import the enemy closure of Prove Dungeon (questEvent 10901) and Buff Select Dungeon (8101).

The two modes spawn their enemies through chains the other imports do not cover:

  Buff Select (Scene per floor, trigger prefabs/EventSystem/Trigger/Event/BuffSelect_N/BuffSelect_01..50,
  QuestEventStage 810101..810150, no monsterSpawnGroup): the monsters each floor really spawns come from
  a pointer-exact walk -- each singleTriggerName's root GameObject is followed through
  component->Transform->children PPtrs only (read_unity_serialized), every NodeCanvas.BehaviourTree
  linked under that subtree is decoded as a whole bounded length-prefixed JSON
  (import_timeattack_dependencies._graph_json) and only the two real typed spawn structures are read:
  ActionNode._action.m_makeMonsterList[].szMonsterName (the 49 BuffSellect attribute machines,
  skill-less) and the m_spawnList task variable's $content[].m_indexString (the wave Nests, the five
  suicide bombing spiders and the one intro boss every floor carries; a floor missing either structure
  aborts, and so does a floor whose graphs do not carry EXACTLY ONE m_spawnType "Intro" boss -- the
  live fifty floors each have exactly one, always through the task variable, and a floor that loses
  it keeps spawning waves with no boss and stalls, the measured BuffSelect 810101 v1024 hang).
  A bundle-wide Monster.* regex is NOT used -- it is blind to single-segment names (the 14
  *_BuffSelect_Nests bosses) and counts monsters no floor spawns: the standalone graph assets the walk
  meets in the same bundle (m_GameObject PPtr 0, unreached by any root) are reported only, never
  imported. Spawn names resolve against the tables case-insensitively (Monster.FindByString is
  ordinal-ignore-case; a casefold collision aborts), every floor's OWN aiGrade/monsterLevel drive its
  spawned monsters' AiGroupTable and MonsterLevelStatTable needs (no all-floors-by-all-groups product),
  the buffs (BuffSelectDungeonBuffTable buffMainType 2/3 -> BuffTable 64000001..64000103) close as
  before, and every consumed monster's prefab bundle must be in the client manifest AND the PC cache.
  The AI rows land mobile-original, then adapt_buffselect_pc_ai closes the PC's _Mob contract inside
  the same run: its preflight runs over the CURRENT AiGroupTable plus the planned AI rows BEFORE any
  table is written (a divergence aborts with nothing written) and adapt_current_master re-applies it
  after the merges -- the six legacy grade-1 rows restored to the BuffSelect originals
  (+aiOperationValue 1.0, local ids kept) and the 845 base stripped of its original _Mob suffix
  (Character-rooted fighters: the PC appends _Mob back at load). Group 842 spawns through
  Prefabs/Monster/, so MonsterInitializer_AI loads BuffSelect_MonsterBoss AS-IS and no alias is
  claimed for it; the one PENDING ASSET -- printed on every buffselect/all run and never verified
  here -- is 843's runtime alias BuffSelect_Goenitz_1_Normal_Mob, shipped separately (floor 810105's
  boss cannot load its AI until it ships). --mode prove never runs the adapter.
  Index/asset level only; nothing here claims combat.

  Prove (Scene_Single_ProveDungeonReady -> duel, trigger Tri_Prove_Common, no monsterSpawnGroup): the
  bosses are FIGHTERS, not monsters. Model_ProveDungeon.SetBossCharacters (0x180D5C720) finds each rolled
  ProveDungeonRandomBossTable string in ProveDungeonBossTeamTable, then CharacterTable rows at
  bossTeamStringIndex and bossTeamStrikerIndex (450 unique fighters), and builds DBData.Character +
  CharacterData.Character at the stage's bossLevel (CharacterLevelingTable.GetMaxExp), bossAwakenLevel
  (SetAwakenInfo) and bossCoreLevel (GetCoreTreeList). Each fighter drags its growthType (whole type:
  CharacterGrowthTable), characterSkillSetIndex (skills: SkillTable ids plus the ultimate's
  '#'-versioned rows, closed transitively over linkedSkillIndex), coreBoardIndex, evolveSetType and
  limitBreakItemIndex, plus its aiGroup row at each stage's aiGrade (group 690, grades 1..8).

Everything comes from the mobile source (kofas_server/server/tabel "baris") or the PC cache (bundles are
only read, never modified). Append-only like the sibling imports: existing rows are never touched, a
referenced id in neither place aborts the run naming the gap, and no value is ever invented. Bundle skill
names with no row in any source are reported as orphans and left alone (Hall of Elements precedent).
The Prove closure is PC-first and resumable: every dependency is derived from all consumed rows (the
project's own when present, so a partially applied import still closes what it already carries), and the
growth/evolve whole-type step skips by content, which keeps re-runs idempotent across re-indexes. Two
fields are ever rewritten, each documented at its site: the NEW boss fighters' pictureBookShow (set to
0 -- UI adaptation, keeps the 450 NPC duel enemies out of the collection book the client builds from
that flag), and -- the tool's single in-place exception -- 20319 orochiiori_98 DM's characterPrefab,
whose bundle exists locally only as an ANDROID build and is repointed at the PC base bundle (see
DM_PREFAB_ALIAS). Fighters whose character prefab bundle is not in the PC cache are imported anyway but
flagged in the report -- the table row is correct; only the client cannot load that boss until its
bundle exists.

--mode gates the two halves for INCREMENTAL validation; the complete closure ("all", the default and
the end goal) is unchanged. "buffselect" touches no player-facing table (no CharacterTable, SkillTable
or any Character* growth/evolve/board row): gameapi.owned_characters serves every CharacterTable row as
an owned fighter while save.json carries "ownAllFighters" (the default), so the 450 Prove profiles must
not enter CharacterTable before an isolation of enemy-only fighters exists, and
import_dungeons.append_player_ai_grades assumes every CharacterTable aiGroup is a homogeneous player
group -- enemy group 690 (per-grade rows) would abort that reimport. "prove" runs only the boss-fighter
half. BuffSelect needs nothing from Prove and vice versa: their AiGroupTable pairs are disjoint.

usage: import_prove_buff_dependencies.py <kofas_server folder> [--data DIR] [--report PATH]
                                       [--mode buffselect|prove|all]
"""
import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import import_dungeons as base          # one merge semantics: fields_of/load_data/save_data/merge/strings_add
import import_dungeon_monsters as mono  # strict int/key/dup guards of the monster closure import
import import_timeattack_dependencies as ta_deps  # _graph_json bounded decode + client bundle manifest
import read_unity_serialized            # canonical SerializedFile v22 index + PPtr-only subtree walk
import adapt_buffselect_pc_ai as bs_ai  # PC _Mob-contract adaptation of the BuffSelect AI rows (116)
import adapt_buffselect_pc_power as bs_power  # PC power-fold of the referenced BuffSelect buffs


BUFF_QE = 8101
PROVE_QE = 10901
BS_BUFF_FIELD = "buffIndex"
SKILL_SLOTS = ("activeSkill1Index", "activeSkill2Index", "activeSkill3Index", "activeSkill4Index",
               "activeSkill5Index", "activeSkill6Index", "activeSkill7Index", "specialSkill1Index",
               "supporterSkill1Index")

# 20319 orochiiori_98 DM: the ONLY boss whose mobile prefab dir (98_orochiiori_dm) has no PC bundle. The
# one local copy (mobile-files/assetbundles) is an ANDROID build (SerializedFile targetPlatform 13; the
# PC bundles are 19) and cannot load on this client. The PC-faithful adaptation -- evidence in
# native-analysis/prove-buff-contract.md and the bridge's prove20319-assets.md -- repoints ONLY this
# row's characterPrefab at the exact base string PC fighter 1268 loads. A fighter's skills are components
# serialized inside its own bundle's prefabs; the base bundle embeds the same 22 Skill.OrochiIori.*
# families the DM skill set references (matched by base name, no '#version' in either bundle), and the
# client resolves asset names case-insensitively (the other 449 bosses already load CamelCase mobile
# names against lowercase PC container paths). Every other field stays verbatim; if a PC build of the DM
# bundle ever lands in the cache this alias must be dropped (the guard below enforces it).
DM_PREFAB_ALIAS = {20319: ("Prefabs/Character/98_orochiiori_dm/98_OrochiIori_DM",
                           "Prefabs/Character/98_orochiiori/98_orochiiori")}


def fail(msg):
    sys.exit(f"import_prove_buff_dependencies: {msg}")


def bundle_path(name):
    return os.path.join(base.BUNDLES, hashlib.md5(name.encode()).hexdigest())


def bundle_skill_names(path):
    """Sorted Skill.* strings of a cached UnityFS bundle, path-tail false positives dropped."""
    blob = base.read_unityfs.load(path).decode("latin-1")
    return sorted(n for n in {m.group(0) for m in re.finditer(r"Skill\.[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*", blob)}
                  if not any(part.startswith("prefab") for part in n.split(".")[1:]))


def monster_prefab_bundle(row):
    """The CDN bundle of a prefab is named after its full directory path
    (Prefabs/Monster/Death/Death -> prefabs_monster_death). NOT hardcoded to prefabs_monster_*:
    the BuffSelect fighter bosses' monsterPrefab legitimately lives under Prefabs/Character/
    (Goenitz_96, Mukai, Ash_03, Rock_14, Nakoruru and the TF bosses reuse the fighter's own
    bundle), and a prefabs_monster_ fabrication for those rows names a bundle that exists
    nowhere in the client."""
    parts = row["monsterPrefab"].split("/")
    return "_".join(parts[:-1]).lower() if len(parts) > 1 else None


def wanted_or_fail(label, wanted, have, mobile, key):
    """Ids `wanted` must exist in the project (`have`) or the mobile rows keyed the same way."""
    gap = sorted(i for i in wanted if i not in have and i not in mobile)
    if gap:
        fail(f"{label}: {key} in neither the project tables nor the mobile source: {gap[:12]}"
             f"{'...' if len(gap) > 12 else ''}")
    return [mobile[i] for i in sorted(wanted) if i not in have]


def whole_type_rows(schema, src, table, index_field, type_field, types):
    """Every mobile row of the wanted types, whole: a growth/evolve type is many rows and the client's
    range search needs them all -- CharacterGrowthTable.GetCharacterGrowth (0x180D11B30) builds its
    RangeSearchParam from (isAwaken, growthType, grade, level) and RangeSearcher.DoCompare (0x180D11D70)
    compares that tuple only; the proto's primary index (+0x10) never enters the search and no schema
    field references it, so the two sources' independent numbering can be told apart safely. A mobile
    row whose content (every schema field but the index) is already here is skipped -- that is what
    makes a re-run after a re-index idempotent; an index already carried by a row of the same type is
    the project's own row winning, per the sibling imports' convention; a true index conflict is
    re-indexed past every key in play (a key allocation, never a content change)."""
    fields = base.fields_of(schema, table)
    off_rows = base.load_data(table)["rows"]
    off_by_idx = {}
    for r in off_rows:
        off_by_idx.setdefault(mono.as_int(r.get(index_field), f"{table}.{index_field}"), r)
    have_types = {mono.as_int(r.get(type_field), f"{table}.{type_field}") for r in off_rows}

    def fingerprint(r):
        return json.dumps({k: r.get(k) for k in sorted(fields) if k != index_field},
                          sort_keys=True, ensure_ascii=False)

    have_fp = {fingerprint(r) for r in off_rows}
    mobile_rows = [r for r in base.mobile_rows(src, table)
                   if mono.as_int(r.get(type_field), f"{table}.{type_field}") in types]
    missing = sorted(t for t in types if t not in have_types
                     and t not in {mono.as_int(r.get(type_field), f"{table}.{type_field}") for r in mobile_rows})
    if missing:
        fail(f"{table}: {type_field} in neither the project tables nor the mobile source: {missing}")
    next_index = max(list(off_by_idx) or [0])
    next_index = max(next_index, max((mono.as_int(r.get(index_field), f"{table}.{index_field}")
                                      for r in mobile_rows), default=0))
    out, reindexed, pc_wins, resumed = [], [], 0, 0
    for r in sorted(mobile_rows, key=lambda x: mono.as_int(x.get(index_field), f"{table}.{index_field}")):
        if fingerprint(r) in have_fp:
            resumed += 1          # content already imported (maybe under a re-indexed key): nothing to do
            continue
        idx = mono.as_int(r.get(index_field), f"{table}.{index_field}")
        typ = mono.as_int(r.get(type_field), f"{table}.{type_field}")
        if idx in off_by_idx:
            if mono.as_int(off_by_idx[idx].get(type_field), f"{table}.{type_field}") == typ:
                pc_wins += 1        # the project's own row of this type: it stays, mobile row not merged
                continue
            next_index += 1
            row = dict(r)
            row[index_field] = next_index
            out.append(row)
            reindexed.append((idx, next_index, typ))
        else:
            out.append(r)
    return out, {"pc_row_kept": pc_wins, "reindexed": reindexed, "resumed_content": resumed}


def _typed_stage_spawns(graph, label):
    """(make_monster, spawn_list, intro_bosses): the two real typed spawn structures of one
    decoded graph, recursed whole so nested lists cannot hide an entry -- ActionNode._action.
    m_makeMonsterList[].szMonsterName and the m_spawnList carriers' $content[].m_indexString,
    each entry KEEPING its typed m_spawnType ("Spawn" wave or "Intro" boss; the live fifty
    floors carry their one and only Intro through the m_spawnList TASK VARIABLE -- the
    ActionSpawnMonsterWrap field is an always-empty list there). An entry whose typed name
    field is missing or empty aborts (a Json.NET "$ref" entry would too), and so does a
    m_spawnList carrier that is itself malformed (m_value without a $content list, or the
    action field not serialized as a list -- all 50 live actions carry it): a broken spawn
    source must never disappear just because another carrier of the same graph is valid."""
    make_monster, spawn_list, intro_bosses = set(), set(), set()

    def spawn_entries(entries, carrier):
        for e in entries:
            name = e.get("m_indexString") if isinstance(e, dict) else None
            if not isinstance(name, str) or not name:
                fail(f"{label}: {carrier} entry without m_indexString -- refusing")
            spawn_list.add(name)
            if e.get("m_spawnType") == "Intro":
                intro_bosses.add(name)

    def rec(node):
        if isinstance(node, dict):
            lst = node.get("m_makeMonsterList")
            if isinstance(lst, list):
                for e in lst:
                    name = e.get("szMonsterName") if isinstance(e, dict) else None
                    if not isinstance(name, str) or not name:
                        fail(f"{label}: m_makeMonsterList entry without szMonsterName -- refusing")
                    make_monster.add(name)
            if node.get("m_variableName") == "m_spawnList":
                value = node.get("m_value")
                content = value.get("$content") if isinstance(value, dict) else None
                if not isinstance(content, list):
                    fail(f"{label}: m_spawnList task variable without a $content list -- refusing")
                spawn_entries(content, "m_spawnList task variable")
            if node.get("$type", "").endswith("ActionSpawnMonsterWrap"):
                if not isinstance(node.get("m_spawnList"), list):
                    fail(f"{label}: ActionSpawnMonsterWrap without an m_spawnList list -- refusing")
                spawn_entries(node["m_spawnList"], "ActionSpawnMonsterWrap.m_spawnList")
            for v in node.values():
                rec(v)
        elif isinstance(node, list):
            for v in node:
                rec(v)

    rec(graph)
    return make_monster, spawn_list, intro_bosses


def buffselect_stage_spawns(stages, manifest):
    """({stageIndex: {"root", "bundle", "make_monster", "spawn_list"}}, standalone_assets):
    the per-floor typed spawn closure. Each floor's singleTriggerName names its trigger prefab;
    the root GameObject is located by name inside that bundle only to pick the PPtr the walk
    then follows (component->Transform->children), every NodeCanvas.BehaviourTree linked under
    the subtree is decoded bounded, and a floor with no graph, no m_makeMonsterList or no
    m_spawnList aborts (all fifty live floors carry the attribute machine AND the boss).
    Graphs in the same bundles no floor root reaches (the fifty standalone assets,
    m_GameObject PPtr 0) are collected for the report and demand nothing."""
    indexed, linked = {}, {}
    per_stage, standalone = {}, []
    for s in stages:
        idx = mono.as_int(s.get("questEventStageIndex"), "questEventStageIndex")
        path = s.get("singleTriggerName") or ""
        root_name = path.rsplit("/", 1)[-1] if "/" in path else ""
        if not root_name:
            fail(f"QuestEventStage {idx}: no singleTriggerName -- the trigger root cannot be located")
        bundle = ta_deps.bundle_of_prefab(path)
        if not bundle or bundle not in manifest:
            fail(f"QuestEventStage {idx}: trigger bundle of {path!r} is not in the client manifest")
        if not os.path.isfile(bundle_path(bundle)):
            fail(f"QuestEventStage {idx}: trigger bundle {bundle} has no file in the PC cache")
        if bundle not in indexed:
            try:
                _, gos, mbs, trs, _ = read_unity_serialized.index_bundle(bundle_path(bundle))
            except Exception as exc:
                fail(f"trigger bundle {bundle}: cannot parse ({exc!r}) -- refusing")
            indexed[bundle] = (gos, mbs, trs)
            linked[bundle] = set()
        gos, mbs, trs = indexed[bundle]
        roots = [p for p, g in gos.items() if g["name"] == root_name]
        if not roots:
            fail(f"QuestEventStage {idx}: root GameObject {root_name!r} not found in bundle {bundle}")
        sub = set()
        for rp in roots:
            sub |= read_unity_serialized.subtree_gameobjects(gos, trs, rp)
        make_monster, spawn_list, intro_bosses, graph_pids = set(), set(), set(), set()
        for pid, m in mbs.items():
            if m["go_pid"] not in sub or read_unity_serialized.GRAPH_MARKER not in m["payload"]:
                continue
            graph = ta_deps._graph_json(m["payload"])
            graph_pids.add(pid)
            mk, sl, intro = _typed_stage_spawns(graph, f"stage {idx} {root_name}")
            make_monster |= mk
            spawn_list |= sl
            intro_bosses |= intro
        if not graph_pids:
            fail(f"QuestEventStage {idx}: no NodeCanvas.BehaviourTree linked under root {root_name!r}")
        if not make_monster or not spawn_list:
            fail(f"QuestEventStage {idx}: graph under {root_name!r} lost a typed spawn structure "
                 f"(make_monster={len(make_monster)}, spawn_list={len(spawn_list)}) -- refusing")
        if len(intro_bosses) != 1:
            fail(f"QuestEventStage {idx}: graphs under {root_name!r} carry {len(intro_bosses)} intro "
                 f"bosses (m_spawnType \"Intro\" of the m_spawnList task variable), exactly 1 expected "
                 f"-- the live fifty floors each carry one, and a floor that loses it spawns its waves "
                 f"with no boss and stalls (measured: BuffSelect 810101 v1024, 55s hang, "
                 f"ActionSpawnMonsterWrap Failure)")
        linked[bundle] |= graph_pids
        per_stage[idx] = {"root": root_name, "bundle": bundle, "intro": sorted(intro_bosses)[0],
                          "make_monster": make_monster, "spawn_list": spawn_list}
    for bundle in sorted(indexed):
        gos, mbs, trs = indexed[bundle]
        for pid in sorted(mbs):
            m = mbs[pid]
            if pid in linked[bundle] or read_unity_serialized.GRAPH_MARKER not in m["payload"]:
                continue
            try:
                mk, sl, _ = _typed_stage_spawns(ta_deps._graph_json(m["payload"]),
                                                f"standalone asset {pid:016x} of {bundle}")
            except SystemExit as exc:
                standalone.append({"bundle": bundle, "mb_pid": f"{pid:016x}",
                                   "monsters": [f"<unreadable graph: {exc}>"]})
                continue
            monsters = sorted(mk | sl)
            if monsters:
                standalone.append({"bundle": bundle, "mb_pid": f"{pid:016x}", "monsters": monsters})
    return per_stage, standalone


def _row_by_casefold(names, rows, table):
    """name -> row resolved the client's way (Monster.FindByString is ORDINAL_IGNORE_CASE,
    0x180D42B20): the spawn name matches a monsterIndexString case-insensitively. Only rows
    matching one of `names` are considered; two rows (or two distinct strings) answering the
    same spawn name abort -- a spawn may never resolve to two monsters."""
    wanted = {n.casefold() for n in names}
    by_casefold = {}
    for r in rows:
        s = r.get("monsterIndexString")
        if not isinstance(s, str) or not s or s.casefold() not in wanted:
            continue
        prev = by_casefold.setdefault(s.casefold(), r)
        if prev is not r:
            fail(f"{table}: spawn names {s!r} and {prev.get('monsterIndexString')!r} collide "
                 f"case-insensitively -- refusing to guess which one the floor spawns")
    return {n: by_casefold[n.casefold()] for n in names if n.casefold() in by_casefold}


def buffselect_plan(schema, src, stages):
    """(per-table rows to append, string tag sets, notes) of the Buff Select closure."""
    manifest = ta_deps.bundle_manifest()
    per_stage, standalone = buffselect_stage_spawns(stages, manifest)
    names = sorted({n for s in per_stage.values()
                    for n in (s["make_monster"] | s["spawn_list"])})
    mob_map = _row_by_casefold(names, base.mobile_rows(src, "MonsterTable"), "MonsterTable (mobile)")
    mst_map = _row_by_casefold(names, base.load_data("MonsterTable")["rows"], "MonsterTable (project)")
    gap = [n for n in names if n not in mob_map and n not in mst_map]
    if gap:
        fail(f"MonsterTable: typed floor spawns in neither the project tables nor the mobile source: {gap}")

    row_of = {n: (mst_map.get(n) or mob_map[n]) for n in names}   # PC row first, like prove_plan
    monsters = [row_of[n] for n in names]
    uncached = []
    for n, r in sorted(row_of.items()):
        b = monster_prefab_bundle(r)
        if b not in manifest or not os.path.isfile(bundle_path(b)):
            uncached.append({"monster": n, "bundle": b, "alreadyInProjectTables": n in mst_map})
    if uncached:
        fail(f"monster prefab bundles missing from the client manifest/PC cache (the client could "
             f"never load them): {uncached}")

    # every floor's OWN aiGrade/monsterLevel drive its spawned monsters' AI and level-stat needs
    need_ai, need_lstat, floors_of_pair = set(), set(), {}
    for s in stages:
        idx = mono.as_int(s.get("questEventStageIndex"), "questEventStageIndex")
        grade = mono.as_int(s.get("aiGrade"), "aiGrade") if s.get("aiGrade") else None
        level = mono.as_int(s.get("monsterLevel"), "monsterLevel") if s.get("monsterLevel") else None
        for n in sorted(per_stage[idx]["make_monster"] | per_stage[idx]["spawn_list"]):
            r = row_of[n]
            if r.get("aiGroup") is not None and grade is not None:
                pair = (mono.as_int(r.get("aiGroup"), "aiGroup"), grade)
                need_ai.add(pair)
                floors_of_pair.setdefault(pair, []).append(idx)
            if r.get("levelStatType") is not None and level is not None:
                need_lstat.add((mono.as_int(r.get("levelStatType"), "levelStatType"), level))

    pc_ai_rows = {(mono.as_int(r.get("aiGroup"), "aiGroup"), mono.as_int(r.get("aiGrade"), "aiGrade")): r
                  for r in base.load_data("AiGroupTable")["rows"]}
    mob_ai_rows = {(mono.as_int(r.get("aiGroup"), "aiGroup"), mono.as_int(r.get("aiGrade"), "aiGrade")): r
                   for r in base.mobile_rows(src, "AiGroupTable")}
    ai = wanted_or_fail("AiGroupTable", need_ai, set(pc_ai_rows), mob_ai_rows, "(aiGroup, aiGrade)")
    # PC-first keeps the project's grade-1 rows; the divergence is reported, never overwritten
    grade1_divergent = []
    for pair in sorted(need_ai):
        if pair[1] != 1:
            continue
        pc_row, mob_row = pc_ai_rows.get(pair), mob_ai_rows.get(pair)
        if pc_row and mob_row and pc_row != mob_row:
            grade1_divergent.append({"aiGroup": pair[0], "floors": sorted(floors_of_pair[pair]),
                                     "pc_row": pc_row, "mobile_row": mob_row})

    skills = set()
    for r in monsters:
        skills |= mono.skill_indexes(r)
    chain, orphans = set(), {}
    have_skill_string = {r.get("monsterSkillIndexString") for r in base.load_data("MonsterSkillTable")["rows"]}
    mobile_skill_string = {r.get("monsterSkillIndexString"): r for r in base.mobile_rows(src, "MonsterSkillTable")}
    for r in monsters:
        if not mono.skill_indexes(r):
            continue                                   # skill-less machines: SetSkillData never runs for them
        for sname in bundle_skill_names(bundle_path(monster_prefab_bundle(r))):
            if sname + "#1" in have_skill_string:
                continue
            if sname + "#1" in mobile_skill_string:
                chain.add(sname + "#1")
            else:
                orphans.setdefault(sname, r["monsterIndexString"])
    chain_rows = [mobile_skill_string[s] for s in sorted(chain)]
    direct = wanted_or_fail("MonsterSkillTable", skills,
                            {int(r.get("monsterSkillIndex") or 0) for r in base.load_data("MonsterSkillTable")["rows"]},
                            {int(r.get("monsterSkillIndex") or 0): r for r in base.mobile_rows(src, "MonsterSkillTable")},
                            "monsterSkillIndex")

    buffs = {mono.as_int(r.get(BS_BUFF_FIELD), BS_BUFF_FIELD)
             for r in base.load_data("BuffSelectDungeonBuffTable")["rows"] if r.get(BS_BUFF_FIELD)}
    buff_rows = wanted_or_fail("BuffTable", buffs,
                               {mono.as_int(r.get(BS_BUFF_FIELD), BS_BUFF_FIELD) for r in base.load_data("BuffTable")["rows"]},
                               {mono.as_int(r.get(BS_BUFF_FIELD), BS_BUFF_FIELD): r
                                for r in base.mobile_rows(src, "BuffTable")}, BS_BUFF_FIELD)

    lstat = wanted_or_fail("MonsterLevelStatTable", need_lstat,
                           {(mono.as_int(r.get("levelStatType"), "levelStatType"),
                             mono.as_int(r.get("monsterLevel"), "monsterLevel"))
                            for r in base.load_data("MonsterLevelStatTable")["rows"]},
                           {(mono.as_int(r.get("levelStatType"), "levelStatType"),
                             mono.as_int(r.get("monsterLevel"), "monsterLevel")): r
                            for r in base.mobile_rows(src, "MonsterLevelStatTable")}, "(levelStatType, level)")
    grow, grow_notes = whole_type_rows(schema, src, "MonsterGrowthTable", "monsterGrowthIndex", "growthType",
                                       {mono.as_int(r.get("growthType"), "growthType")
                                        for r in monsters if r.get("growthType")})

    add = [("MonsterTable", "monsterIndex", [r for r in monsters if r.get("monsterIndex") not in
                                             {x.get("monsterIndex") for x in base.load_data("MonsterTable")["rows"]}]),
           ("MonsterSkillTable", "monsterSkillIndex", direct + chain_rows),
           ("AiGroupTable", "aiGroupIndex", ai),
           ("BuffTable", BS_BUFF_FIELD, buff_rows),
           ("MonsterLevelStatTable", "monsterLevelStatIndex", lstat),
           ("MonsterGrowthTable", "monsterGrowthIndex", grow)]
    tags = ({r.get("monsterNameTag") for r in monsters}
            | {t for r in chain_rows + direct for t in (r.get("monsterNameTag"),) if t}
            | {t for r in buff_rows for t in (r.get("buffNameTag"), r.get("buffDescriptionTag")) if t})
    return add, tags, {"trigger_monsters": len(names), "floors": len(per_stage),
                       "per_floor_spawns": {str(i): {"root": v["root"], "bundle": v["bundle"],
                                                     "intro_boss": v["intro"],
                                                     "make_monster": sorted(v["make_monster"]),
                                                     "spawn_list": sorted(v["spawn_list"])}
                                            for i, v in sorted(per_stage.items())},
                       "standalone_graph_assets": standalone,
                       "ai_grade1_pc_divergent": grade1_divergent,
                       "skill_chain_orphans": orphans,
                       "monster_growth": grow_notes}


def prove_plan(schema, src, stages, quest_stage_of):
    """(per-table rows to append, string tag sets, notes) of the Prove boss-fighter closure.

    PC-first (resumable): every dependency is derived from ALL consumed rows -- the project's own row
    when it has one, the mobile row otherwise -- so resuming a partially applied import (fighters and
    skill sets already in, skills/growth/items not) still closes everything already applied. The append
    lists stay strictly add-only: rows the project already carries are never re-merged."""
    teams = base.load_data("ProveDungeonBossTeamTable")["rows"]
    fighters = sorted({mono.as_int(r.get("bossTeamStringIndex"), "bossTeamStringIndex") for r in teams
                       if r.get("bossTeamStringIndex")}
                      | {mono.as_int(r.get("bossTeamStrikerIndex"), "bossTeamStrikerIndex") for r in teams
                         if r.get("bossTeamStrikerIndex")})
    mobile_char = {mono.as_int(r.get("characterIndex"), "characterIndex"): r
                   for r in base.mobile_rows(src, "CharacterTable")}
    mst_char = {mono.as_int(r.get("characterIndex"), "characterIndex"): r
                for r in base.load_data("CharacterTable")["rows"]}
    gap = [i for i in fighters if i not in mst_char and i not in mobile_char]
    if gap:
        fail(f"CharacterTable: boss fighters in neither the project tables nor the mobile source: {gap[:8]}")
    chars_all = [mst_char[i] if i in mst_char else mobile_char[i] for i in fighters]
    chars = [mobile_char[i] for i in fighters if i not in mst_char]
    char_fields = base.fields_of(schema, "CharacterTable")
    if chars and "pictureBookShow" not in char_fields:
        fail("CharacterTable: schema has no pictureBookShow -- the NPC book adaptation could not be applied")
    for r in chars:
        # UI ADAPTATION on NEW rows only, this field only: the client's collection book lists every
        # CharacterTable row with pictureBookShow=1, and the mobile source carries the 450 bosses at 1
        # (its own book listed them); here they would show up as 450 unobtainable entries duplicating
        # playable fighters. 0 keeps them out of the book while every combat field stays verbatim --
        # the duel path (SetBossCharacters) reads the row by index and never this field.
        r["pictureBookShow"] = 0
    aliased, repaired = [], []
    for r in chars_all:
        idx = mono.as_int(r.get("characterIndex"), "characterIndex")
        original, aliased_path = DM_PREFAB_ALIAS.get(idx, (None, None))
        if not original:
            continue
        dm_bundle = "prefabs_" + "_".join(p.lower() for p in original.split("/")[1:-1])
        pc_bundle = "prefabs_" + "_".join(p.lower() for p in aliased_path.split("/")[1:-1])
        if os.path.isfile(bundle_path(dm_bundle)):
            continue          # a PC build of the DM bundle exists: keep the row verbatim, alias retired
        current = r.get("characterPrefab")
        if current == aliased_path:
            continue          # the alias is already in place (a fresh append or an earlier repair)
        if current != original:
            fail(f"CharacterTable {idx}: prefab is {current!r}, DM_PREFAB_ALIAS expects {original!r} "
                 "-- the alias table is stale")
        if not os.path.isfile(bundle_path(pc_bundle)):
            fail(f"CharacterTable {idx}: alias target bundle {pc_bundle} missing from the PC cache")
        r["characterPrefab"] = aliased_path
        if idx in mst_char:
            repaired.append(idx)     # row an earlier run already appended: an in-place one-field repair
        else:
            aliased.append(idx)      # row this run appends with the aliased path from the start
    uncached_prefabs = sorted({r["characterPrefab"] for r in chars_all
                               if not os.path.isfile(bundle_path("prefabs_" + "_".join(
                                   p.lower() for p in r["characterPrefab"].split("/")[1:-1])))})

    levels = sorted({mono.as_int(s.get("bossLevel"), "bossLevel") for s in stages if s.get("bossLevel")})
    leveling = wanted_or_fail("CharacterLevelingTable", set(levels),
                              {mono.as_int(r.get("chracterLevel"), "chracterLevel")
                               for r in base.load_data("CharacterLevelingTable")["rows"]},
                              {mono.as_int(r.get("chracterLevel"), "chracterLevel"): r
                               for r in base.mobile_rows(src, "CharacterLevelingTable")}, "chracterLevel")
    growth, growth_notes = whole_type_rows(schema, src, "CharacterGrowthTable", "characterGrowthIndex",
                                           "growthType", {mono.as_int(r.get("growthType"), "growthType")
                                                          for r in chars_all if r.get("growthType")})

    ss_ids = {mono.as_int(r.get("characterSkillSetIndex"), "characterSkillSetIndex")
              for r in chars_all if r.get("characterSkillSetIndex")}
    mst_ss = {mono.as_int(r.get("characterSkillSetIndex"), "characterSkillSetIndex"): r
              for r in base.load_data("CharacterSkillSetTable")["rows"]}
    mob_ss = {mono.as_int(r.get("characterSkillSetIndex"), "characterSkillSetIndex"): r
              for r in base.mobile_rows(src, "CharacterSkillSetTable")}
    gap = sorted(i for i in ss_ids if i not in mst_ss and i not in mob_ss)
    if gap:
        fail(f"CharacterSkillSetTable: characterSkillSetIndex in neither place: {gap[:8]}")
    ss_all = [mst_ss[i] if i in mst_ss else mob_ss[i] for i in sorted(ss_ids)]
    skillsets = [mob_ss[i] for i in sorted(ss_ids) if i not in mst_ss]

    boards = wanted_or_fail("CoreBoardTable", {mono.as_int(r.get("coreBoardIndex"), "coreBoardIndex")
                                               for r in chars_all if r.get("coreBoardIndex")},
                            {mono.as_int(r.get("coreBoardIndex"), "coreBoardIndex")
                             for r in base.load_data("CoreBoardTable")["rows"]},
                            {mono.as_int(r.get("coreBoardIndex"), "coreBoardIndex"): r
                             for r in base.mobile_rows(src, "CoreBoardTable")}, "coreBoardIndex")
    evolves, evolve_notes = whole_type_rows(schema, src, "CharacterEvolveTable", "characterEvolveIndex",
                                            "evolveSetType", {mono.as_int(r.get("evolveSetType"), "evolveSetType")
                                                              for r in chars_all if r.get("evolveSetType")})
    items = wanted_or_fail("ItemTable", {mono.as_int(r.get("limitBreakItemIndex"), "limitBreakItemIndex")
                                         for r in chars_all if r.get("limitBreakItemIndex")},
                           {mono.as_int(r.get("itemIndex"), "itemIndex") for r in base.load_data("ItemTable")["rows"]},
                           {mono.as_int(r.get("itemIndex"), "itemIndex"): r
                            for r in base.mobile_rows(src, "ItemTable")}, "itemIndex")

    pc_skill = {mono.as_int(r.get("skillIndex"), "skillIndex"): r for r in base.load_data("SkillTable")["rows"]}
    mobile_skill = {mono.as_int(r.get("skillIndex"), "skillIndex"): r
                    for r in base.mobile_rows(src, "SkillTable")}
    seeds = {mono.as_int(r[k], k) for r in ss_all for k in SKILL_SLOTS if r.get(k)}
    ults = {r.get("ultimateSkill1IndexString") for r in ss_all if r.get("ultimateSkill1IndexString")}
    prefixes = tuple(u + "#" for u in ults)
    seeds |= {i for src_rows in (pc_skill, mobile_skill) for i, r in src_rows.items()
              if str(r.get("skillIndexString") or "").startswith(prefixes)}
    closure, frontier = set(seeds), list(seeds)
    while frontier:
        nxt = []
        for i in frontier:
            row = pc_skill.get(i) or mobile_skill.get(i)   # PC-first: a skill already here closes the chain
            if row is None:
                fail(f"SkillTable: skillIndex {i} of the boss skill sets is in neither place")
            link = mono.as_int(row.get("linkedSkillIndex"), "linkedSkillIndex") if row.get("linkedSkillIndex") else 0
            if link and link not in closure:
                closure.add(link)
                nxt.append(link)
        frontier = nxt
    skills = [mobile_skill[i] for i in sorted(closure) if i not in pc_skill]

    grades = sorted({mono.as_int(quest_stage_of[mono.as_int(s.get("questEventStageIndex"), "questEventStageIndex")]
                                 .get("aiGrade"), "aiGrade") for s in stages
                     if s.get("questEventStageIndex") in quest_stage_of and quest_stage_of[
                         mono.as_int(s.get("questEventStageIndex"), "questEventStageIndex")].get("aiGrade")})
    groups = sorted({mono.as_int(r.get("aiGroup"), "aiGroup") for r in chars_all if r.get("aiGroup") is not None})
    ai = wanted_or_fail("AiGroupTable", {(g, gr) for g in groups for gr in grades},
                        {(mono.as_int(r.get("aiGroup"), "aiGroup"), mono.as_int(r.get("aiGrade"), "aiGrade"))
                         for r in base.load_data("AiGroupTable")["rows"]},
                        {(mono.as_int(r.get("aiGroup"), "aiGroup"), mono.as_int(r.get("aiGrade"), "aiGrade")): r
                         for r in base.mobile_rows(src, "AiGroupTable")}, "(aiGroup, aiGrade)")

    add = [("CharacterTable", "characterIndex", chars),
           ("CharacterGrowthTable", "characterGrowthIndex", growth),
           ("CharacterSkillSetTable", "characterSkillSetIndex", skillsets),
           ("CoreBoardTable", "coreBoardIndex", boards),
           ("CharacterEvolveTable", "characterEvolveIndex", evolves),
           ("ItemTable", "itemIndex", items),
           ("SkillTable", "skillIndex", skills),
           ("AiGroupTable", "aiGroupIndex", ai),
           ("CharacterLevelingTable", "characterLevelingIndex", leveling)]
    tags = {r.get("characterNameTag") for r in chars}
    return add, tags, {"fighters": len(fighters), "npc_book_hidden": len(chars),
                       "dm_prefab_alias": aliased, "dm_prefab_repaired": repaired,
                       "uncached_character_prefabs": uncached_prefabs,
                       "character_growth": growth_notes, "character_evolve": evolve_notes}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("src", help="kofas_server folder (with tabel/ and tabel_teks/)")
    parser.add_argument("--data", default=os.path.normpath(os.path.join(HERE, "..", "server",
                                                                        "tables", "data")),
                        help="tables data dir to update (default: the project's)")
    parser.add_argument("--report", help="write the exact appended rows as JSON to this path")
    parser.add_argument("--mode", choices=("buffselect", "prove", "all"), default="all",
                        help="incremental validation: 'buffselect' closes only the trigger monsters, their "
                             "skills/AI and the dungeon buffs (no CharacterTable/SkillTable and no Character* "
                             "row -- nothing the roster, gacha or player-AI reimport consumes); 'prove' only "
                             "the boss fighters; 'all' (default) the complete closure, the end goal")
    args = parser.parse_args()
    src, data = args.src, args.data
    if not os.path.isdir(os.path.join(src, "tabel")):
        fail(f"{src} has no tabel/ -- usage: import_prove_buff_dependencies.py <kofas_server folder> [--data DIR]")
    if not os.path.isfile(os.path.join(data, "QuestEventStageTable.json")):
        fail(f"{data} carries no QuestEventStageTable.json")
    schema = json.load(open(base.SCHEMA, encoding="utf-8"))
    base.DATA = data  # every helper reads it per call, so temp copies are fully supported

    consumed_buffselect = ("MonsterTable", "MonsterSkillTable", "MonsterGrowthTable",
                           "MonsterLevelStatTable", "AiGroupTable", "BuffTable")
    consumed_prove = ("AiGroupTable", "CharacterTable", "CharacterGrowthTable", "CharacterSkillSetTable",
                      "CoreBoardTable", "CharacterEvolveTable", "ItemTable", "SkillTable",
                      "CharacterLevelingTable")
    consumed = consumed_buffselect if args.mode == "buffselect" else (
        consumed_prove if args.mode == "prove" else consumed_buffselect + consumed_prove)
    for table in dict.fromkeys(consumed):     # each table once, mode-dependent order kept
        if table not in schema["tables"]:
            fail(f"{table}: not in schema.json")
        if not os.path.isfile(os.path.join(src, "tabel", table + ".json")):
            fail(f"mobile source lacks tabel/{table}.json")

    stages = [r for r in base.load_data("QuestEventStageTable")["rows"]
              if mono.as_int(r.get("questEventIndex"), "questEventIndex") == BUFF_QE]
    if len(stages) != 50:
        fail(f"QuestEventStageTable: expected the 50 Buff Select floors, found {len(stages)}")
    quest_stage_of = {mono.as_int(r.get("questEventStageIndex"), "questEventStageIndex"): r
                      for r in base.load_data("QuestEventStageTable")["rows"]}
    bs_add, bs_tags, bs_notes = [], set(), {}
    pv_add, pv_tags, pv_notes = [], set(), {}
    if args.mode != "prove":
        bs_add, bs_tags, bs_notes = buffselect_plan(schema, src, stages)
    if args.mode != "buffselect":
        prove_stages = base.load_data("ProveDungeonStageTable")["rows"]
        if not prove_stages:
            fail("ProveDungeonStageTable: no rows in the project tables")
        pv_add, pv_tags, pv_notes = prove_plan(schema, src, prove_stages, quest_stage_of)
    if args.mode != "prove":
        # The AI rows land mobile-original; the PC _Mob contract is closed by the same run. The
        # adapter's preflight runs over the post-merge table (current rows + every PLANNED AI row)
        # BEFORE any write happens -- ids and row order are untouched -- so a divergence aborts
        # with nothing written, and the apply after the merges only ever sees the validated state.
        planned_ai = [r for t, _, rows in bs_add + pv_add if t == "AiGroupTable" for r in rows]
        try:
            bs_ai.preflight(base.load_data("AiGroupTable")["rows"] + planned_ai,
                            bs_ai.oracle_pairs(os.path.join(src, "tabel")))
        except bs_ai.Divergence as exc:
            fail(f"AiGroupTable PC adaptation diverged (nothing written yet): {exc}")
        planned_buffs = [r for t, _, rows in bs_add + pv_add if t == "BuffTable" for r in rows]
        try:
            bs_power.preflight_rows(base.load_data("BuffTable")["rows"] + planned_buffs, data)
        except bs_power.Divergence as exc:
            fail(f"BuffTable power adaptation diverged (nothing written yet): {exc}")
    if args.mode != "buffselect":
        for idx in pv_notes.get("dm_prefab_repaired", []):
            # The tool's ONE in-place exception (import_dungeons has three of its own): a row this tool
            # already appended carries the DM prefab path an earlier run planned, and no PC build of that
            # bundle exists -- rewrite exactly that one field so the boss can load at all.
            original, aliased_path = DM_PREFAB_ALIAS[idx]
            doc = base.load_data("CharacterTable")
            row = next((r for r in doc["rows"] if mono.as_int(r.get("characterIndex"), "characterIndex")
                        == idx), None)
            if row is None or row.get("characterPrefab") != original:
                fail(f"CharacterTable {idx}: repair refused -- row missing or prefab already "
                     f"{(row or {}).get('characterPrefab')!r}")
            row["characterPrefab"] = aliased_path
            base.save_data("CharacterTable", doc)

    text_tables = {"MonsterTable": ["MonsterTable"], "BuffTable": ["BuffTable"],
                   "CharacterTable": ["CharacterTable"]}
    strings_path = os.path.join(data, "strings_en.json")
    strings_before = len(json.load(open(strings_path, encoding="utf-8")))
    appended, plan = {}, []
    for table, key, rows in bs_add + pv_add:
        added = base.merge(schema, table, rows, key, src, text_tables.get(table, []))
        appended[table] = appended.get(table, 0) + len(added)
        plan.append({"table": table, "key": key, "added": len(added),
                     "rows": [{k: v for k, v in r.items() if k in base.fields_of(schema, table)} for r in added]})
    strings_added = len(json.load(open(strings_path, encoding="utf-8"))) - strings_before

    ai_adaptation, power_fold = [], []
    if args.mode != "prove":
        try:
            applied = bs_ai.adapt_current_master(data, os.path.join(src, "tabel"))
        except bs_ai.Divergence as exc:
            fail(f"post-merge AiGroupTable adaptation diverged (tables already imported, the AI "
                 f"table NOT adapted -- fix and rerun): {exc}")
        ai_adaptation = [{"aiGroup": r.get("aiGroup"), "aiGrade": r.get("aiGrade"),
                          "field": f, "old": o, "new": n} for r, f, o, n in applied]
        try:
            power_fold = bs_power.mutate_tables(data)
        except bs_power.Divergence as exc:
            fail(f"post-merge BuffTable power fold diverged (tables already imported, the buffs "
                 f"NOT folded -- fix and rerun): {exc}")

    print(" | ".join(f"{t} +{n}" for t, n in appended.items() if n) or "tables: nothing to append")
    parts = [f"strings +{strings_added}"]
    if bs_notes:
        parts.append(f"BuffSelect trigger monsters {bs_notes['trigger_monsters']} "
                     f"(chain orphans left as-is: {len(bs_notes['skill_chain_orphans'])})")
    if pv_notes:
        parts.append(f"Prove fighters {pv_notes['fighters']}")
    print(" | ".join(parts))
    if bs_notes.get("skill_chain_orphans"):
        print("bundle skills with no row in any source (never invented): "
              + ", ".join(f"{n} [{m}]" for n, m in sorted(bs_notes["skill_chain_orphans"].items())))
    if bs_notes.get("standalone_graph_assets"):
        assets = bs_notes["standalone_graph_assets"]
        monsters = sorted({m for a in assets for m in a["monsters"]})
        print(f"standalone graph assets in the trigger bundle(s), REPORTED ONLY (no floor spawns them "
              f"via PPtr, nothing imported, no row demanded): {len(assets)} assets -> "
              + ", ".join(monsters))
    if args.mode != "prove":
        if ai_adaptation:
            print(f"AiGroupTable adapted to the PC _Mob contract: {len(ai_adaptation)} field changes "
                  "(six legacy grade-1 rows restored to the BuffSelect originals + aiOperationValue "
                  "1.0, 845 base stripped of _Mob; aiGroupIndex, ids and every other field kept)")
        else:
            print("AiGroupTable already PC-adapted, nothing to do")
        if power_fold:
            print(f"BuffTable power folded to the PC contract: {len(power_fold)} referenced buffs "
                  "base := perLv and max := perLv*buffMaxLevel (the client's Max clamp kept the "
                  "default 0 at zero; levels, perLv and every other field kept)")
        else:
            print("BuffTable power already folded, nothing to do")
        print("PENDING ASSET (never verified by this tool): aiGroup 843's base "
              "Prefabs/AI/BuffSelect/BuffSelect_Goenitz_1_Normal needs the runtime alias "
              "BuffSelect_Goenitz_1_Normal_Mob, shipped separately -- until it ships, floor 810105's "
              "boss cannot load its AI; aiGroup 842 loads BuffSelect_MonsterBoss as-is through "
              "MonsterInitializer_AI and needs no alias. Table-level adaptation only: runtime and "
              "combat are not validated by this import")
    if pv_notes.get("dm_prefab_alias") or pv_notes.get("dm_prefab_repaired"):
        parts = []
        if pv_notes.get("dm_prefab_alias"):
            parts.append(f"aliased at append on {pv_notes['dm_prefab_alias']}")
        if pv_notes.get("dm_prefab_repaired"):
            parts.append(f"repaired in place on {pv_notes['dm_prefab_repaired']}")
        print(f"CharacterTable 20319 orochiiori_98 DM: {'; '.join(parts)} -- its bundle exists only as an "
              "ANDROID build (targetPlatform 13; PC is 19), unusable on this client, so the row points at "
              "the base 98_orochiiori bundle PC fighter 1268 loads. Every other field verbatim; the alias "
              "retires itself if a PC build of the DM bundle ever reaches the cache")
    if pv_notes.get("uncached_character_prefabs"):
        print("WARNING fighters whose character prefab bundle is NOT in the PC cache (client cannot load "
              "them until the bundle exists; row still imported): "
              + ", ".join(pv_notes["uncached_character_prefabs"]))
    for label, notes in (("CharacterGrowthTable", pv_notes.get("character_growth", {})),
                         ("CharacterEvolveTable", pv_notes.get("character_evolve", {})),
                         ("MonsterGrowthTable", bs_notes.get("monster_growth", {}))):
        if notes.get("reindexed"):
            print(f"{label}: {notes.get('pc_row_kept', 0)} rows already carried by the project stayed (PC wins), "
                  f"{notes.get('resumed_content', 0)} already-imported contents skipped (idempotent), "
                  f"{len(notes['reindexed'])} rows re-indexed past every key in play "
                  f"({notes['reindexed'][0][0]}->{notes['reindexed'][0][1]} .. "
                  f"{notes['reindexed'][-1][0]}->{notes['reindexed'][-1][1]}; key allocation only, "
                  "content untouched -- GetCharacterGrowth searches by (isAwaken, growthType, grade, level), "
                  "never the index)")
    if pv_notes.get("npc_book_hidden"):
        print(f"CharacterTable: pictureBookShow=0 on {pv_notes['npc_book_hidden']} NEW boss rows only "
              "(UI adaptation: keeps the 450 NPC duel fighters out of the collection book; every combat "
              "field verbatim)")
    if args.report:
        json.dump({"mode": args.mode, "tables": appended, "strings_added": strings_added, "notes": {
            "buffselect": {k: v for k, v in bs_notes.items() if k != "skill_chain_orphans"},
            "buffselect_chain_orphans": bs_notes.get("skill_chain_orphans", {}),
            "ai_pc_adaptation": ai_adaptation,
            "power_pc_fold": [{"buffIndex": i, "buffPowerBase": p, "buffPowerMax": c}
                              for i, p, c in power_fold]
                              if args.mode != "prove" else None,
            "ai_pc_pending_asset": "Prefabs/AI/BuffSelect/BuffSelect_Goenitz_1_Normal_Mob (843; "
                                   "alias shipped separately, not verified here)" if args.mode != "prove" else None,
            "prove": {k: (len(v) if k == "uncached_character_prefabs" else v)
                      for k, v in pv_notes.items()}}, "plan": plan},
                  open(args.report, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print(f"report: {args.report}")


if __name__ == "__main__":
    main()
