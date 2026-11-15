"""Stage the Sura Dungeon enemy closure for the project tables -- ONLY a staging copy; the master
tables and the client cache are never written.

Observed gap this closes (v1021 live test, requests-20261115-032147.log): stage 1 fought 32s with
Progress 1/2/3 and ZERO enemies. The graphs spawn whole waves, not just the boss: each stage's QuestEventStage
singleTriggerName (Prefabs/EventSystem/Trigger/SuraDungeon/SuraDungeon_01..12) is a NodeCanvas
behaviour tree that names every monster it can spawn, and those names resolve through MonsterTable
rows the project tables did not carry -- SuraDungeonStageTable.monsterIndex (560004, Namaiki) is only
the api-side difficulty boss. Of the 23 distinct monsters the 12 trigger graphs name, the master had
exactly one; the mobile source carries all 23 (indexes 560001..560023). This is a confirmed missing-data
dependency; the effect of importing it still needs a real battle test. No bundle HTTP request was
observed between stageStart and stageEnd, but cached assets can load without HTTP, so that absence
alone does not identify where the spawn pipeline stopped.

Derivation, all from the project's own tables plus the cached bundles, nothing hardcoded:
SuraDungeonStageTable -> its QuestEventStage rows (must belong to questEvent 10801) -> each stage's
singleTriggerName -> the trigger family's one cached bundle (path dir lowercased, / -> _) ->
read_unity_serialized (GameObject/Transform/MonoBehaviour PPtr walk, no name matching beyond the
trigger root) -> the exact Monster.* set per stage, compared with MonsterTable.monsterIndexString
case-sensitively. Missing rows come from the mobile source; a project row always wins and is never
overwritten (divergences are reported).

Table closure on top of the monsters (the Tower/HoE importers' rules, plus the live-crash rule
tools/import_dungeons.close_hoe_skill_chains documents: MonsterBattleController.SetSkillData walks
each skill prefab's m_linkedSkill chain, and a missing child row kills the spawn in FormatException):
- direct skills: every skillNIndex of every consumed monster (master row wins when present);
- linked skills: each skill-carrying monster's cached bundle(s), resolved by evidence -- a bundle
  belongs to the monster when its decompressed bytes contain the base name (before '#') of one of
  that monster's direct skills, which is how the *_comdown ninja reuse and the iron/wood statue
  variants surface -- every Skill.* an owning bundle carries gets its mobile '#1' row (the only
  version any of these families has); bundle names with no row anywhere are reported as orphans,
  never invented; a skill-carrying monster with no owning bundle aborts the run;
- MonsterGrowthTable: every row of each consumed monster's growthType (the whole type set);
- MonsterLevelStatTable: (levelStatType, monsterLevel) for the 24 stages' own levels;
- AiGroupTable: (aiGroup, aiGrade) at each stage's original aiGrade for every monster that stage's
  graph names.
Strings come from the mobile text tables for the staged rows' tags; tags with no text stay absent
(like the project's other MonsterSkillTable rows). The spawn prefab naming inside bundles is NOT
reverse-engineered (root GameObjects are named "Namaiki", not the full index string; the working Hall
of Elements spawns prove the table rows are the gate), so prefab presence is only evidenced through
the skill bundles above.

Output (default tools/out_sura_enemies): one additions doc per table that gains rows (they all exist
in the project already), plus a manifest with the per-stage graph evidence, owning bundles, counts
and apply steps. Applying = append the additions to server/tables/data, then tools/build_tables.py,
tools/make_tablepacks.py and a server/game restart. Preflight guards all run before any write: an
aborted run leaves the output folder untouched, and a fully applied closure stages nothing
(idempotent, byte-identical on re-run).

usage: import_sura_enemies.py <kofas_server folder> [--data DIR] [--out DIR] [--bundles DIR]
"""
import argparse
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # the embedded python's _pth never adds the script's own folder
import import_dungeons as base             # read-only helpers; its writers are never called
import import_dungeon_monsters as M        # as_int/keyed/dup_guard/same_row/skill_indexes
import read_unity_serialized as U
import read_unityfs

SURA_QE = 10801
OUT_DEFAULT = os.path.join(HERE, "out_sura_enemies")
TABLES = (("MonsterTable", "monsterIndex"), ("MonsterSkillTable", "monsterSkillIndex"),
          ("MonsterGrowthTable", "monsterGrowthIndex"), ("MonsterLevelStatTable", "monsterLevelStatIndex"),
          ("AiGroupTable", "aiGroupIndex"))


