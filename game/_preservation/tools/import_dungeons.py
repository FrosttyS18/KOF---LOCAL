"""Import QuestEvent-driven dungeon data from the community mobile server (kofas_server/server/tabel
+ tabel_teks, Indonesian offline APK) into this project's rebuilt tables.

Two sets, all from the real mobile tables:
  Transcendence (default questEventIndex list): Hall of Elements 41001-41005 + Advent 42001-42006 --
    their QuestEventTable / QuestEventStageTable / QuestEventScheduleTable rows.
  Challenge (always): Tower of Illusion 107, Buff Select Dungeon 8101, Sura Dungeon 10801, Prove
    Dungeon 10901 -- their QuestEvent rows and stages, the systems' own tables (Challenge*Table,
    SuraDungeon*Table, ProveDungeon*Table, BuffSelectDungeon*Table) wholesale, and the ModeTable /
    ContentsUnlockTable / ContentsAdmissionTable rows that add the menu buttons.

Plus the closure of everything those rows reference: RewardGroupTable groups, StageMissionTable rows,
RewardDisplayTable groups, ItemTable rows paid by type-13 rewards, the ResourceMapTable maps,
StageBalanceTable balances and DifficultyTable rows the stages load (the PC's Time Attack also asks
DifficultyTable.GetDifficultyRange for hardcoded modeIndex 202), and the name/description strings.
The Hall of Elements trigger graphs also require every HighComedown monster -- the five Flame Walker
bosses plus the ten mob/elite wave monsters their graphs spawn first (the live GraphOwner dump showed
NODE 7 creating Pierrena/Ryo waves before NODE 9's boss; boss-only v1015 left the arena empty) -- and
their monster skills, growth curves, level stats and AI groups from the mobile reference.
Existing rows are never touched; only appended -- the sole exception: adapt_triggers_to_pc renames
questEvent 41001's singleTriggerName to the PC bundle's real asset name. Fields follow
server/tables/schema.json.

usage: import_dungeons.py <kofas_server folder> [questEventIndex ...]
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "server", "tables", "data")
SCHEMA = os.path.join(HERE, "..", "server", "tables", "schema.json")
DEFAULT_QES = [41001, 41002, 41003, 41004, 41005, 42001, 42002, 42003, 42004, 42005, 42006]
CHALLENGE_QES = [107, 8101, 10801, 10901]
DEDICATED = {  # table -> its primary key (all present in the PC schema)
    "ChallengeScheduleTable": "challengeScheduleIndex",
    "ChallengeStageTable": "challengeStageIndex",
    "ChallengeScoreTable": "challengeScoreIndex",
    "ChallengeEntryTable": "challengeEntryIndex",
    "SuraDungeonStageTable": "suraDungeonStageIndex",
    "SuraDungeonDifficultyTable": "suraDungeonDifficultyIndex",
    "ProveDungeonStageTable": "proveDungeonStageIndex",
    "ProveDungeonRandomBossTable": "randomBossIndex",
    "ProveDungeonBossTeamTable": "bossTeamIndex",
    "BuffSelectDungeonStageTable": "stageIndex",
    "BuffSelectDungeonBuffTable": "dungeonBuffIndex",
    "EventPageTable": "eventPageIndex",
    "EventPageMissionGroupTable": "eventPageMissionGroupIndex",
}
MENU = {  # merged into the project's own rows (the dungeon buttons read ModeTable)
    "ModeTable": "modeIndex",
    "ContentsUnlockTable": "contentsUnlockIndex",
    "ContentsAdmissionTable": "contentsAdmissionIndex",
}


def fields_of(schema, table):
    proto = schema["tables"][table]["proto"]
    return {f["name"].lstrip("_") for f in schema["protos"][proto]["fields"]}


def load_data(name):
    path = os.path.join(DATA, name + ".json")
    if not os.path.exists(path):
        return {"_comment": "real mobile table (tools/import_dungeons.py)", "rows": []}
    return json.load(open(path, encoding="utf-8"))


def save_data(name, doc):
    json.dump(doc, open(os.path.join(DATA, name + ".json"), "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)


def mobile_rows(src, table):
    path = os.path.join(src, "tabel", table + ".json")
    if not os.path.isfile(path):
        return []
    return json.load(open(path, encoding="utf-8")).get("baris", [])


def mobile_texts(src, table):
    path = os.path.join(src, "tabel_teks", table + ".json")
    if not os.path.isfile(path):
        return {}
    return json.load(open(path, encoding="utf-8")).get("teks", {})


def merge(schema, table, rows, key, src, text_tables):
    """Append mobile `rows` (filtered to schema fields) whose `key` is new; report and collect strings."""
    if table not in schema["tables"] or not rows:
        return []
    allowed = fields_of(schema, table)
    doc = load_data(table)
    have = {r.get(key) for r in doc["rows"]}
    add, tags = [], set()
    for r in rows:
        if r.get(key) is None:
            continue
        tags |= {v for k, v in r.items() if k.endswith("Tag") and isinstance(v, str)}
        if r.get(key) in have:
            continue
        have.add(r.get(key))
        add.append({k: v for k, v in r.items() if k in allowed})
    if add:
        doc["rows"].extend(add)
        save_data(table, doc)
    strings_add(src, text_tables + ["SystemTable"], tags)
    return add


def strings_add(src, text_tables, tags):
    if not tags:
        return 0
    strings = json.load(open(os.path.join(DATA, "strings_en.json"), encoding="utf-8"))
    texts = {}
    for t in text_tables:
        texts.update(mobile_texts(src, t))
    add = {tag: texts[tag] for tag in tags if tag in texts and tag not in strings}
    if add:
        strings.update(add)
        json.dump(strings, open(os.path.join(DATA, "strings_en.json"), "w", encoding="utf-8"),
                  indent=1, ensure_ascii=False)
    return len(add)


PC_TRIGGER_RENAME = {
    "Prefabs/EventSystem/Trigger/Comedown/HighComedown/comedown_flame_walker_violet":
        "Prefabs/EventSystem/Trigger/Comedown/HighComedown/comedown_flame_walker_purple",
}


def adapt_triggers_to_pc():
    """The PC trigger bundle (md5 6af2d750a50492afb4a048f65fb10639) ships
    comedown_flame_walker_purple.prefab and no violet asset, so the mobile rows' violet trigger
    hangs every load behind it (live-proven: the DATA DOWNLOAD modal's stuck coroutine asked for
    exactly that name). Renames questEvent 41001's trigger in place -- new and already-imported
    rows alike: the sole append-only exception."""
    doc = load_data("QuestEventStageTable")
    renamed = 0
    for row in doc["rows"]:
        if (int(row.get("questEventIndex") or 0) == 41001
                and row.get("singleTriggerName") in PC_TRIGGER_RENAME):
            row["singleTriggerName"] = PC_TRIGGER_RENAME[row["singleTriggerName"]]
            renamed += 1
    if renamed:
        save_data("QuestEventStageTable", doc)
    return renamed


def import_hoe_monsters(schema, src):
    """Import every monster named by the PC HighComedown trigger graphs (5 Flame Walker bosses + the
    10 mob/elite wave monsters their graphs spawn before each boss) and their table dependencies.
    All skillNIndex references resolve in MonsterSkillTable; SkillTable is never touched."""
    monsters = [r for r in mobile_rows(src, "MonsterTable")
                if str(r.get("monsterIndexString", "")).startswith("Monster.")
                and str(r.get("monsterIndexString", "")).endswith(".HighComedown")]
    if len(monsters) != 15:
        raise ValueError(f"Hall of Elements: expected fifteen HighComedown monster rows, found {len(monsters)}")
    skills = {int(v) for r in monsters for k, v in r.items()
              if re.fullmatch(r"skill\d+Index", k) and v}
    plans = []
    for table, key, field, wanted in (
            ("MonsterSkillTable", "monsterSkillIndex", "monsterSkillIndex", skills),
            ("MonsterGrowthTable", "monsterGrowthIndex", "growthType",
             {int(r["growthType"]) for r in monsters}),
            ("MonsterLevelStatTable", "monsterLevelStatIndex", "levelStatType",
             {int(r["levelStatType"]) for r in monsters}),
            ("AiGroupTable", "aiGroupIndex", "aiGroup", {int(r["aiGroup"]) for r in monsters})):
        rows = [r for r in mobile_rows(src, table) if int(r.get(field) or 0) in wanted]
        available = {int(r.get(field) or 0) for r in rows + load_data(table)["rows"]}
        missing = wanted - available
        if missing:
            raise ValueError(f"{table}: Hall of Elements references missing {field}: {sorted(missing)}")
        plans.append((table, key, rows))
    counts = {table: len(merge(schema, table, rows, key, src, [table]))
              for table, key, rows in plans}
    counts["MonsterTable"] = len(merge(schema, "MonsterTable", monsters, "monsterIndex", src,
                                      ["MonsterTable"]))
    return counts


UI_TERMS = ("buffselect", "sura", "prove", "timeattack", "phantom", "challenge", "transcend", "comedown",
            "marathon", "hallofelements", "adventure.come", "questevententrycount")


def placeholder(tag):
    """build_tables.placeholder: the derived text the last build gave a tag with no real string."""
    parts = tag.split(".")[1:]
    if parts and parts[-1] in ("Name", "Desc", "Msg", "Text"):
        parts = parts[:-1]
    if len(parts) == 2 and parts[0] == "TopMenuText":
        return re.sub(r"(?<=[a-zA-Z])(?=[A-Z][a-z])", " ", parts[1])
    return " ".join(parts) or tag


def ui_strings(src):
    """The dungeons' UI texts (System.* of the mobile SystemTable): added when missing, and replacing
    the placeholders the last build derived for them (a placeholder would show as the raw tag words,
    e.g. the login popup's 'BuffSelectDungeon Title SeasonInformation')."""
    texts = mobile_texts(src, "SystemTable")
    keys = {k for k in texts if any(t in k.lower() for t in UI_TERMS)}
    strings = json.load(open(os.path.join(DATA, "strings_en.json"), encoding="utf-8"))
    add = {k: v for k, v in texts.items() if k in keys and (k not in strings or strings[k] == placeholder(k))}
    strings.update(add)
    json.dump(strings, open(os.path.join(DATA, "strings_en.json"), "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)
    return len(add)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else ""
    qes = [int(a) for a in sys.argv[2:]] or DEFAULT_QES
    if not os.path.isdir(os.path.join(src, "tabel")):
        sys.exit("usage: import_dungeons.py <kofas_server folder> [questEventIndex ...]")
    schema = json.load(open(SCHEMA, encoding="utf-8"))
    todo = qes + CHALLENGE_QES

    events = merge(schema, "QuestEventTable",
                   [r for r in mobile_rows(src, "QuestEventTable")
                    if int(r.get("questEventIndex") or 0) in todo],
                   "questEventIndex", src, ["QuestEventTable"])
    stages = merge(schema, "QuestEventStageTable",
                   [r for r in mobile_rows(src, "QuestEventStageTable")
                    if int(r.get("questEventIndex") or 0) in todo],
                   "questEventStageIndex", src, ["QuestEventStageTable"])
    renamed = adapt_triggers_to_pc()
    hoe = import_hoe_monsters(schema, src)
    schedules = merge(schema, "QuestEventScheduleTable",
                      [r for r in mobile_rows(src, "QuestEventScheduleTable")
                       if int(r.get("questEventIndex") or 0) in qes],
                      "questEventScheduleIndex", src, [])
    added = {t: len(merge(schema, t, mobile_rows(src, t), key, src, ["ModeTable"] if t in MENU else []))
             for t, key in {**DEDICATED, **MENU}.items()}

    stage_rows = [r for r in load_data("QuestEventStageTable")["rows"]
                  if int(r.get("questEventIndex") or 0) in todo]
    groups = {int(r[k]) for r in stage_rows for k in
              ("questEventStageClearRewardGroup", "questEventStageFirstClearRewardGroup",
               "missionCompleteRewardGroup") if r.get(k)}
    for table, cols in (("SuraDungeonDifficultyTable", ("suraDungeonMopUpRewardIndex",)),
                        ("ProveDungeonStageTable", ("proveDungeonWinRewardGroup", "proveDungeonAllKillBonus")),
                        ("ChallengeScheduleTable", ("challengeRewardGroup",)),
                        ("ChallengeScoreTable", ("scoreRewardGroup",))):
        groups |= {int(r[k]) for r in load_data(table)["rows"] for k in cols if r.get(k)}
    displays = {int(r["dropRewardDisplayGroup"]) for r in stage_rows if r.get("dropRewardDisplayGroup")}
    missions = {int(r[k]) for r in stage_rows for k in ("mission1Index", "mission2Index", "mission3Index")
                if r.get(k)}
    ref_rows = stage_rows + load_data("ChallengeStageTable")["rows"]
    maps = {int(r["resourceMapIndex"]) for r in ref_rows if r.get("resourceMapIndex")}
    balances = {int(r[k]) for r in ref_rows for k in
                ("stageBalanceIndex", "singleStageBalanceIndex", "multiStageBalanceIndex") if r.get(k)}

    def closure(table, key, wanted):
        """Mobile rows of `table` the imported stages reference and the project lacks; exits when an id
        is in neither place -- a stage pointing at a missing map or balance hangs the battle scene."""
        have = {int(r.get(key) or 0) for r in load_data(table)["rows"]}
        mobile = {int(r[key]): r for r in mobile_rows(src, table) if r.get(key) is not None}
        nowhere = sorted(i for i in wanted if i not in have and i not in mobile)
        if nowhere:
            sys.exit(f"{table}: {key} referenced by the imported stages but in neither the project "
                     f"tables nor the mobile source: {nowhere}")
        return [mobile[i] for i in sorted(wanted) if i not in have]

    resmaps = merge(schema, "ResourceMapTable", closure("ResourceMapTable", "resourceMapIndex", maps),
                    "resourceMapIndex", src, [])
    resbalances = merge(schema, "StageBalanceTable",
                        closure("StageBalanceTable", "stageBalanceIndex", balances),
                        "stageBalanceIndex", src, [])
    diff_mobile = {int(r["difficultyIndex"]): r for r in mobile_rows(src, "DifficultyTable")
                   if r.get("difficultyIndex") is not None}
    difficulties = {int(r["difficultyType"]) for r in stage_rows if r.get("difficultyType")}
    difficulties |= {i for i, r in diff_mobile.items() if int(r.get("modeIndex") or 0) == 202}
    diff_rows = closure("DifficultyTable", "difficultyIndex", difficulties)
    diffs = merge(schema, "DifficultyTable", diff_rows, "difficultyIndex", src, [])
    diff_tags = {v for i in difficulties if i in diff_mobile
                 for v in (diff_mobile[i].get("difficultyNameStringTag"),
                           diff_mobile[i].get("difficultyNameStringTagEng"))
                 if isinstance(v, str)}
    diff_strings = strings_add(src, ["DifficultyTable", "SystemTable"], diff_tags)

    reward_rows = [r for r in mobile_rows(src, "RewardGroupTable")
                   if int(r.get("rewardGroup") or 0) in groups]
    rewards = merge(schema, "RewardGroupTable", reward_rows, "rewardGroupIndex", src, [])
    items = {int(r["contentsIndex"]) for r in reward_rows if int(r.get("rewardType") or 0) == 13
             and r.get("contentsIndex")}
    item_rows = [r for r in mobile_rows(src, "ItemTable")
                 if int(r.get("itemIndex") or 0) in items or 3_000_000 <= int(r.get("itemIndex") or 0) < 4_000_000]
    items_added = merge(schema, "ItemTable", item_rows, "itemIndex", src, ["ItemTable"])
    merge(schema, "StageMissionTable",
          [r for r in mobile_rows(src, "StageMissionTable")
           if int(r.get("stageMissionIndex") or 0) in missions],
          "stageMissionIndex", src, ["StageMissionTable"])
    merge(schema, "RewardDisplayTable",
          [r for r in mobile_rows(src, "RewardDisplayTable")
           if int(r.get("rewardDisplayGroup") or 0) in displays],
          "rewardDisplayIndex", src, [])

    print(f"QuestEventTable +{len(events)} | QuestEventStageTable +{len(stages)} "
          f"(PC triggers {renamed}) | "
          f"QuestEventScheduleTable +{len(schedules)} | RewardGroupTable +{len(rewards)} | "
          f"ResourceMapTable +{len(resmaps)} | StageBalanceTable +{len(resbalances)} | "
          f"DifficultyTable +{len(diffs)} (strings +{diff_strings}) | "
          f"ItemTable +{len(items_added)} | UI strings +{ui_strings(src)}")
    print(" | ".join(f"{t} +{n}" for t, n in added.items() if n) or "dedicadas: nada novo")
    print("Hall of Elements monsters: " + " | ".join(f"{t} +{n}" for t, n in hoe.items()))


if __name__ == "__main__":
    main()
