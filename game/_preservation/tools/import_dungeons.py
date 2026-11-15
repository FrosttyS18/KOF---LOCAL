"""Import QuestEvent-driven dungeon data from the community mobile server (kofas_server/server/tabel
+ tabel_teks, Indonesian offline APK) into this project's rebuilt tables.

Two sets, all from the real mobile tables:
  Transcendence (default questEventIndex list): Hall of Elements 41001-41005 + Advent 42001-42006 --
    their QuestEventTable / QuestEventStageTable / QuestEventScheduleTable rows.
  Challenge (always): Tower of Illusion 107, Buff Select Dungeon 8101, Sura Dungeon 10801, Prove
    Dungeon 10901 -- their QuestEvent rows and stages, the systems' own tables (Challenge*Table,
    SuraDungeon*Table, ProveDungeon*Table, BuffSelectDungeon*Table) wholesale, and the ModeTable /
    ContentsUnlockTable / ContentsAdmissionTable rows that add the menu buttons.

Plus the closure of everything those rows reference: RewardGroupTable groups (including the
missionCompleteRewardGroup of every referenced StageMissionTable row -- the YOU WIN missions' own
rewards; Hall of Elements' 9610050 pays 50 rubies as rewardType 2, which carries no contentsIndex
and needs no ItemTable row), StageMissionTable rows, RewardDisplayTable groups, ItemTable rows paid
by type-13 rewards, the ResourceMapTable maps, StageBalanceTable balances and DifficultyTable rows
the stages load (the PC's Time Attack also asks DifficultyTable.GetDifficultyRange for hardcoded
modeIndex 202), and the name/description strings. Every referenced mission and reward group must
exist in the project tables or the mobile source -- the import aborts rather than fill a gap with
an invented default.
The Hall of Elements trigger graphs also require every HighComedown monster -- the five Flame Walker
bosses plus the ten mob/elite wave monsters their graphs spawn first (the live GraphOwner dump showed
NODE 7 creating Pierrena/Ryo waves before NODE 9's boss; boss-only v1015 left the arena empty) -- and
their monster skills, growth curves, level stats and AI groups from the mobile reference. The
player-AI AiGroupTable rows the imported stages' aiGrade demands are a compatibility adaptation
(a clone of the group's grade-1 row), documented in append_player_ai_grades.
Existing rows are never touched; only appended -- four deliberate in-place compatibility/UI
adaptations: adapt_triggers_to_pc renames questEvent 41001's singleTriggerName to the PC
bundle's real asset name, adapt_hoe_group_menu zeroes the five HoE rows'
specialQuestEventGroupOnOff so the hub collapses to one card whose per-boss tabs then open
natively, adapt_hoe_tab_elements rewrites the 165 HoE stages' dungeonType to each arena's
element so those tabs stop rendering all-Purple, and adapt_phantom_tower renumbers the mobile
Tower of Illusion floors onto the restored 1070001..1070050 ids (the reference's 10701..10720
collide with the daily Crucible Tower here) or leaves them alone while the project still runs
the legacy 10721..10750 import. Fields follow server/tables/schema.json.

usage: import_dungeons.py <kofas_server folder> [questEventIndex ...]
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # the embedded python's _pth never adds the script's own folder
import read_unityfs

DATA = os.path.join(HERE, "..", "server", "tables", "data")
SCHEMA = os.path.join(HERE, "..", "server", "tables", "schema.json")
BUNDLES = os.path.abspath(os.path.join(HERE, "..", "..", "storage", "cache", "assetbundles"))
DEFAULT_QES = [41001, 41002, 41003, 41004, 41005, 42001, 42002, 42003, 42004, 42005, 42006]
CHALLENGE_QES = [107, 8101, 10801, 10901]
PHANTOM_QE = 107  # the mobile reference numbers its floors 10701..10750, but 10701..10720 are the
PHANTOM_LEGACY = frozenset(range(10721, 10751))  # daily Crucible Tower's floors 101..120 here, so
PHANTOM_RESTORED = frozenset(range(1070001, 1070051))  # restore_phantom_tower.py moved the event to
PHANTOM_SOURCE = frozenset(range(10701, 10751))  # this collision-free block; a raw merge would
# re-add 10721..10750 next to it and break the openValue chain the client's entry check walks
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


def adapt_phantom_tower(rows):
    """Renumber the mobile Tower of Illusion rows onto the 1070001..1070050 ids a restored
    project uses, in place, before anything merges. When the master still carries the legacy
    import (or nothing) the rows pass through untouched, so running this script before
    restore_phantom_tower.py behaves exactly as it always did. Aborts before any table is
    written when the master's event-107 rows straddle or only partially cover a namespace,
    when a restored id is owned by another event, or when the source does not carry all 50
    floors with an intact openValue chain -- a partial prefix would import floors whose
    openValue points at ids that exist nowhere."""
    master = load_data("QuestEventStageTable")["rows"]
    ids = {int(r.get("questEventStageIndex") or 0) for r in master
           if int(r.get("questEventIndex") or 0) == PHANTOM_QE}
    if not ids & PHANTOM_RESTORED:
        if ids - PHANTOM_LEGACY:
            sys.exit(f"QuestEventStageTable: event {PHANTOM_QE} in an unknown state "
                     f"(neither legacy {min(PHANTOM_LEGACY)}..{max(PHANTOM_LEGACY)} nor "
                     f"restored {min(PHANTOM_RESTORED)}..{max(PHANTOM_RESTORED)}): {sorted(ids)}")
        return
    if ids != PHANTOM_RESTORED:
        sys.exit(f"QuestEventStageTable: event {PHANTOM_QE} only partially restored "
                 f"({len(ids)} of {len(PHANTOM_RESTORED)} floors); rerun "
                 "tools/restore_phantom_tower.py before importing")
    foreign = sorted({int(r.get("questEventStageIndex") or 0) for r in master
                      if int(r.get("questEventStageIndex") or 0) in PHANTOM_RESTORED
                      and int(r.get("questEventIndex") or 0) != PHANTOM_QE})
    if foreign:
        sys.exit(f"QuestEventStageTable: restored ids owned by another quest event: {foreign}")
    source = {int(r.get("questEventStageIndex") or 0) for r in rows}
    if source != PHANTOM_SOURCE:
        sys.exit(f"mobile QuestEventStageTable: a restored event {PHANTOM_QE} needs all "
                 f"{len(PHANTOM_SOURCE)} floors {min(PHANTOM_SOURCE)}..{max(PHANTOM_SOURCE)} "
                 f"with their chain intact, found {sorted(source)}")
    for row in rows:
        floor = int(row["questEventStageIndex"]) - min(PHANTOM_SOURCE)
        if int(row.get("openValue") or 0) != (0 if floor == 0 else min(PHANTOM_SOURCE) + floor - 1):
            sys.exit(f"mobile QuestEventStageTable: floor {floor + 1} openValue "
                     f"{row.get('openValue')} breaks the reference chain")
        row["questEventStageIndex"] = min(PHANTOM_RESTORED) + floor
        row["openValue"] = 0 if floor == 0 else min(PHANTOM_RESTORED) + floor - 1


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


def adapt_hoe_group_menu():
    """UI adaptation (the second in-place exception): the hub's Transcendence menu renders one card
    per QuestEvent row with specialQuestEventGroupOnOff != 0 -- five Hall of Elements cards today.
    At 0 the card dedups by SubType and UIPage_SPQuestMode.SetData lists every group of the param's
    SubType (FindAll b__0 @ 0x18086B700 compares only get_questEventSubType), i.e. one card ->
    per-boss tabs -> each boss's 33 stages, with Type 10 and every other row untouched. The card
    title reads the first row's nameTag, so the collapsed card would say "Hall of Elements -
    Purple" while its color-only tabs (the maintainer's call) already carry each element: the
    maintainer authorized rewriting QuestEvent.Name.41001 in place to the exact common prefix of
    the five imported event names ("Hall of Elements") as the offline hub label. Deliberate UI
    label, no game data: the other four names, bosses, elements, difficulties and rewards stay
    exactly as imported; refuses unless the five real names share that prefix."""
    doc = load_data("QuestEventTable")
    rows = [r for r in doc["rows"] if 41001 <= int(r.get("questEventIndex") or 0) <= 41005]
    if (len(rows) != 5
            or {int(r["questEventIndex"]) for r in rows} != set(range(41001, 41006))
            or any(int(r.get("questEventType") or 0) != 10
                             or int(r.get("questEventSubType") or 0) != 27
                             or int(r.get("questEventGroup") or 0) != 41000 for r in rows)):
        sys.exit("QuestEventTable: expected the five Hall of Elements rows as Type 10 / SubType 27 / "
                 "group 41000 before grouping their menu card")
    changed = 0
    for row in rows:
        if row.get("specialQuestEventGroupOnOff") != 0:
            row["specialQuestEventGroupOnOff"] = 0
            changed += 1
    if changed:
        save_data("QuestEventTable", doc)
    strings = json.load(open(os.path.join(DATA, "strings_en.json"), encoding="utf-8"))
    names = {i: strings.get(f"QuestEvent.Name.{i}") for i in range(41001, 41006)}
    prefix = os.path.commonprefix([names[i] for i in range(41001, 41006)]).rstrip(" -")
    if (any(v is None for v in names.values()) or prefix != "Hall of Elements"
            or not all(names[i].startswith(prefix + " ") and len(names[i]) > len(prefix) + 1
                       for i in range(41002, 41006))):
        sys.exit("strings_en: QuestEvent.Name.41001..41005 should read 'Hall of Elements - <element>' "
                 "before deriving the hub label -- refusing to title the card")
    retitled = 0
    if strings["QuestEvent.Name.41001"] != prefix:
        strings["QuestEvent.Name.41001"] = prefix
        json.dump(strings, open(os.path.join(DATA, "strings_en.json"), "w", encoding="utf-8"),
                  indent=1, ensure_ascii=False)
        retitled = 1
    return changed, retitled


def adapt_hoe_tab_elements():
    """UI adaptation (the third in-place exception): the grouped card's per-boss tabs take their
    color from the group's first stage's dungeonType -- UIPage_SPQuestMode.SetTab (0x18086A130)
    passes QuestEventStageProto+0x6C to UIUnit_SPQuestTab.SetData (0x18086F920), whose only use of
    the value is StringDefine.GetFighterSynastryIcon (0x180505010) for the tab's active and
    inactive sprites; SynastryType 1 Purple, 2 Blue, 3 Red, 4 Green, 5 Yellow. The mobile source
    ships every HoE stage with dungeonType 1, so all five tabs render Purple; each stage already
    carries its arena's element in its own setSynastry{Normal,Elite,Boss}MonsterValue (the 33 rows
    of questEvent 4100n agree on n). Rewrites only dungeonType of the 165 HoE stages to that
    element; nothing else in those rows and no other row changes. Refuses (before writing) anything
    unexpected: missing/extra events, a stage count other than 33, questEventStageIndex other than
    each event's 4100n01..4100n33 exactly once, setSynastry disagreement inside a row or across an
    event's rows, elements outside 1..5 or not the five distinct values, or a current dungeonType
    that is neither the mobile source's 1 nor the element itself."""
    doc = load_data("QuestEventStageTable")
    per_event = {}
    for row in doc["rows"]:
        if 41001 <= int(row.get("questEventIndex") or 0) <= 41005:
            per_event.setdefault(int(row["questEventIndex"]), []).append(row)
    counts = {event: len(rows) for event, rows in sorted(per_event.items())}
    if set(per_event) != set(range(41001, 41006)) or any(n != 33 for n in counts.values()):
        sys.exit(f"QuestEventStageTable: expected the five Hall of Elements events 41001-41005 with "
                 f"33 stages each before recoloring their tabs, got {counts}")
    changed = 0
    elements = {}
    for event, rows in sorted(per_event.items()):
        indexes = [int(row.get("questEventStageIndex") or 0) for row in rows]
        expected = {event * 100 + n for n in range(1, 34)}
        if len(set(indexes)) != len(indexes) or set(indexes) != expected:
            sys.exit(f"QuestEventStageTable: questEvent {event}'s 33 questEventStageIndex should be "
                     f"{event * 100 + 1}..{event * 100 + 33} once each, got {sorted(indexes)}")
        values = {v for row in rows for v in (int(row.get(k) or 0) for k in
                   ("setSynastryNormalMonsterValue", "setSynastryEliteMonsterValue",
                    "setSynastryBossMonsterValue"))}
        if len(values) != 1 or not 1 <= next(iter(values)) <= 5:
            sys.exit(f"QuestEventStageTable: questEvent {event}'s stages disagree on their "
                     f"setSynastry*MonsterValue element {sorted(values)} -- refusing to pick one")
        elements[event] = next(iter(values))
        for row in rows:
            current = int(row.get("dungeonType") or 0)
            if current == elements[event]:
                continue
            if current != 1:
                sys.exit(f"QuestEventStageTable: questEvent {event} stage "
                         f"{row.get('questEventStageIndex')} has dungeonType {current}, expected "
                         f"the mobile source's 1 -- refusing to overwrite it")
            row["dungeonType"] = elements[event]
            changed += 1
    if set(elements.values()) != set(range(1, 6)):
        sys.exit(f"QuestEventStageTable: the five Hall of Elements arenas should carry the five "
                 f"distinct elements 1-5, got {elements} -- refusing to recolor")
    if changed:
        save_data("QuestEventStageTable", doc)
    return changed