def fail(msg):
    sys.exit("import_sura_enemies: %s" % msg)


def bundle_of(bundles, name):
    return bundles.get(name)


def cached_bundles():
    """name -> file of every bundle the client's own assetbundles.info lists with a file on disk."""
    info = os.path.join(os.path.dirname(BUNDLES.rstrip("/\\")), "assetbundles.info")
    if not os.path.isfile(info):
        fail("no assetbundles.info next to the bundle cache")
    raw = open(info, "rb").read()
    i, out = 0, {}
    while i + 4 <= len(raw):
        n = struct.unpack_from("<i", raw, i)[0]
        name = raw[i + 4:i + 4 + n].decode()
        i += 4 + n
        n = struct.unpack_from("<i", raw, i)[0]
        i += 4 + n
        f = os.path.join(BUNDLES, hashlib.md5(name.encode()).hexdigest())
        if os.path.isfile(f):
            out[name] = f
    if not out:
        fail("assetbundles.info lists no cached bundle")
    return out


def needle_holders(bundles, needles):
    """base name -> the cached prefabs_monster_* bundles whose decompressed bytes carry it. One pass
    over the candidate bundles: the needles are the monsters' direct skill base names, so a hit is
    the monster's own skill asset family -- no bundle-name guessing."""
    holders = {n: [] for n in needles}
    encoded = [(n, n.encode()) for n in needles]
    for name in sorted(bundles):
        if not name.startswith("prefabs_monster_"):
            continue
        data = read_unityfs.load(bundles[name])
        for needle, raw in encoded:
            if raw in data:
                holders[needle].append(name)
    return holders


def stage_graphs():
    """-> (stages, per-trigger monster sets, trigger path -> stage indexes, trigger bundle name)."""
    sura = sorted((r for r in base.load_data("SuraDungeonStageTable")["rows"]
                   if M.as_int(r.get("questEventStageIndex"), "questEventStageIndex")),
                  key=lambda r: M.as_int(r.get("questEventStageIndex"), "questEventStageIndex"))
    if not sura:
        fail("SuraDungeonStageTable carries no stages")
    stage_of = M.keyed(base.load_data("QuestEventStageTable")["rows"],
                       lambda r: M.as_int(r.get("questEventStageIndex"), "questEventStageIndex") or None)
    stages, evidence = [], {}
    for r in sura:
        qes = M.as_int(r.get("questEventStageIndex"), "questEventStageIndex")
        st = stage_of.get(qes)
        if st is None:
            fail("QuestEventStageTable has no row %d" % qes)
        if M.as_int(st.get("questEventIndex"), "questEventIndex") != SURA_QE:
            fail("stage %d belongs to questEvent %s, not %d" % (qes, st.get("questEventIndex"), SURA_QE))
        trig = st.get("singleTriggerName") or ""
        if not trig.startswith("Prefabs/EventSystem/Trigger/"):
            fail("stage %d carries no event trigger: %r" % (qes, trig))
        stages.append(st)
        evidence.setdefault(trig, []).append(qes)

    family = os.path.dirname(stages[0]["singleTriggerName"])     # .../Trigger/SuraDungeon
    bundle_name = family.replace("Prefabs/", "prefabs_", 1).replace("/", "_").lower()
    bundles = cached_bundles()
    path = bundle_of(bundles, bundle_name)
    if not path:
        fail("no cached bundle %s for the trigger family" % bundle_name)
    data, gos, mbs, trs, _info = U.index_bundle(path)
    graphs = {}
    for trig, _qess in sorted(evidence.items()):
        root_name = os.path.basename(trig)
        roots = [pid for pid, g in gos.items() if g["name"] == root_name]
        if len(roots) != 1:
            fail("trigger root %s: %d GameObjects in %s, expected exactly 1"
                 % (root_name, len(roots), bundle_name))
        _holders, monsters = U.graph_monsters(mbs, U.subtree_gameobjects(gos, trs, roots[0]))
        if not monsters:
            fail("trigger %s names no monster (empty graph?)" % root_name)
        graphs[root_name] = sorted(monsters)
    return stages, graphs, evidence, bundle_name, bundles


