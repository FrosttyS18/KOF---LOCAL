"""Import the monster/skill/AI closure of the six Advent comedown events (questEvent
42001-42006: Yashiro Halloween, Athena & Sakura, Twins Ranger, Yamazaki, Statue Goenitz,
Saisyu CD) from the mobile source into the project tables.

Chain, derived from the project tables on every run (nothing is a snapshot): each Advent
stage's singleTriggerName names a trigger prefab under Prefabs/EventSystem/Trigger/...;
the folder part of that path lowercased and '_'-joined is the asset bundle name, whose
file in game/storage/cache/assetbundles is the md5 of that name. The bundle is
decompressed with tools/read_unityfs.py (read-only, stable) and every JSON string value
"Monster.<name>" (key m_indexString included) is collected as a monster the trigger
graphs may spawn. That ref set is a BUNDLE-LEVEL SUPERSET: the exact SerializedFile v22
graph parser is still being rebuilt for this cache (Unity 2021.3, type trees shipped),
so no monster here is attributed to a specific stage or wave -- the tool closes the whole
superset, which only ever appends rows the stages never load and never changes the stats
of a row they do. Events sharing a trigger folder (42001/42002 both live in
prefabs_eventsystem_trigger_comedown) share one superset, including refs of other
comedown triggers that ride in the same bundle; every such extra is an original mobile
row, appended as-is.

Every "Monster.*" reference must resolve exactly (case-insensitive: the graphs spell
Comedown/Comdown/ComeDown and Greed_BLue) against the project MonsterTable first, then
the mobile source; an unresolved reference aborts before any write as a blocking gap --
nothing is cloned, defaulted or invented. The case-insensitive match is the client's own
predicate: MonsterTable.FindMonsterIndexByString (0x180D428E0) filters with lambda
0x180D42B20, which calls System.Globalization.CompareInfo.CompareOrdinalIgnoreCase (see
native-analysis/decomp-180D428E0.txt and decomp-180D42B20.txt) -- so refs are matched
ordinal-ignore-case and the tables' m_indexString spelling is never rewritten.

Skills close over the direct skillNIndex slots of each chosen row, PLUS every '#N'
continuation the mobile source or the project carries under the same Skill.<base> name,
PLUS every "Skill.<...>" string found in the bytes of the bundles the closure already
resolved: each monster's model bundles (manifest prefabs_* names ENDING with the prefab's
file token, or parent token, on a '_' boundary -- suffix heuristic, documented) and each
needed aiGroup's aiBaseNodeName folder bundle, next to the five trigger bundles. Those
bundles carry linked children
under a DIFFERENT base (Yashiro S03Start -> S03End, S05Start/Loop/End; the same shape as
the HoE S02Start -> S02End chain), which the same-base rule alone never finds. The scan
is a raw substring match, so it also picks up non-live names of other assets sharing a
bundle: a hit can only pull an existing original row (resolved ordinal-ignore-case
against MonsterSkillTable rows; an ambiguous name aborts), never fabricate one, and refs
with no row anywhere are reported as orphans instead of invented. Per-asset attribution
of a skill to one prefab needs the exact SerializedFile v22 parser and stays out of here.
Growth closes whole growthTypes, level stats close every
(levelStatType, monsterLevel) the six events' stages use, AI closes every
(aiGroup, aiGrade) the stages' own aiGrade field needs (Find reads the stage's _aiGrade),
and every appended row's tags get their real texts via the shared strings_add (tags with
no text in any source stay absent and are only reported, like the project's other
MonsterSkillTable rows). Model and trigger bundles must exist in the client's own
assetbundles.info index with a file on disk for every resolved monster prefab (parent
folder token fallback for prefabs whose file name differs, e.g. the Rangers); a missing
bundle aborts as a blocking gap.

Strict integers, duplicate guards, schema filtering, append-only writes, PC-first
closure and collision refusal mirror tools/import_dungeon_monsters.py; the project's
row always wins and a divergent mobile row is only reported, never merged over it.

usage: import_advent_dependencies.py <kofas_server folder> [--data DIR]
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
import import_dungeons as base
from import_dungeon_monsters import same_row, skill_indexes
import read_unityfs

ADVENT_QES = (42001, 42002, 42003, 42004, 42005, 42006)
CACHE = os.path.normpath(os.path.join(HERE, "..", "..", "storage", "cache"))
JSON_MONSTER = re.compile(rb'"(Monster\.[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)"')
RAW_SKILL = re.compile(rb"Skill\.[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*(?:#[0-9]+)?")
HASH_SUFFIX = re.compile(r"#\d+$")


def fail(msg):
    sys.exit(f"import_advent_dependencies: {msg}")


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


def manifest_index():
    """{bundle name} from the client's own assetbundles.info (see kofserver.bundle_manifest),
    plus a {lowercased name} set for the substring lookups below."""
    path = os.path.join(CACHE, "assetbundles.info")
    d = open(path, "rb").read()
    i, names = 0, set()
    while i + 4 <= len(d):
        n = struct.unpack_from("<i", d, i)[0]
        name = d[i + 4:i + 4 + n].decode()
        i += 4 + n
        n = struct.unpack_from("<i", d, i)[0]
        val = d[i + 4:i + 4 + n].decode()
        i += 4 + n
        if len(val) == 32:
            names.add(name)
    return names, {n.lower() for n in names}


def bundle_file(bundle):
    return os.path.join(CACHE, "assetbundles", hashlib.md5(bundle.encode()).hexdigest())


def bundle_with_file(names, token, label):
    """First manifest bundle containing `token` whose file exists on disk (substring heuristic:
    the manifest has no path->asset index we can read without the v22 parser)."""
    if not token:
        return None
    for name in sorted(names):
        if token in name.lower() and os.path.exists(bundle_file(name)):
            return name
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("src", help="kofas_server folder (with tabel/ and tabel_teks/)")
    parser.add_argument("--data", default=os.path.normpath(os.path.join(HERE, "..", "server",
                                                                        "tables", "data")),
                        help="tables data dir to update (default: the project's)")
    args = parser.parse_args()
    src, data = args.src, args.data
    if not os.path.isdir(os.path.join(src, "tabel")):
        fail(f"{src} has no tabel/ -- usage: import_advent_dependencies.py <kofas_server folder> "
             f"[--data DIR]")
    if not os.path.isfile(os.path.join(data, "QuestEventStageTable.json")):
        fail(f"{data} carries no QuestEventStageTable.json")
    schema = json.load(open(base.SCHEMA, encoding="utf-8"))
    base.DATA = data

    consumed = ("MonsterTable", "MonsterSkillTable", "MonsterGrowthTable",
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
    advent = [r for r in stages if as_int(r.get("questEventIndex"), "questEventIndex")
              in ADVENT_QES]
    if not advent:
        fail(f"QuestEventStageTable: no Advent stages for {ADVENT_QES} in the project tables")
    dup_guard(advent, lambda r: r.get("questEventStageIndex"), stage_fields,
              "QuestEventStageTable Advent (project)")
    for table, stage_field, key in (("ResourceMapTable", "resourceMapIndex", "resourceMapIndex"),
                                    ("StageBalanceTable", "singleStageBalanceIndex",
                                     "stageBalanceIndex"),
                                    ("DifficultyTable", "difficultyType", "difficultyIndex")):
        have = keyed(base.load_data(table)["rows"], lambda r, k=key: r.get(k))
        gaps = sorted({f"{r.get(stage_field)}" for r in advent
                       if str(r.get(stage_field)) not in {str(k) for k in have}})
        if gaps:
            fail(f"{table}: Advent stages reference missing {stage_field} {gaps}")
    grades = sorted({as_int(r.get("aiGrade"), "aiGrade") for r in advent if r.get("aiGrade")})
    levels = sorted({as_int(r.get("monsterLevel"), "monsterLevel")
                     for r in advent if r.get("monsterLevel")})

    names, names_low = manifest_index()
    maps = keyed(base.load_data("ResourceMapTable")["rows"], lambda r: r.get("resourceMapIndex"))
    scenes = {maps[r.get("resourceMapIndex")].get("resourceMapScene")
              for r in advent if r.get("resourceMapIndex") in maps}
    scene_gaps = sorted(s for s in scenes
                        if s and not bundle_with_file(names, s.lower().replace("/", "_"),
                                                     "bg scene"))
    if scene_gaps:
        fail(f"no cached bundle carries the Advent bg scenes {scene_gaps}")

    triggers = {}
    for r in advent:
        path = r.get("singleTriggerName")
        if not path:
            fail(f"stage {r.get('questEventStageIndex')} has no singleTriggerName")
        asset = path.strip("/").split("/")[-1]
        bundle = "_".join(p.lower() for p in path.strip("/").split("/")[:-1])
        triggers.setdefault(bundle, set()).add(asset)
    for bundle in sorted(triggers):
        if bundle not in names or not os.path.exists(bundle_file(bundle)):
            fail(f"trigger bundle {bundle} is not in assetbundles.info with a file on disk")
        stream = read_unityfs.load(bundle_file(bundle))
        for asset in sorted(triggers[bundle]):
            if asset.encode() not in stream:
                fail(f"trigger asset {asset} not found in bundle {bundle} (bytes probe)")
        triggers[bundle] = stream

    refs = set()
    for bundle, stream in triggers.items():
        found = {m.decode() for m in JSON_MONSTER.findall(stream)}
        if not found:
            fail(f"bundle {bundle} carries no \"Monster.*\" JSON value -- nothing to close")
        refs |= found

    mon_fields = fields["MonsterTable"]
    proj_rows = dup_guard(base.load_data("MonsterTable")["rows"],
                          lambda r: r.get("monsterIndex"), mon_fields, "MonsterTable (project)")
    mob_rows = dup_guard(base.mobile_rows(src, "MonsterTable"),
                         lambda r: r.get("monsterIndex"), mon_fields, "MonsterTable (mobile)")
    by_lower = {}
    ambiguous = set()
    for r in list(proj_rows.values()) + list(mob_rows.values()):
        s = r.get("monsterIndexString")
        if not isinstance(s, str):
            continue
        first = by_lower.setdefault(s.lower(), r)
        if first.get("monsterIndex") != r.get("monsterIndex"):
            ambiguous.add(s.lower())
    unresolved = sorted(r for r in refs if r.lower() not in by_lower)
    clash = sorted(r for r in refs if r.lower() in ambiguous)
    if unresolved or clash:
        fail(f"trigger graph refs cannot be resolved to exactly one monster row (blocking gap, "
             f"nothing imported) -- unresolved: {unresolved} -- ambiguous name: {clash}")

    rows_of = {}
    mon_append = []
    proj_strings_low = {r.get("monsterIndexString", "").lower() for r in proj_rows.values()}
    for ref in sorted(refs):
        row = by_lower[ref.lower()]
        rows_of[ref] = row
        if row.get("monsterIndex") in proj_rows and row.get("monsterIndexString", "").lower() \
                not in proj_strings_low:
            fail(f"MonsterTable: mobile monsterIndex {row.get('monsterIndex')} "
                 f"({row.get('monsterIndexString')}) collides with a different project row")
        if row.get("monsterIndexString", "").lower() not in proj_strings_low:
            mon_append.append({k: v for k, v in row.items() if k in mon_fields})
    seen_ids = set()
    deduped = []
    for r in mon_append:
        if r.get("monsterIndex") not in seen_ids:
            seen_ids.add(r.get("monsterIndex"))
            deduped.append(r)
    mon_append = deduped

    def model_scan_bundles(token):
        """prefabs_* bundles whose name ENDS with the token on a '_' boundary: the bundle
        actually named after the prefab, not other events' variants that merely contain the
        word (prefabs_monster_yashiro_halloween, not prefabs_monster_bottle_crucibletower51)."""
        if not token:
            return []
        return sorted(n for n in names
                      if n.startswith("prefabs_") and (n == token or n.endswith("_" + token))
                      and os.path.exists(bundle_file(n)))

    model_gaps = []
    scan = {name: "trigger" for name in triggers}
    for ref in sorted(rows_of):
        prefab = rows_of[ref].get("monsterPrefab") or ""
        parts = [p for p in prefab.split("/") if p]
        file_tok = parts[-1].lower()
        parent_tok = parts[-2].lower() if len(parts) >= 2 else ""
        chosen = model_scan_bundles(file_tok) or model_scan_bundles(parent_tok)
        if not chosen:
            chosen = [bundle_with_file(names, t, "model")
                      for t in (file_tok, parent_tok)]
            chosen = [n for n in chosen if n]
        if not chosen:
            model_gaps.append(f"{ref} ({prefab})")
        for name in chosen:
            scan.setdefault(name, f"model of {ref}")
    if model_gaps:
        fail(f"no cached bundle carries the monster prefabs (blocking gap): {model_gaps}")

    ai_groups = {as_int(r.get("aiGroup"), "aiGroup") for r in rows_of.values()}
    ai_fields = fields["AiGroupTable"]
    ai_proj_rows = base.load_data("AiGroupTable")["rows"]
    ai_mob_rows = base.mobile_rows(src, "AiGroupTable")
    akey = lambda r: ((as_int(r.get("aiGroup"), "aiGroup"), as_int(r.get("aiGrade"), "aiGrade"))
                      if r.get("aiGroup") is not None else None)
    ai_proj = dup_guard(ai_proj_rows, akey, ai_fields, "AiGroupTable (project)")
    ai_mob = dup_guard(ai_mob_rows, akey, ai_fields, "AiGroupTable (mobile)")
    for g in sorted(ai_groups):
        nodes = {r.get("aiBaseNodeName") for r in list(ai_proj.values()) + list(ai_mob.values())
                 if as_int(r.get("aiGroup"), "aiGroup") == g
                 and isinstance(r.get("aiBaseNodeName"), str) and r.get("aiBaseNodeName")}
        for node in sorted(nodes):
            bundle = "_".join(p.lower() for p in node.strip("/").split("/")[:-1])
            if bundle in names and os.path.exists(bundle_file(bundle)):
                scan.setdefault(bundle, f"ai base node of group {g}")

    skill_fields = fields["MonsterSkillTable"]
    skill_proj_rows = base.load_data("MonsterSkillTable")["rows"]
    skill_mob_rows = base.mobile_rows(src, "MonsterSkillTable")
    skill_proj = dup_guard(skill_proj_rows, lambda r: r.get("monsterSkillIndex"), skill_fields,
                           "MonsterSkillTable (project)")
    skill_mob = dup_guard(skill_mob_rows, lambda r: r.get("monsterSkillIndex"), skill_fields,
                          "MonsterSkillTable (mobile)")
    skill_rows_by_base = {}
    for r in list(skill_proj.values()) + list(skill_mob.values()):
        s = r.get("monsterSkillIndexString")
        if isinstance(s, str) and s:
            skill_rows_by_base.setdefault(HASH_SUFFIX.sub("", s).lower(), []).append(r)

    streams = dict(triggers)
    skill_refs = set()
    for name in sorted(scan):
        if name not in streams:
            streams[name] = read_unityfs.load(bundle_file(name))
        skill_refs |= {m.decode() for m in RAW_SKILL.findall(streams[name])}
    resolved_rows = []
    orphans = []
    for ref in sorted(skill_refs):
        rows = skill_rows_by_base.get(HASH_SUFFIX.sub("", ref).lower())
        if rows:
            resolved_rows.extend(rows)
        else:
            orphans.append(ref)

    skills = set()
    bases = set()
    for row in rows_of.values():
        skills |= skill_indexes(row)
        for k, v in row.items():
            if re.fullmatch(r"skill\d+IndexString", k) and isinstance(v, str) and v:
                bases.add(HASH_SUFFIX.sub("", v).lower())
    for row in resolved_rows:
        idx = as_int(row.get("monsterSkillIndex"), "monsterSkillIndex")
        if idx:
            skills.add(idx)
        s = row.get("monsterSkillIndexString")
        if isinstance(s, str) and s:
            bases.add(HASH_SUFFIX.sub("", s).lower())
    for r in list(skill_proj.values()) + list(skill_mob.values()):
        s = r.get("monsterSkillIndexString")
        if isinstance(s, str) and HASH_SUFFIX.sub("", s).lower() in bases:
            idx = as_int(r.get("monsterSkillIndex"), "monsterSkillIndex")
            if idx:
                skills.add(idx)
    skills = {s for s in skills if s}
    gap = sorted(s for s in skills if s not in skill_proj and s not in skill_mob)
    if gap:
        fail(f"MonsterSkillTable: skill ids in neither the project tables nor the mobile source: "
             f"{gap}")
    skill_append = [skill_mob[s] for s in sorted(skills) if s not in skill_proj]

    growth_types = {as_int(r.get("growthType"), "growthType") for r in rows_of.values()}
    growth_fields = fields["MonsterGrowthTable"]
    growth_proj_rows = base.load_data("MonsterGrowthTable")["rows"]
    growth_mob_rows = base.mobile_rows(src, "MonsterGrowthTable")
    have_types = ({as_int(r.get("growthType"), "growthType") for r in growth_proj_rows}
                  | {as_int(r.get("growthType"), "growthType") for r in growth_mob_rows})
    gap = sorted(growth_types - have_types)
    if gap:
        fail(f"MonsterGrowthTable: growthType {gap} in neither the project tables nor the "
             f"mobile source")
    growth_proj = dup_guard(growth_proj_rows, lambda r: r.get("monsterGrowthIndex"),
                            growth_fields, "MonsterGrowthTable (project)")
    growth_mob = dup_guard(growth_mob_rows, lambda r: r.get("monsterGrowthIndex"),
                           growth_fields, "MonsterGrowthTable (mobile)")
    growth_append = [r for r in growth_mob_rows
                     if as_int(r.get("growthType"), "growthType") in growth_types
                     and r.get("monsterGrowthIndex") not in growth_proj]

    ltypes = {as_int(r.get("levelStatType"), "levelStatType") for r in rows_of.values()}
    lstat_fields = fields["MonsterLevelStatTable"]
    lkey = lambda r: ((as_int(r.get("levelStatType"), "levelStatType"),
                       as_int(r.get("monsterLevel"), "monsterLevel"))
                      if r.get("levelStatType") is not None else None)
    lstat_proj_rows = base.load_data("MonsterLevelStatTable")["rows"]
    lstat_mob_rows = base.mobile_rows(src, "MonsterLevelStatTable")
    lstat_proj = dup_guard(lstat_proj_rows, lkey, lstat_fields,
                           "MonsterLevelStatTable (project)")
    lstat_mob = dup_guard(lstat_mob_rows, lkey, lstat_fields,
                          "MonsterLevelStatTable (mobile)")
    need_lstat = {(t, l) for t in ltypes for l in levels}
    gap = sorted(p for p in need_lstat if p not in lstat_proj and p not in lstat_mob)
    if gap:
        fail(f"MonsterLevelStatTable: (levelStatType, level) {gap} in neither the project tables "
             f"nor the mobile source")
    lstat_append = [r for r in lstat_mob_rows
                    if lkey(r) in need_lstat and lkey(r) not in lstat_proj]

    need_ai = {(g, grade) for g in ai_groups for grade in grades}
    gap = sorted(p for p in need_ai if p not in ai_proj and p not in ai_mob)
    if gap:
        fail(f"AiGroupTable: (aiGroup, aiGrade) {gap} in neither the project tables nor the "
             f"mobile source")
    ai_append = [r for r in ai_mob_rows if akey(r) in need_ai and akey(r) not in ai_proj]

    divergent = []
    for label, proj, mob, wanted, allowed in (
            ("MonsterTable", proj_rows, mob_rows,
             {as_int(r.get("monsterIndex"), "monsterIndex") for r in rows_of.values()},
             mon_fields),
            ("MonsterSkillTable", skill_proj, skill_mob, skills, skill_fields),
            ("MonsterGrowthTable", growth_proj, growth_mob,
             {k for k, r in list(growth_proj.items()) + list(growth_mob.items())
              if as_int(r.get("growthType"), "growthType") in growth_types},
             growth_fields),
            ("MonsterLevelStatTable", lstat_proj, lstat_mob, need_lstat, lstat_fields),
            ("AiGroupTable", ai_proj, ai_mob, need_ai, ai_fields)):
        for k in sorted(wanted, key=str):
            if k in proj and k in mob and not same_row(proj[k], mob[k], allowed):
                divergent.append(f"{label} {k}")

    for table, key_field, rows_add in (
            ("MonsterTable", "monsterIndex", mon_append),
            ("MonsterSkillTable", "monsterSkillIndex", skill_append),
            ("MonsterGrowthTable", "monsterGrowthIndex", growth_append),
            ("MonsterLevelStatTable", "monsterLevelStatIndex", lstat_append),
            ("AiGroupTable", "aiGroupIndex", ai_append)):
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
    tags = {v for rows_add in (mon_append, skill_append, growth_append, lstat_append, ai_append)
            for r in rows_add for k, v in r.items() if k.endswith("Tag") and isinstance(v, str)}
    no_text = sorted(t for t in tags if t not in strings and t not in texts)

    counts = {table: len(base.merge(schema, table, rows_add, key, src,
                                    ["MonsterTable"] if table == "MonsterTable"
                                    else ["MonsterSkillTable"] if table == "MonsterSkillTable"
                                    else []))
              for table, key, rows_add in (
                  ("MonsterTable", "monsterIndex", mon_append),
                  ("MonsterSkillTable", "monsterSkillIndex", skill_append),
                  ("MonsterGrowthTable", "monsterGrowthIndex", growth_append),
                  ("MonsterLevelStatTable", "monsterLevelStatIndex", lstat_append),
                  ("AiGroupTable", "aiGroupIndex", ai_append))}
    print(" | ".join(f"{t} +{n}" for t, n in counts.items()))
    print(f"bundle-level superset (no monster is attributed to a specific stage): "
          f"{len(refs)} refs over {len(triggers)} trigger bundles -> {len(mon_append)} unique "
          f"monster rows to append; grades {grades}, levels {levels}")
    print(f"skill closure: {len(skills)} ids ({len(bases)} linked bases, every '#N' the source "
          f"or the project carries); {len(skill_refs)} Skill.* refs scanned from "
          f"{len(scan)} bundles ({sum(1 for v in scan.values() if v.startswith('model'))} model, "
          f"{sum(1 for v in scan.values() if v.startswith('ai'))} ai, "
          f"{sum(1 for v in scan.values() if v.startswith('trigger'))} trigger)")
    if orphans:
        print(f"skill refs with no MonsterSkillTable row in any source (declared absent, "
              f"not invented): {len(orphans)} (first: {orphans[:4]})")
    if divergent:
        print(f"divergent keys kept from the project tables, mobile row not merged over it: "
              f"{len(divergent)} (e.g. {divergent[:5]})")
    if no_text:
        print(f"strings: {len(no_text)} tags carry no text in any source and stay absent, like "
              f"the project's other MonsterSkillTable rows (first: {no_text[:3]})")


if __name__ == "__main__":
    main()