def import_hoe_monsters(schema, src):
    """Import every monster named by the PC HighComedown trigger graphs (5 Flame Walker bosses + the
    10 mob/elite wave monsters their graphs spawn before each boss) and their table dependencies.
    All skillNIndex references resolve in MonsterSkillTable, and the monsters' prefab skill chains
    are closed on top (close_hoe_skill_chains); SkillTable is never touched."""
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
    counts["MonsterSkillChain"], orphans = close_hoe_skill_chains(schema, src, monsters)
    return counts, orphans


def close_hoe_skill_chains(schema, src, monsters):
    """Close MonsterSkillTable over what the client actually loads, not just the 12 root slots.

    MonsterBattleController.SetSkillData (0x181160BD0) walks each skill prefab's m_linkedSkill chain
    (Skill+0x88): per link it Int32.Parse's the part after '#' of the parent's SkillIndexString, then
    MonsterSkillTable.FindByString looks up child.m_tableIndexString + '#' + that version. A missing
    child row leaves the child without ISkillData, so the next parent's Skill.get_SkillIndexString
    (0x1811EFD20: m_data at +0x168, null -> a '#'-less static fallback) feeds Int32.Parse a whole
    asset name and the spawn coroutine dies in FormatException -- green 4100401's first-wave Yuri
    never entered combat and the boss never spawned. The mobile rows carry the chain links only in
    the prefabs, so the closure reads each monster's cached prefabs_monster_<name> bundle
    (tools/read_unityfs.py; the CDN file name is md5 of the bundle name) and appends the original
    mobile row of every Skill.* name it contains, version '#1' (the only one any Hall of Elements
    row carries). Skill-less monsters (Ryo/Kyo/Kdash: skill-less in the mobile source as well, so
    SetSkillData never runs for them) need no bundle; a skill-carrying monster without its cached
    bundle aborts the import rather than guess the chain. Bundle skill names with no row in the
    project or the mobile source are reported as orphans and left alone -- never invented."""
    doc = load_data("MonsterSkillTable")
    have = {r.get("monsterSkillIndexString") for r in doc["rows"]}
    mobile = mobile_rows(src, "MonsterSkillTable")
    by_string = {r.get("monsterSkillIndexString"): r for r in mobile}
    wanted, orphans = set(), {}
    for m in monsters:
        parts = m["monsterIndexString"].split(".")     # Monster.<Name>.<Grade>.HighComedown
        bundle = os.path.join(BUNDLES, hashlib.md5(f"prefabs_monster_{parts[1].lower()}".encode()).hexdigest())
        if not [v for k, v in m.items() if re.fullmatch(r"skill\d+Index", k) and v]:
            continue
        if not os.path.isfile(bundle):
            sys.exit(f"prefabs_monster_{parts[1].lower()}: skill-carrying {m['monsterIndexString']} has "
                     f"no cached bundle to close its skill chain from")
        for name in bundle_skill_names(bundle):
            if name + "#1" in have:
                continue
            if name + "#1" in by_string:
                wanted.add(name + "#1")
            else:
                orphans[name] = m["monsterIndexString"]
    added = merge(schema, "MonsterSkillTable", [by_string[s] for s in sorted(wanted)],
                  "monsterSkillIndex", src, ["MonsterSkillTable"])
    return len(added), orphans