def main():
    global BUNDLES
    ap = argparse.ArgumentParser(description="stage the Sura enemy closure (never writes master tables)")
    ap.add_argument("src", help="kofas_server folder (with tabel/ and tabel_teks/)")
    ap.add_argument("--data", default=os.path.normpath(os.path.join(HERE, "..", "server", "tables", "data")),
                    help="project tables data dir to read (default: the server's)")
    ap.add_argument("--out", default=OUT_DEFAULT, help="staging dir to write (default: tools/out_sura_enemies)")
    ap.add_argument("--bundles", default=base.BUNDLES, help="client assetbundles cache dir")
    args = ap.parse_args()
    base.DATA, BUNDLES = args.data, args.bundles
    if not os.path.isdir(os.path.join(args.src, "tabel")):
        fail("usage: import_sura_enemies.py <kofas_server folder> [--data DIR] [--out DIR] [--bundles DIR]")
    schema = json.load(open(base.SCHEMA, encoding="utf-8"))

    stages, graphs, evidence, trig_bundle, bundles = stage_graphs()
    stage_by_qes = M.keyed(stages, lambda r: M.as_int(r.get("questEventStageIndex"),
                                                      "questEventStageIndex") or None)
    stage_monsters = {qes: graphs[os.path.basename(trig)]
                      for trig, qess in evidence.items() for qes in qess}
    bosses = sorted({M.as_int(r.get("monsterIndex"), "monsterIndex")
                     for r in base.load_data("SuraDungeonStageTable")["rows"] if r.get("monsterIndex")})
    wanted = sorted({m for ms in stage_monsters.values() for m in ms})

    fields = {}
    for table, _key in TABLES:
        if table not in schema["tables"]:
            fail("%s: not in schema.json" % table)
        if not os.path.isfile(os.path.join(args.src, "tabel", table + ".json")):
            fail("mobile source lacks tabel/%s.json" % table)
        fields[table] = base.fields_of(schema, table)

    mst_mon = M.dup_guard([r for r in base.load_data("MonsterTable")["rows"]
                           if r.get("monsterIndexString") in set(wanted)],
                          lambda r: r.get("monsterIndexString"), fields["MonsterTable"],
                          "MonsterTable (project)")
    ref_mon_all = base.mobile_rows(args.src, "MonsterTable")
    ref_mon = M.dup_guard([r for r in ref_mon_all if r.get("monsterIndexString") in set(wanted)],
                          lambda r: r.get("monsterIndexString"), fields["MonsterTable"],
                          "MonsterTable (mobile)")
    gap = [m for m in wanted if m not in mst_mon and m not in ref_mon]
    if gap:
        fail("graph monsters in neither the project tables nor the mobile source: %s" % gap)
    divergent = ["MonsterTable %s" % m for m in sorted(set(mst_mon) & set(ref_mon))
                 if not M.same_row(mst_mon[m], ref_mon[m], fields["MonsterTable"])]
    mon_add = [ref_mon[m] for m in wanted if m not in mst_mon]
    row_of = {m: mst_mon.get(m) or ref_mon[m] for m in wanted}
    for b in bosses:      # the api-side boss must resolve somewhere too (560004 is already present)
        if not [r for r in base.load_data("MonsterTable")["rows"] if r.get("monsterIndex") == b] \
                and not [r for r in ref_mon_all if r.get("monsterIndex") == b]:
            fail("stage boss monsterIndex %d in neither the project tables nor the mobile source" % b)

    skills = set()
    for r in row_of.values():
        skills |= M.skill_indexes(r)
    mst_skill = M.dup_guard([r for r in base.load_data("MonsterSkillTable")["rows"]
                             if r.get("monsterSkillIndex") in skills],
                            lambda r: r.get("monsterSkillIndex"), fields["MonsterSkillTable"],
                            "MonsterSkillTable (project)")
    ref_skill = M.dup_guard([r for r in base.mobile_rows(args.src, "MonsterSkillTable")
                             if r.get("monsterSkillIndex") in skills],
                            lambda r: r.get("monsterSkillIndex"), fields["MonsterSkillTable"],
                            "MonsterSkillTable (mobile)")
    gap = sorted(s for s in skills if s not in mst_skill and s not in ref_skill)
    if gap:
        fail("direct skills in neither the project tables nor the mobile source: %s" % gap)
    divergent += ["MonsterSkillTable %s" % s for s in sorted(set(mst_skill) & set(ref_skill))
                  if not M.same_row(mst_skill[s], ref_skill[s], fields["MonsterSkillTable"])]
    skill_add = [ref_skill[s] for s in sorted(skills) if s not in mst_skill]
    skill_string = {M.as_int(r.get("monsterSkillIndex"), "monsterSkillIndex"):
                    r.get("monsterSkillIndexString") or "" for r in list(mst_skill.values()) + list(ref_skill.values())}

    direct_of = {m: sorted({skill_string.get(s, "").rsplit("#", 1)[0]
                            for s in M.skill_indexes(r) if skill_string.get(s)})
                 for m, r in row_of.items()}
    needles = sorted({b for bases in direct_of.values() for b in bases})
    holders = needle_holders(bundles, needles)
    by_string = {r.get("monsterSkillIndexString"): r for r in base.mobile_rows(args.src, "MonsterSkillTable")}
    have_string = {r.get("monsterSkillIndexString") for r in base.load_data("MonsterSkillTable")["rows"]}
    chain_add, owners_map, orphans = [], {}, {}
    for name in wanted:
        bases = [b for b in direct_of[name]]
        if not M.skill_indexes(row_of[name]):
            continue                    # skill-less: SetSkillData never runs for it (the HoE rule)
        if not any(holders.get(b) for b in bases):
            fail("skill-carrying %s: no cached bundle carries its skills %s -- refusing to guess the chain"
                 % (name, bases))
        owners_map[name] = {b: holders[b] for b in bases}
        for bname in sorted({bn for b in bases for bn in holders[b]}):
            for s in base.bundle_skill_names(bundle_of(bundles, bname)):
                if s + "#1" in have_string:
                    continue
                if s + "#1" in by_string:
                    chain_add.append(by_string[s + "#1"])
                    have_string.add(s + "#1")
                else:
                    orphans.setdefault(s, name)
    chain_add = sorted(M.dup_guard(chain_add, lambda r: r.get("monsterSkillIndex"),
                                   fields["MonsterSkillTable"], "linked skills").values(),
                       key=lambda r: M.as_int(r.get("monsterSkillIndex"), "monsterSkillIndex"))

    need_growth = {M.as_int(r.get("growthType"), "growthType") for r in row_of.values()}
    growth_add, growth_types = [], {}
    for t in sorted(need_growth):
        src_rows = [r for r in base.mobile_rows(args.src, "MonsterGrowthTable")
                    if M.as_int(r.get("growthType"), "growthType") == t]
        have = {r.get("monsterGrowthIndex") for r in base.load_data("MonsterGrowthTable")["rows"]
                if M.as_int(r.get("growthType"), "growthType") == t}
        if not src_rows and not have:
            fail("MonsterGrowthTable: growthType %d in neither the project tables nor the mobile source" % t)
        growth_types[t] = {"project_rows": len(have), "source_rows": len(src_rows)}
        growth_add += [r for r in src_rows if r.get("monsterGrowthIndex") not in have]

    ltypes = {M.as_int(r.get("levelStatType"), "levelStatType") for r in row_of.values()}
    levels = {M.as_int(st.get("monsterLevel"), "monsterLevel") for st in stages if st.get("monsterLevel")}
    mst_lstat = {(M.as_int(r.get("levelStatType"), "levelStatType"),
                  M.as_int(r.get("monsterLevel"), "monsterLevel"))
                 for r in base.load_data("MonsterLevelStatTable")["rows"]}
    ref_lstat = {(M.as_int(r.get("levelStatType"), "levelStatType"),
                  M.as_int(r.get("monsterLevel"), "monsterLevel")): r
                 for r in base.mobile_rows(args.src, "MonsterLevelStatTable")}
    gap = sorted(p for p in {(t, l) for t in ltypes for l in levels}
                 if p not in mst_lstat and p not in ref_lstat)
    if gap:
        fail("MonsterLevelStatTable: (levelStatType, level) %s in neither place" % gap)
    lstat_add = [ref_lstat[p] for p in sorted({(t, l) for t in ltypes for l in levels} - mst_lstat)]

    akey = lambda r: ((M.as_int(r.get("aiGroup"), "aiGroup"), M.as_int(r.get("aiGrade"), "aiGrade"))
                      if r.get("aiGroup") is not None else None)
    need_ai = {(M.as_int(row_of[n].get("aiGroup"), "aiGroup"),
                M.as_int(stage_by_qes[qes].get("aiGrade"), "aiGrade"))
               for qes, names in stage_monsters.items() for n in names}
    mst_ai = {akey(r) for r in base.load_data("AiGroupTable")["rows"] if akey(r)}
    ref_ai = {akey(r): r for r in base.mobile_rows(args.src, "AiGroupTable") if akey(r)}
    gap = sorted(p for p in need_ai if p not in mst_ai and p not in ref_ai)
    if gap:
        fail("AiGroupTable: (aiGroup, aiGrade) %s in neither the project tables nor the mobile source" % gap)
    ai_add = [ref_ai[p] for p in sorted(need_ai - mst_ai)]

    # a monster's bundle carries its own direct skills too, so the direct and linked lists overlap:
    # every table's adds collapse to one row per primary key before writing -- identical duplicates
    # are tolerated, a key arriving twice with different schema-visible content aborts pre-write
    def dedup(table, key, rows):
        return sorted(M.dup_guard(rows, lambda r: r.get(key), fields[table],
                                  "%s additions" % table).values(),
                      key=lambda r: M.as_int(r.get(key), key))

    adds = {"MonsterTable": dedup("MonsterTable", "monsterIndex", mon_add),
            "MonsterSkillTable": dedup("MonsterSkillTable", "monsterSkillIndex",
                                       list(skill_add) + list(chain_add)),
            "MonsterGrowthTable": dedup("MonsterGrowthTable", "monsterGrowthIndex", growth_add),
            "MonsterLevelStatTable": dedup("MonsterLevelStatTable", "monsterLevelStatIndex", lstat_add),
            "AiGroupTable": dedup("AiGroupTable", "aiGroupIndex", ai_add)}
    for table, key in TABLES:
        have = M.keyed(base.load_data(table)["rows"], lambda r: r.get(key))
        for r in adds[table]:
            old = have.get(r.get(key))
            if old is not None and not M.same_row(old, r, fields[table]):
                fail("%s: %s %s already exists with different content -- refusing to append"
                     % (table, key, r.get(key)))

    strings = json.load(open(os.path.join(args.data, "strings_en.json"), encoding="utf-8"))
    texts = {}
    for t in ("MonsterTable", "MonsterSkillTable"):
        texts.update(base.mobile_texts(args.src, t))
    tags = {v for rows in adds.values() for r in rows for k, v in r.items()
            if k.endswith("Tag") and isinstance(v, str)}
    strings_add = {t: texts[t] for t in sorted(tags) if t in texts and t not in strings}
    no_text = sorted(t for t in tags if t not in strings and t not in texts)

    docs = [(t + ".additions.json",
             {"_comment": "rows to append to the project's server/tables/data/%s.json "
                          "(tools/import_sura_enemies.py)" % t, "rows": adds[t]})
            for t, _key in TABLES if adds[t]]
    if strings_add:
        docs.append(("strings_en.additions.json",
                     {"_comment": "entries to merge into the project's server/tables/data/strings_en.json "
                                  "(tools/import_sura_enemies.py)", "entries": strings_add}))
    if not docs:
        print("already applied: every Sura enemy closure row is in the project tables; nothing staged")
        return
    os.makedirs(args.out, exist_ok=True)
    for name, doc in docs:
        json.dump(doc, open(os.path.join(args.out, name), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    json.dump({"trigger_bundle": trig_bundle,
               "stages": {str(qes): {"trigger": os.path.basename(t), "monsters": ms}
                          for t, qess in sorted(evidence.items()) for qes in qess
                          for ms in [graphs[os.path.basename(t)]]},
               "monsters": {"wanted": wanted, "staged": [r.get("monsterIndex") for r in mon_add],
                            "bosses": bosses},
               "skill_bundles": owners_map, "orphans": sorted(orphans), "growth_types": growth_types,
               "divergent_project_rows_kept": divergent,
               "strings": {"added": strings_add, "no_text_anywhere": no_text},
               "apply": ["append each additions file to its table in server/tables/data",
                         "run tools/build_tables.py, then tools/make_tablepacks.py",
                         "restart the server and the game"],
               "source": os.path.abspath(args.src)},
              open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("graphs: %d triggers, %d stages, %d distinct monsters (%d rows staged) from %s"
          % (len(graphs), len(stage_monsters), len(wanted), len(mon_add), trig_bundle))
    print(" | ".join("%s +%d" % (t, len(adds[t])) for t, _k in TABLES))
    print("skill bundles: %d families, linked skills +%d, orphans %d"
          % (len(owners_map), len(chain_add), len(orphans)))
    if divergent:
        print("divergent keys kept from the project tables: %d (e.g. %s)" % (len(divergent), divergent[:5]))
    if no_text:
        print("strings: %d tags carry no text in any source and stay absent (first: %s)"
              % (len(no_text), no_text[:3]))
    print("staged %d file(s) + manifest.json in %s" % (len(docs), args.out))


if __name__ == "__main__":
    main()
