"""Restore the Tower of Illusion's 50 floors (QuestEvent 107) under collision-free stage ids.

The mobile reference numbers the tower's floors 10701..10750, but 10701..10720 are already the
Crucible Tower's floors 101..120 (QuestEvent 106) here, so a plain import can only ever bring
F21..F50. The PC client treats questEventStageIndex as an opaque key -- UIPage_PhantomTower
sorts floors by it (descending), labels floors from list positions and unlocks a floor when its
openValue equals the server's lastClearStageIndex; NetworkManagerWEB's Parse_PhantomTower* only
move the value around; stages resolve through BaseTableList.Find's exact-match search. No
consumer divides or decomposes the id, so the tower is renumbered to the contiguous block
1070001..1070050: F1 opens at 0, every later floor opens on the previous floor's new id, and the
Crucible's own rows (10601..10720) stay untouched. saves keep the legacy ids in phantom.last;
ext_phantom.py maps 10721..10750 -> 1070021..1070050 in memory when reading them.

Tables written (staged into --out; --apply copies them over server/tables/data after review,
then build_tables.py + make_tablepacks.py + a server restart make the client see them):
  QuestEventStageTable  the 30 rows 10721..10750 replaced by all 50 reference rows, ids and the
                        openValue chain remapped, every other field verbatim (spawn groups,
                        reward groups and balance indexes keep their original namespaces, none
                        of which collide with anything);
  StageBalanceTable     + 3900001..3900020 (PhantomBalance_1..20) verbatim;
  RewardGroupTable      + the first-clear rows of groups 94100001..94100020 verbatim.

Also writes phantom-tower-f20-dependencies.json next to the staged tables: the monster-side rows
the new F1..F20 floors need (spawn groups 10701..10720, 8 monsters, 12 skills, AiGroup 703
grades 1-2, their name tags). Those stay out of the master tables on purpose -- the monster
pipeline (tools/import_dungeons.py / import_dungeon_monsters.py) owns that side; the JSON is the
hand-off for whoever runs it.

usage: python restore_phantom_tower.py <kofas_server folder> [--data DIR] [--out DIR] [--apply]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "server", "tables", "data")
SCHEMA = os.path.join(HERE, "..", "server", "tables", "schema.json")
QE = 107
OLD_FIRST, OLD_LAST = 10721, 10750
NEW_FIRST, NEW_LAST = 1070001, 1070050
REF_FIRST, REF_LAST = 10701, 10750
F20 = 20
BALANCES = range(3900001, 3900021)
REWARDS = range(94100001, 94100021)
MONSTER_TABLES = ("MonsterSpawnTable", "MonsterTable", "MonsterSkillTable", "AiGroupTable")


def fields_of(schema, table):
    proto = schema["tables"][table]["proto"]
    return {f["name"].lstrip("_") for f in schema["protos"][proto]["fields"]}


def load_data(data, name):
    return json.load(open(os.path.join(data, name + ".json"), encoding="utf-8"))


def mobile_rows(src, table):
    path = os.path.join(src, "tabel", table + ".json")
    if not os.path.isfile(path):
        sys.exit(f"mobile source is missing {path}")
    return json.load(open(path, encoding="utf-8")).get("baris", [])


def schema_row(row, allowed):
    return {k: v for k, v in row.items() if k in allowed}


def stage_row(row, new_id, open_value, allowed):
    out = schema_row(row, allowed)
    out["questEventStageIndex"] = new_id
    out["openValue"] = open_value
    return out


def build_stages(schema, data, src):
    """The 50 reference rows renumbered onto 1070001..1070050, chain-consistent."""
    allowed = fields_of(schema, "QuestEventStageTable")
    ref = {int(r["questEventStageIndex"]): r
           for r in mobile_rows(src, "QuestEventStageTable")
           if int(r.get("questEventIndex") or 0) == QE}
    wanted = set(range(REF_FIRST, REF_LAST + 1))
    if set(ref) != wanted:
        sys.exit(f"mobile QuestEventStageTable: expected the {len(wanted)} floors "
                 f"{REF_FIRST}..{REF_LAST} of event {QE}, found {sorted(set(ref))}")
    rows = []
    for floor in range(1, 51):
        old = ref[REF_FIRST + floor - 1]
        if int(old.get("openValue") or 0) != (0 if floor == 1 else REF_FIRST + floor - 2):
            sys.exit(f"mobile floor {floor}: openValue {old.get('openValue')} breaks the "
                     "reference chain (floor 1 must be 0, later floors the previous id)")
        rows.append(stage_row(old, NEW_FIRST + floor - 1, 0 if floor == 1 else NEW_FIRST + floor - 2,
                              allowed))
    return rows


def preflight(schema, data, src, stages):
    doc = load_data(data, "QuestEventStageTable")
    qe = [int(r["questEventStageIndex"]) for r in doc["rows"]
          if int(r.get("questEventIndex") or 0) == QE]
    if set(qe) == set(range(NEW_FIRST, NEW_LAST + 1)):
        sys.exit(f"event {QE} already restored to {NEW_FIRST}..{NEW_LAST}: nothing to do")
    if set(qe) != set(range(OLD_FIRST, OLD_LAST + 1)):
        sys.exit(f"QuestEventStageTable: expected event {QE} as {OLD_FIRST}..{OLD_LAST} "
                 f"(the importable share of the reference), found {sorted(set(qe))}")
    crucible = {int(r["questEventStageIndex"]) for r in doc["rows"]
                if int(r.get("questEventIndex") or 0) == 106}
    if not crucible <= set(range(10601, OLD_FIRST)):
        sys.exit(f"QuestEventStageTable: Crucible rows outside 10601..10720: "
                 f"{sorted(crucible - set(range(10601, OLD_FIRST)))}")
    taken = {int(r["questEventStageIndex"]) for r in doc["rows"]}
    clash = taken & set(range(NEW_FIRST, NEW_LAST + 1))
    if clash:
        sys.exit(f"QuestEventStageTable: new ids already used by other events: {sorted(clash)}")
    for table, key, wanted in (("StageBalanceTable", "stageBalanceIndex", BALANCES),
                               ("RewardGroupTable", "rewardGroupIndex", [])):
        have = {r.get(key) for r in load_data(data, table)["rows"]}
        hit = have & set(wanted)
        if hit:
            sys.exit(f"{table}: {key}s already present: {sorted(hit)}")
    groups = {int(r["rewardGroup"]) for r in load_data(data, "RewardGroupTable")["rows"]}
    hit = groups & set(REWARDS)
    if hit:
        sys.exit(f"RewardGroupTable: rewardGroups already present: {sorted(hit)}")
    strings = json.load(open(os.path.join(data, "strings_en.json"), encoding="utf-8"))
    tags = {f"QuestEventStage.{kind}.{REF_FIRST + i}"
            for kind in ("Name", "Desc", "Floor") for i in range(50)}
    missing = sorted(t for t in tags if t not in strings)
    if missing:
        sys.exit(f"strings_en.json: floor tags missing (name tags are opaque dictionary keys, "
                 f"the client never rebuilds them from the id): {missing}")
    maps = {int(r["resourceMapIndex"]) for r in stages}
    have = {int(r["resourceMapIndex"]) for r in load_data(data, "ResourceMapTable")["rows"]}
    nowhere = sorted(maps - have
                     - {int(r["resourceMapIndex"]) for r in mobile_rows(src, "ResourceMapTable")})
    if nowhere:
        sys.exit(f"ResourceMapTable: maps used by the tower but in neither table set: {nowhere}")
    diffs = {int(r["difficultyType"]) for r in stages}
    have = {int(r["difficultyIndex"]) for r in load_data(data, "DifficultyTable")["rows"]}
    nowhere = sorted(diffs - have
                     - {int(r["difficultyIndex"]) for r in mobile_rows(src, "DifficultyTable")})
    if nowhere:
        sys.exit(f"DifficultyTable: difficulties used by the tower but nowhere to import from: "
                 f"{nowhere}")


def build_support(schema, data, src):
    balances = []
    allowed = fields_of(schema, "StageBalanceTable")
    have = {r.get("stageBalanceIndex") for r in load_data(data, "StageBalanceTable")["rows"]}
    for r in mobile_rows(src, "StageBalanceTable"):
        if r.get("stageBalanceIndex") in BALANCES and r["stageBalanceIndex"] not in have:
            balances.append(schema_row(r, allowed))
    rewards = []
    allowed = fields_of(schema, "RewardGroupTable")
    rows = load_data(data, "RewardGroupTable")["rows"]
    have_key = {r.get("rewardGroupIndex") for r in rows}
    have_group = {r.get("rewardGroup") for r in rows}
    for r in mobile_rows(src, "RewardGroupTable"):
        if (r.get("rewardGroup") in REWARDS and r.get("rewardGroup") not in have_group
                and r.get("rewardGroupIndex") not in have_key):
            rewards.append(schema_row(r, allowed))
    return balances, rewards


def build_dependencies(schema, data, src, stages):
    """Monster-side rows the F1..F20 floors need and the monster importer owns; preflighted
    against the current master (which already carries the F21..F50 closure) and its own keys."""
    allowed = {t: fields_of(schema, t) for t in MONSTER_TABLES}
    keys = {"MonsterSpawnTable": "monsterSpawnIndex", "MonsterTable": "monsterIndex",
            "MonsterSkillTable": "monsterSkillIndex", "AiGroupTable": "aiGroupIndex"}
    master = {t: {r.get(keys[t]): r for r in load_data(data, t)["rows"]
                  if r.get(keys[t]) is not None} for t in MONSTER_TABLES}
    mobile = {t: {r.get(keys[t]): r for r in mobile_rows(src, t) if r.get(keys[t]) is not None}
              for t in MONSTER_TABLES}

    spawns = [r for r in mobile["MonsterSpawnTable"].values()
              if r.get("monsterSpawnGroup") in range(REF_FIRST, REF_FIRST + F20)]
    monsters = sorted({int(r["monsterIndex"]) for r in spawns})
    skills = set()
    for m in monsters:
        for k, v in mobile["MonsterTable"][m].items():
            if k.startswith("skill") and k.endswith("Index") and v:
                skills.add(int(v))
    grades = {int(r["aiGrade"]) for r in stages if int(r["questEventStageIndex"]) <= NEW_FIRST + F20 - 1}
    groups = {int(mobile["MonsterTable"][m]["aiGroup"]) for m in monsters}
    ais = sorted(g * 100 + grade for g in groups for grade in grades)

    out = {}
    for table, wanted in (("MonsterSpawnTable", sorted({int(r["monsterSpawnIndex"]) for r in spawns})),
                          ("MonsterTable", monsters),
                          ("MonsterSkillTable", sorted(skills)),
                          ("AiGroupTable", ais)):
        missing = [i for i in wanted if i not in master[table] and i not in mobile[table]]
        if missing:
            sys.exit(f"{table}: rows needed by the new floors but in neither the project tables "
                     f"nor the mobile source: {missing}")
        rows = [schema_row(mobile[table][i], allowed[table])
                for i in wanted if i not in master[table]]
        out[table] = {"count": len(rows), "rows": rows}
    growth = {int(mobile["MonsterTable"][m].get("growthType") or 0) for m in monsters}
    have = {int(r.get("growthType") or 0) for r in load_data(data, "MonsterGrowthTable")["rows"]}
    if growth - have:
        sys.exit(f"MonsterGrowthTable: growthTypes used by the new monsters but missing: "
                 f"{sorted(growth - have)}")
    strings = json.load(open(os.path.join(data, "strings_en.json"), encoding="utf-8"))
    texts = json.load(open(os.path.join(src, "tabel_teks", "MonsterTable.json"),
                           encoding="utf-8")).get("teks", {})
    tags = sorted({mobile["MonsterTable"][m].get("monsterNameTag") for m in monsters
                   if mobile["MonsterTable"][m].get("monsterNameTag") not in strings})
    out["strings"] = {"count": len(tags),
                      "rows": [{ "tag": t, "text": texts.get(t, "")} for t in tags]}
    return out


def main():
    ap = argparse.ArgumentParser(description="Renumber QuestEvent 107 onto 1070001..1070050 "
                                             "and stage the table patches.")
    ap.add_argument("src", help="kofas_server folder of the mobile reference (tabel/ inside)")
    ap.add_argument("--data", default=DATA, help="master tables/data folder to read "
                                                 "(default: the project's)")
    ap.add_argument("--out", default=None, help="staging folder for the patched tables "
                                                "(default: <data>/../restore_phantom_tower_out)")
    ap.add_argument("--apply", action="store_true", help="copy the staged tables over --data "
                                                         "(the master tables); default is staging only")
    args = ap.parse_args()
    if not os.path.isdir(os.path.join(args.src, "tabel")):
        sys.exit("usage: restore_phantom_tower.py <kofas_server folder> [--data DIR] [--out DIR] [--apply]")
    data = os.path.abspath(args.data)
    out = os.path.abspath(args.out) if args.out else os.path.join(os.path.dirname(data.rstrip("/\\")),
                                                                 "restore_phantom_tower_out")
    os.makedirs(out, exist_ok=True)
    schema = json.load(open(SCHEMA, encoding="utf-8"))

    stages = build_stages(schema, data, args.src)
    preflight(schema, data, args.src, stages)
    balances, rewards = build_support(schema, data, args.src)
    deps = build_dependencies(schema, data, args.src, stages)

    doc = load_data(data, "QuestEventStageTable")
    first = next(i for i, r in enumerate(doc["rows"])
                 if int(r.get("questEventIndex") or 0) == QE)
    doc["rows"] = [r for r in doc["rows"] if int(r.get("questEventIndex") or 0) != QE]
    doc["rows"][first:first] = stages
    json.dump(doc, open(os.path.join(out, "QuestEventStageTable.json"), "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)

    doc = load_data(data, "StageBalanceTable")
    doc["rows"].extend(balances)
    json.dump(doc, open(os.path.join(out, "StageBalanceTable.json"), "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)

    doc = load_data(data, "RewardGroupTable")
    doc["rows"].extend(rewards)
    json.dump(doc, open(os.path.join(out, "RewardGroupTable.json"), "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)

    json.dump({"_readme": "Monster-side rows the Tower of Illusion floors F1-F20 need and the "
                          "monster importer (import_dungeons.py pipeline) owns; verbatim from the "
                          "mobile reference, schema-filtered, preflighted against the master "
                          "tables and its own keys. Static inventory, not a battle proof.",
               **deps},
              open(os.path.join(out, "phantom-tower-f20-dependencies.json"), "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)

    if args.apply:
        for name in ("QuestEventStageTable", "StageBalanceTable", "RewardGroupTable"):
            doc = json.load(open(os.path.join(out, name + ".json"), encoding="utf-8"))
            json.dump(doc, open(os.path.join(data, name + ".json"), "w", encoding="utf-8"),
                      indent=1, ensure_ascii=False)

    print(f"QuestEventStageTable: {OLD_FIRST}..{OLD_LAST} -> {NEW_FIRST}..{NEW_LAST} "
          f"({len(stages)} rows, chain 0/{NEW_FIRST}..{NEW_LAST - 1}) | "
          f"StageBalanceTable +{len(balances)} | RewardGroupTable +{len(rewards)} | "
          + " | ".join(f"{t} +{v['count']}" for t, v in deps.items()))
    print(f"staged in {out}" + (" | APPLIED to " + data if args.apply else
                                " (not applied; review, then --apply, build_tables.py, "
                                "make_tablepacks.py, restart server+game)"))


if __name__ == "__main__":
    main()
