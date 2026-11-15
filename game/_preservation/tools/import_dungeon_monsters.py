"""Import the monster closure of the challenge dungeons the project tables already carry:
Tower of Illusion (questEvent 107, every stage present that day) and Sura Dungeon (10801).

Chain (same semantics tools/import_dungeons.py established): each questEvent 107 stage's
monsterSpawnGroup -> MonsterSpawnTable rows -> monsterIndex; Sura stages spawn no group -- the
boss comes from SuraDungeonStageTable.monsterIndex of its SuraDungeonDifficultyTable row
(questEventIndex 10801), and each Sura row's questEventStageIndex must belong to questEvent
10801 itself, not merely exist. Every involved monster then needs its skillNIndex rows in
MonsterSkillTable, every row of its growthType in MonsterGrowthTable (the whole type set must
exist -- for growthType 100 the grade column mirrors monsterType, so grade/monsterType variants
travel with the type; same rule as import_hoe_monsters), its (levelStatType, level) rows in
MonsterLevelStatTable for every level the stages and spawn rows use, and its AiGroupTable row at
each spawning stage's aiGrade (AiGroupTable.Find reads the stage's own _aiGrade --
QuestEventStageProto 0x100, see append_player_ai_grades). The whole closure is recalculated from
the project tables plus the mobile source (kofas_server/server/tabel "baris") on every run;
nothing here is a snapshot.

Preflight guards, all before any write (an aborted run leaves the data dir untouched):
- every questEvent 107 spawn group must carry at least one MonsterSpawnTable row in the project
  tables or the mobile source;
- integers are strict: absent/None counts as 0 by protocol, real ints and integer-valued strings
  pass, anything else (float, bool, garbage text) aborts naming the value -- never a silent 0 or
  truncation;
- a consumed collection carrying two different rows under the same key aborts as a conflicting
  duplicate (identical duplicates are tolerated, first row wins);
- a planned row whose key already exists with different content aborts as a collision;
- a referenced id that is in neither place aborts listing the gap. No default is ever invented.

The project's own row always wins the closure when both sides carry the same key: skills,
growth, level stats and AI are read from the PC row, the mobile row is never merged over it, and
divergences on schema fields are logged (PC kept, mobile row reported) rather than overwritten.

Real tag texts come in via strings_add; tags with no text in any source stay absent and are only
reported (the project's MonsterSkillTable nameTags have never had texts anywhere; monster names
do).

Coverage is whatever the project tables carry on the day the tool runs: the closure is derived
from the current questEvent 107 stage rows (count and questEventStageIndex/monsterSpawnGroup
ranges are printed each run), so the legacy 30-floor layout and the remapped 50-floor one both
work with no rule of their own. History: the project first carried only floors 21-50 because
questEventStageIndex 10701-10720 collided with the Crucible daily (questEvent 106); the
coordinator's later remap moved all 50 floors to questEventStageIndex 1070001-1070050 (spawn
groups kept the mobile ids 10701-10750, so both ranges are expected in MonsterSpawnTable).

usage: import_dungeon_monsters.py <kofas_server folder> [--data DIR]
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import import_dungeons as base  # one merge semantics: fields_of/load_data/save_data/merge/strings_add


TOWER_QE = 107
SURA_QE = 10801


def fail(msg):
    sys.exit(f"import_dungeon_monsters: {msg}")


def as_int(value, field):
    """Protocol integer: absent/None counts as 0; real ints and integer strings pass; anything
    else (float, bool, garbage) is a named preflight error, never a silent 0 or truncation."""
    if value is None:
        return 0
    if isinstance(value, bool):
        fail(f"{field}: {value!r} is not an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        return int(value.strip())
    fail(f"{field}: {value!r} is not an integer (absent/None counts as 0)")


def keyed(rows, fn):
    out = {}
    for r in rows:
        k = fn(r)
        if k is not None:
            out.setdefault(k, r)
    return out


def dup_guard(rows, fn, allowed, label):
    """Index `rows` by fn, aborting when two different rows share a key (identical duplicates
    are tolerated, first row wins) -- a consumed collection must not hide conflicting keys."""
    out = {}
    for r in rows:
        k = fn(r)
        if k is None:
            continue
        if k in out and not same_row(out[k], r, allowed):
            fail(f"{label}: duplicate key {k!r} with different content")
        out.setdefault(k, r)
    return out


def skill_indexes(row):
    return {as_int(v, k) for k, v in row.items() if re.fullmatch(r"skill\d+Index", k) and v}


def same_row(a, b, allowed):
    """Equal for import purposes: a field one side omits counts as the other's explicit default."""
    for f in allowed:
        av, bv = a.get(f), b.get(f)
        if av == bv:
            continue
        if (av is None and bv in (0, "", 0.0)) or (bv is None and av in (0, "", 0.0)):
            continue
        return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("src", help="kofas_server folder (with tabel/ and tabel_teks/)")
    parser.add_argument("--data", default=os.path.normpath(os.path.join(HERE, "..", "server",
                                                                        "tables", "data")),
                        help="tables data dir to update (default: the project's)")
    args = parser.parse_args()
    src, data = args.src, args.data
    if not os.path.isdir(os.path.join(src, "tabel")):
        fail(f"{src} has no tabel/ -- usage: import_dungeon_monsters.py <kofas_server folder> [--data DIR]")
    if not os.path.isfile(os.path.join(data, "QuestEventStageTable.json")):
        fail(f"{data} carries no QuestEventStageTable.json")
    schema = json.load(open(base.SCHEMA, encoding="utf-8"))
    base.DATA = data  # every helper reads it per call, so temp copies are fully supported

    consumed = ("MonsterSpawnTable", "MonsterTable", "MonsterSkillTable", "MonsterGrowthTable",
                "MonsterLevelStatTable", "AiGroupTable")
    fields = {}
    for table in consumed:
        if table not in schema["tables"]:
            fail(f"{table}: not in schema.json")
        if not os.path.isfile(os.path.join(src, "tabel", table + ".json")):
            fail(f"mobile source lacks tabel/{table}.json")
        fields[table] = base.fields_of(schema, table)

    stages = base.load_data("QuestEventStageTable")["rows"]
    stage_fields = base.fields_of(schema, "QuestEventStageTable")
    stage_of = keyed(stages, lambda r: as_int(r.get("questEventStageIndex"),
                                              "questEventStageIndex") or None)
    tower = [r for r in stages if as_int(r.get("questEventIndex"), "questEventIndex") == TOWER_QE]
    if not tower:
        fail("QuestEventStageTable: no questEvent 107 stages in the project tables today")
    dup_guard(tower, lambda r: r.get("questEventStageIndex"), stage_fields,
              "QuestEventStageTable questEvent 107 (project)")
    groups = sorted({as_int(r.get("monsterSpawnGroup"), "monsterSpawnGroup")
                     for r in tower if r.get("monsterSpawnGroup")})
    bare = [r.get("questEventStageIndex") for r in tower if not r.get("monsterSpawnGroup")]
    if bare:
        fail(f"questEvent 107 stages without monsterSpawnGroup (would spawn nothing): {bare}")

    sura_fields = base.fields_of(schema, "SuraDungeonStageTable")
    sura_diff_rows = base.load_data("SuraDungeonDifficultyTable")["rows"]
    sura_rows = [r for r in base.load_data("SuraDungeonStageTable")["rows"]
                 if as_int(r.get("suraDungeonDifficultyIndex"), "suraDungeonDifficultyIndex")
                 in {as_int(r.get("suraDungeonDifficultyIndex"), "suraDungeonDifficultyIndex")
                     for r in sura_diff_rows
                     if as_int(r.get("questEventIndex"), "questEventIndex") == SURA_QE}]
    if not sura_rows:
        fail("SuraDungeonDifficultyTable/SuraDungeonStageTable: no questEvent 10801 rows "
             "in the project tables")
    dup_guard(sura_rows, lambda r: r.get("suraDungeonStageIndex"), sura_fields,
              "SuraDungeonStageTable questEvent 10801 (project)")
    lost = sorted({as_int(r.get("questEventStageIndex"), "questEventStageIndex")
                   for r in sura_rows} - set(stage_of))
    if lost:
        fail(f"Sura rows point at stages missing from QuestEventStageTable: {lost}")
    wrong = sorted({as_int(r.get("questEventStageIndex"), "questEventStageIndex") for r in sura_rows
                    if as_int(stage_of[as_int(r.get("questEventStageIndex"),
                                              "questEventStageIndex")].get("questEventIndex"),
                              "questEventIndex") != SURA_QE})
    if wrong:
        fail(f"Sura rows point at stages of another questEvent (must be {SURA_QE}): {wrong}")
    sura_bosses = sorted({as_int(r.get("monsterIndex"), "monsterIndex")
                          for r in sura_rows if r.get("monsterIndex")})
    sura_stages = [stage_of[as_int(r.get("questEventStageIndex"), "questEventStageIndex")]
                   for r in sura_rows]

    wanted = set(groups)
    mst_spawn_rows = [r for r in base.load_data("MonsterSpawnTable")["rows"]
                      if as_int(r.get("monsterSpawnGroup"), "monsterSpawnGroup") in wanted]
    ref_spawn_rows = [r for r in base.mobile_rows(src, "MonsterSpawnTable")
                      if as_int(r.get("monsterSpawnGroup"), "monsterSpawnGroup") in wanted]
    if not ref_spawn_rows and not mst_spawn_rows:
        fail(f"MonsterSpawnTable: mobile source and project carry no rows for spawn groups {groups}")
    spawn_fields = fields["MonsterSpawnTable"]
    mst_spawn = dup_guard(mst_spawn_rows, lambda r: r.get("monsterSpawnIndex"), spawn_fields,
                          "MonsterSpawnTable spawn groups (project)")
    ref_spawn = dup_guard(ref_spawn_rows, lambda r: r.get("monsterSpawnIndex"), spawn_fields,
                          "MonsterSpawnTable spawn groups (mobile)")
    group_rows = {g: [] for g in groups}
    for r in mst_spawn_rows:
        group_rows[as_int(r.get("monsterSpawnGroup"), "monsterSpawnGroup")].append(r)
    spawn_add = []
    for r in ref_spawn_rows:
        rows = group_rows[as_int(r.get("monsterSpawnGroup"), "monsterSpawnGroup")]
        if r.get("monsterSpawnIndex") in {x.get("monsterSpawnIndex") for x in rows}:
            continue
        rows.append(r)
        spawn_add.append(r)
    empty = [g for g in groups if not group_rows[g]]
    if empty:
        fail(f"MonsterSpawnTable: questEvent 107 spawn groups with no rows in the project tables "
             f"or the mobile source: {empty}")

    divergent = []

    def note_divergences(label, pc, ref, allowed):
        """PC rows win the closure and are never overwritten; both-sides keys with different
        schema-visible content are only logged."""
        for k in sorted(pc.keys() & ref.keys(), key=str):
            if not same_row(pc[k], ref[k], allowed):
                divergent.append(f"{label} {k}")

    note_divergences("MonsterSpawnTable", mst_spawn, ref_spawn, spawn_fields)

    mon_ids = sorted({as_int(r.get("monsterIndex"), "monsterIndex")
                      for rows in group_rows.values() for r in rows
                      if r.get("monsterIndex") is not None} | set(sura_bosses))
    mon_fields = fields["MonsterTable"]
    mon_set = set(mon_ids)
    mst_mon = dup_guard([r for r in base.load_data("MonsterTable")["rows"]
                         if r.get("monsterIndex") in mon_set],
                        lambda r: r.get("monsterIndex"), mon_fields, "MonsterTable (project)")
    ref_mon = dup_guard([r for r in base.mobile_rows(src, "MonsterTable")
                         if r.get("monsterIndex") in mon_set],
                        lambda r: r.get("monsterIndex"), mon_fields, "MonsterTable (mobile)")
    gap = [m for m in mon_ids if m not in mst_mon and m not in ref_mon]
    if gap:
        fail(f"MonsterTable: monsterIndex in neither the project tables nor the mobile source: {gap}")
    note_divergences("MonsterTable", mst_mon, ref_mon, mon_fields)
    mon_add = [ref_mon[m] for m in mon_ids if m not in mst_mon]
    row_of = {m: mst_mon.get(m) or ref_mon[m] for m in mon_ids}  # the PC profile always wins

    skills = set()
    for r in row_of.values():
        skills |= skill_indexes(r)
    skill_fields = fields["MonsterSkillTable"]
    skill_set = set(skills)
    mst_skill = dup_guard([r for r in base.load_data("MonsterSkillTable")["rows"]
                           if r.get("monsterSkillIndex") in skill_set],
                          lambda r: r.get("monsterSkillIndex"), skill_fields,
                          "MonsterSkillTable (project)")
    ref_skill = dup_guard([r for r in base.mobile_rows(src, "MonsterSkillTable")
                           if r.get("monsterSkillIndex") in skill_set],
                          lambda r: r.get("monsterSkillIndex"), skill_fields,
                          "MonsterSkillTable (mobile)")
    gap = sorted(s for s in skills if s not in mst_skill and s not in ref_skill)
    if gap:
        fail(f"MonsterSkillTable: skill ids in neither the project tables nor the mobile source: {gap}")
    note_divergences("MonsterSkillTable", mst_skill, ref_skill, skill_fields)
    skill_add = [ref_skill[s] for s in sorted(skills) if s not in mst_skill]

    def group_monsters(st):
        return [as_int(r.get("monsterIndex"), "monsterIndex")
                for r in group_rows[as_int(st.get("monsterSpawnGroup"), "monsterSpawnGroup")]
                if as_int(r.get("monsterIndex"), "monsterIndex") in row_of]

    need_growth = {as_int(r.get("growthType"), "growthType") for r in row_of.values()}
    growth_fields = fields["MonsterGrowthTable"]
    mst_growth_rows = [r for r in base.load_data("MonsterGrowthTable")["rows"]
                       if as_int(r.get("growthType"), "growthType") in need_growth]
    ref_growth_rows = [r for r in base.mobile_rows(src, "MonsterGrowthTable")
                       if as_int(r.get("growthType"), "growthType") in need_growth]
    mst_growth = dup_guard(mst_growth_rows, lambda r: r.get("monsterGrowthIndex"), growth_fields,
                           "MonsterGrowthTable (project)")
    ref_growth = dup_guard(ref_growth_rows, lambda r: r.get("monsterGrowthIndex"), growth_fields,
                           "MonsterGrowthTable (mobile)")
    note_divergences("MonsterGrowthTable", mst_growth, ref_growth, growth_fields)
    have_types = ({as_int(r.get("growthType"), "growthType") for r in mst_growth_rows}
                  | {as_int(r.get("growthType"), "growthType") for r in ref_growth_rows})
    gap = sorted(need_growth - have_types)
    if gap:
        fail(f"MonsterGrowthTable: growthType {gap} in neither the project tables nor the mobile source")
    growth_add = [r for r in ref_growth_rows if r.get("monsterGrowthIndex") not in mst_growth]

    ltypes = {as_int(r.get("levelStatType"), "levelStatType") for r in row_of.values()}
    levels = ({as_int(st.get("monsterLevel"), "monsterLevel")
               for st in tower + sura_stages if st.get("monsterLevel")}
              | {as_int(r.get("monsterLevel"), "monsterLevel")
                 for rows in group_rows.values() for r in rows if r.get("monsterLevel")})
    lstat_fields = fields["MonsterLevelStatTable"]
    lkey = lambda r: ((as_int(r.get("levelStatType"), "levelStatType"),
                       as_int(r.get("monsterLevel"), "monsterLevel"))
                      if r.get("levelStatType") is not None else None)
    mst_lstat_rows = [r for r in base.load_data("MonsterLevelStatTable")["rows"]
                      if lkey(r) and lkey(r)[0] in ltypes]
    ref_lstat_rows = [r for r in base.mobile_rows(src, "MonsterLevelStatTable")
                      if lkey(r) and lkey(r)[0] in ltypes]
    mst_lstat = dup_guard(mst_lstat_rows, lkey, lstat_fields, "MonsterLevelStatTable (project)")
    ref_lstat = dup_guard(ref_lstat_rows, lkey, lstat_fields, "MonsterLevelStatTable (mobile)")
    note_divergences("MonsterLevelStatTable", mst_lstat, ref_lstat, lstat_fields)
    need_lstat = {(t, l) for t in ltypes for l in levels}
    gap = sorted(p for p in need_lstat if p not in mst_lstat and p not in ref_lstat)
    if gap:
        fail(f"MonsterLevelStatTable: (levelStatType, level) {gap} in neither place")
    lstat_add = [r for r in ref_lstat_rows if lkey(r) in need_lstat and lkey(r) not in mst_lstat]

    need_ai = set()
    for st in tower:
        for m in group_monsters(st):
            need_ai.add((as_int(row_of[m].get("aiGroup"), "aiGroup"),
                         as_int(st.get("aiGrade"), "aiGrade")))
    for st in sura_stages:
        for m in sura_bosses:
            need_ai.add((as_int(row_of[m].get("aiGroup"), "aiGroup"),
                         as_int(st.get("aiGrade"), "aiGrade")))
    akey = lambda r: ((as_int(r.get("aiGroup"), "aiGroup"), as_int(r.get("aiGrade"), "aiGrade"))
                      if r.get("aiGroup") is not None else None)
    ai_fields = fields["AiGroupTable"]
    mst_ai_rows = [r for r in base.load_data("AiGroupTable")["rows"] if akey(r) in need_ai]
    ref_ai_rows = [r for r in base.mobile_rows(src, "AiGroupTable") if akey(r) in need_ai]
    mst_ai = dup_guard(mst_ai_rows, akey, ai_fields, "AiGroupTable (project)")
    ref_ai = dup_guard(ref_ai_rows, akey, ai_fields, "AiGroupTable (mobile)")
    note_divergences("AiGroupTable", mst_ai, ref_ai, ai_fields)
    gap = sorted(p for p in need_ai if p not in mst_ai and p not in ref_ai)
    if gap:
        fail(f"AiGroupTable: (aiGroup, aiGrade) {gap} in neither the project tables "
             f"nor the mobile source")
    ai_add = [r for r in ref_ai_rows if akey(r) in need_ai and akey(r) not in mst_ai]

    for table, key_field, rows_add in (
            ("MonsterSpawnTable", "monsterSpawnIndex", spawn_add),
            ("MonsterTable", "monsterIndex", mon_add),
            ("MonsterSkillTable", "monsterSkillIndex", skill_add),
            ("MonsterGrowthTable", "monsterGrowthIndex", growth_add),
            ("MonsterLevelStatTable", "monsterLevelStatIndex", lstat_add),
            ("AiGroupTable", "aiGroupIndex", ai_add)):
        have = keyed(base.load_data(table)["rows"], lambda r: r.get(key_field))
        for r in rows_add:
            old = have.get(r.get(key_field))
            if old is not None and not same_row(old, r, fields[table]):
                fail(f"{table}: {key_field} {r.get(key_field)} already exists with different "
                     f"content -- refusing to append")

    strings = json.load(open(os.path.join(data, "strings_en.json"), encoding="utf-8"))
    texts = {}
    for t in ("MonsterTable", "MonsterSkillTable"):
        texts.update(base.mobile_texts(src, t))
    tags = {v for rows_add in (spawn_add, mon_add, skill_add, growth_add, lstat_add, ai_add)
            for r in rows_add for k, v in r.items() if k.endswith("Tag") and isinstance(v, str)}
    no_text = sorted(t for t in tags if t not in strings and t not in texts)

    counts = {table: len(base.merge(schema, table, rows_add, key_field, src,
                                    ["MonsterTable"] if table == "MonsterTable"
                                    else ["MonsterSkillTable"] if table == "MonsterSkillTable" else []))
              for table, key_field, rows_add in (
                  ("MonsterSpawnTable", "monsterSpawnIndex", spawn_add),
                  ("MonsterTable", "monsterIndex", mon_add),
                  ("MonsterSkillTable", "monsterSkillIndex", skill_add),
                  ("MonsterGrowthTable", "monsterGrowthIndex", growth_add),
                  ("MonsterLevelStatTable", "monsterLevelStatIndex", lstat_add),
                  ("AiGroupTable", "aiGroupIndex", ai_add))}
    print(" | ".join(f"{t} +{n}" for t, n in counts.items()))
    if divergent:
        print(f"divergent keys kept from the project tables, mobile row not merged over it: "
              f"{len(divergent)} (e.g. {divergent[:5]})")
    if no_text:
        print(f"strings: {len(no_text)} tags carry no text in any source and stay absent, "
              f"like the project's other MonsterSkillTable rows (first: {no_text[:3]})")
    stage_idx = sorted(as_int(r.get("questEventStageIndex"), "questEventStageIndex") for r in tower)
    print(f"questEvent 107 coverage detected in the project tables: {len(tower)} stages "
          f"(questEventStageIndex {stage_idx[0]}..{stage_idx[-1]}), {len(groups)} spawn groups "
          f"({groups[0]}..{groups[-1]})")


if __name__ == "__main__":
    main()
