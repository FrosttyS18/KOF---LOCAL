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
RewardDisplayTable groups, ItemTable rows paid by type-13 rewards, and the name/description strings.
Existing rows are never touched; only appended. Fields follow server/tables/schema.json.

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


UI_TERMS = ("buffselect", "sura", "prove", "timeattack", "phantom", "challenge", "transcend", "comedown",
            "marathon", "hallofelements", "adventure.come")


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

    print(f"QuestEventTable +{len(events)} | QuestEventStageTable +{len(stages)} | "
          f"QuestEventScheduleTable +{len(schedules)} | RewardGroupTable +{len(rewards)} | "
          f"ItemTable +{len(items_added)} | UI strings +{ui_strings(src)}")
    print(" | ".join(f"{t} +{n}" for t, n in added.items() if n) or "dedicadas: nada novo")


if __name__ == "__main__":
    main()