def bundle_skill_names(bundle):
    """Sorted Skill.* strings of a cached UnityFS bundle: the monster's own skill assets, whose prefab
    names and serialized m_tableIndexString values are the same strings. Path tails the regex also
    catches (e.g. 'Skill.prefab' inside '.../Skill.prefab') are dropped by the prefab-segment check."""
    names = {m.group(0) for m in re.finditer(r"Skill\.[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*",
                                             read_unityfs.load(bundle).decode("latin-1"))}
    return sorted(n for n in names
                  if not any(part.startswith("prefab") for part in n.split(".")[1:]))


def append_player_ai_grades(schema, src, ref_rows):
    """Compatibility ADAPTATION, not a restoration: the last HoE stage hangs loading characters
    because AiGroupTable.Find wants the player group's row at the stage's own aiGrade (dump.cs
    QuestEventStageProto _aiGrade 0x100 -- exactly what MyInfo.GetAIGroupGrade returns for
    quest-event stages, per the independent Ghidra read) and the reconstructed player group 301
    stops at grade 5. Grade 6 for group 301 exists in no available source (mobile has no group
    301; the original PC aigrouptable.bin cannot be decrypted, so whether a real 3016 ever
    existed is unknowable). Clones each player group's grade-1 row whole: only aiGrade and
    aiGroupIndex change (template index - template grade + grade, the group's 301n numbering).
    No combat behavior is invented: all 301 rows share the Fighter001 prefab, whose NodeCanvas
    graphs hold no grade/aiOperationValue branch, and the omitted aiOperationValue keeps the
    client default (AiGroup.EffectiveOperationValue: field 0x24, 0 => constant 0.2), exactly like
    the working grades 1..5. Enemy rows (70506/70606) are never touched.

    Only PLAYER groups are extended: the Prove boss fighters (ProveDungeonBossTeamTable
    bossTeamStringIndex/bossTeamStrikerIndex -- identified by data, never by name tag) are NPC duel
    enemies whose aiGroup rows the source already carries per grade (group 690: 69000..69010) and
    heterogeneous by design -- cloning them as player groups would abort the guards below and
    corrupt enemy AI. Their groups are skipped whole; their original rows stay untouched."""
    rows = load_data("AiGroupTable")["rows"]
    grades = {int(r["aiGrade"]) for r in ref_rows if int(r.get("aiGrade") or 0) > 0}
    npc = {int(r[k]) for r in load_data("ProveDungeonBossTeamTable")["rows"]
           for k in ("bossTeamStringIndex", "bossTeamStrikerIndex") if r.get(k)}
    add, used = [], {int(r.get("aiGroupIndex") or 0) for r in rows}
    for group in sorted({int(r["aiGroup"]) for r in load_data("CharacterTable")["rows"]
                         if r.get("aiGroup") is not None
                         and int(r["characterIndex"]) not in npc}):
        members = [r for r in rows if int(r.get("aiGroup") or 0) == group]
        base = [r for r in members if int(r.get("aiGrade") or 0) == 1]
        if not members or len(base) != 1:
            sys.exit(f"AiGroupTable: player aiGroup {group} lacks a single grade-1 row to clone")
        template = {k: v for k, v in base[0].items() if k not in ("aiGrade", "aiGroupIndex")}
        strays = [r.get("aiGroupIndex") for r in members
                  if {k: v for k, v in r.items() if k not in ("aiGrade", "aiGroupIndex")} != template]
        if strays:
            sys.exit(f"AiGroupTable: player aiGroup {group} rows {strays} differ from the grade-1 "
                     "template beyond aiGrade/aiGroupIndex -- refusing to extend the group")
        for grade in sorted(grades - {int(r.get("aiGrade") or 0) for r in members}):
            index = int(base[0]["aiGroupIndex"]) - int(base[0]["aiGrade"]) + grade
            if index in used:
                sys.exit(f"AiGroupTable: player aiGroup {group} grade {grade} would collide at "
                         f"aiGroupIndex {index}")
            used.add(index)
            clone = dict(base[0])
            clone["aiGroupIndex"] = index
            clone["aiGrade"] = grade
            add.append(clone)
    return len(merge(schema, "AiGroupTable", add, "aiGroupIndex", src, []))


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

    mobile_stages = mobile_rows(src, "QuestEventStageTable")
    adapt_phantom_tower([r for r in mobile_stages
                         if int(r.get("questEventIndex") or 0) == PHANTOM_QE])
    events = merge(schema, "QuestEventTable",
                   [r for r in mobile_rows(src, "QuestEventTable")
                    if int(r.get("questEventIndex") or 0) in todo],
                   "questEventIndex", src, ["QuestEventTable"])
    stages = merge(schema, "QuestEventStageTable",
                   [r for r in mobile_stages
                    if int(r.get("questEventIndex") or 0) in todo],
                   "questEventStageIndex", src, ["QuestEventStageTable"])
    renamed = adapt_triggers_to_pc()
    grouped, retitled = adapt_hoe_group_menu()
    recolored = adapt_hoe_tab_elements()
    hoe, hoe_orphans = import_hoe_monsters(schema, src)
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
    ai_added = append_player_ai_grades(schema, src, ref_rows)
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

    mission_rows = closure("StageMissionTable", "stageMissionIndex", missions)
    groups |= {int(r["missionCompleteRewardGroup"]) for r in mission_rows
               + [m for m in load_data("StageMissionTable")["rows"]
                  if int(m.get("stageMissionIndex") or 0) in missions]
               if r.get("missionCompleteRewardGroup")}
    nowhere = sorted(groups
                     - {int(r["rewardGroup"]) for r in load_data("RewardGroupTable")["rows"]}
                     - {int(r["rewardGroup"]) for r in mobile_rows(src, "RewardGroupTable")})
    if nowhere:
        sys.exit(f"RewardGroupTable: rewardGroup referenced by the imported stages or missions but in "
                 f"neither the project tables nor the mobile source: {nowhere}")

    reward_rows = [r for r in mobile_rows(src, "RewardGroupTable")
                   if int(r.get("rewardGroup") or 0) in groups]
    rewards = merge(schema, "RewardGroupTable", reward_rows, "rewardGroupIndex", src, [])
    items = {int(r["contentsIndex"]) for r in reward_rows if int(r.get("rewardType") or 0) == 13
             and r.get("contentsIndex")}
    item_rows = [r for r in mobile_rows(src, "ItemTable")
                 if int(r.get("itemIndex") or 0) in items or 3_000_000 <= int(r.get("itemIndex") or 0) < 4_000_000]
    items_added = merge(schema, "ItemTable", item_rows, "itemIndex", src, ["ItemTable"])
    merge(schema, "StageMissionTable", mission_rows, "stageMissionIndex", src, ["StageMissionTable"])
    merge(schema, "RewardDisplayTable",
          [r for r in mobile_rows(src, "RewardDisplayTable")
           if int(r.get("rewardDisplayGroup") or 0) in displays],
          "rewardDisplayIndex", src, [])

    print(f"QuestEventTable +{len(events)} | QuestEventStageTable +{len(stages)} "
          f"(PC triggers {renamed}, HoE menu grouped {grouped}, hub titled {retitled}, "
          f"tab elements {recolored}) | "
          f"QuestEventScheduleTable +{len(schedules)} | RewardGroupTable +{len(rewards)} | "
          f"ResourceMapTable +{len(resmaps)} | StageBalanceTable +{len(resbalances)} | "
          f"DifficultyTable +{len(diffs)} (strings +{diff_strings}) | "
          f"ItemTable +{len(items_added)} | UI strings +{ui_strings(src)}")
    print(" | ".join(f"{t} +{n}" for t, n in added.items() if n) or "dedicadas: nada novo")
    print("Hall of Elements monsters: " + " | ".join(f"{t} +{n}" for t, n in hoe.items()))
    if hoe_orphans:
        print("Hall of Elements bundle skills with no table row in any source (left as-is): "
              + ", ".join(f"{n} [{m}]" for n, m in sorted(hoe_orphans.items())))
    print(f"player AI grades +{ai_added} (AiGroupTable)")


if __name__ == "__main__":
    main()
