"""Adapt Phantom Tower (questEventIndex 107) floor UI for the PC client (v1025+).

Three visibility-only changes, all derived from real sources already on disk (nothing is
invented and no payment/API logic is touched):

1. CLEAR REWARDS preview. UIUnit_PhantomStageInfo.SetRewardItem (0x1807CA7B0) renders the
   floor preview exclusively from RewardDisplayTable.ListByDisplayGroup(stage.
   firstClearRewardDisplayGroup). The 50 floors (1070001..1070050) consume groups
   94100001..94100050; the PC master has no rows for them (empty preview) while the mobile
   reference tabel carries the real rows (F01 group 94100001: 6000 gold, 20 rubies,
   1 capsule goods 1003 -- exactly the real payout already proven in-game). This helper
   derives the consumed groups from the CURRENT QuestEventStageTable rows (questEventIndex
   107), fetches the exact matching source rows from the mobile RewardDisplayTable, filters
   each row to the authentic project schema (server/tables/schema.json ->
   tables.RewardDisplayTable.proto -> protos[proto].fields[].name, never a sample of
   existing rows), and appends them. Existing rows are never modified: a row with the same
   rewardDisplayIndex whose every schema field is equal is skipped (absent fields and
   protocol defaults 0/''/None compare equal per project tooling), one with any divergent
   non-default value aborts before any write; a missing group in the source, duplicate
   source ids, or id collisions abort as well.

2. Floor label tags. The client code requests the literal tag
   'System.Contents.BattlePower.MosterLevel.Name' (Netmarble's original 'Moster' typo,
   present in global-metadata.dat at 0x67dff) and, for levels above 90, the tag
   'System.MonsterLv.Awakened.Name' (ScriptString handle at RVA 0x3B21408, root-confirmed;
   both consumed by UIUnit_PhantomStageInfo.SetMonsterLevel 0x1807CB440). Neither key exists
   in the PC string table, so ByTag misses and the raw key leaks into the UI. This helper
   imports BOTH keys with their EXACT values from the primary text source
   (src/tabel_teks/SystemTable.json, 'teks' map): 'Lv. {0}' and 'Awakened Lv. {0}'.
   A key missing from the source, or already present locally with a divergent value,
   aborts before any write; a locally equal key is skipped (no-op).

3. Floor enemy level. UIUnit_PhantomStageInfo.SetData (0x1807CA280) resolves the floor's
   StageBalance row via get_StageBalanceIndex(stage) and SetMonsterLevel (0x1807CB440) reads
   StageBalanceProto._monsterLevel@0x1C4 (joined by the stage's singleStageBalanceIndex;
   the Tower floors join 1:1 to balances 3900001..3900050). The PC StageBalance rows carry
   no monsterLevel field, so the native label formats 0. This helper fills ONLY that field
   on the 50 Tower balance rows, using the level the same floor already uses in battle:
   QuestEventStage.monsterLevel of the joining stage (30..128 -- existing values, nothing
   invented or re-leveled). monsterOverallPoint (C.P.) is deliberately NOT touched: no real
   source value exists locally and recommendBattlePower is not equivalent; that value stays
   a declared gap. Preflight: the join must be unambiguous (exactly one balance row per
   target index, every stage level a positive integer, a balance shared by several Tower
   stages only when they agree on the level), and any locally known monsterLevel must be
   absent/0 (to fill) or already equal (to skip); a different value aborts before ANY write.
   All other StageBalance fields, rows and ids (including difficulty coups) are preserved.

The real payout rows are NOT touched: the PC RewardGroupTable already carries the 160 real
payout rows (rewardGroup 94100001..94100050, types {1:50, 2:50, 13:60} -- root-verified equal
to the source by Counter(type, goods, count)); only the display mirror was missing.
Everything else is out of scope (C.P. value, other StageBalance fields, stats, difficulty,
RewardGroupTable/API, other labels/files). All preflights run before a single byte is
written, files are rewritten only when something actually changes, with their original
CRLF/LF style and trailing-newline shape, so a second run is a byte-level no-op.

plan(data_dir, src_server_dir) builds and validates the full change set without writing;
adapt_current_master(data_dir, src_server_dir) applies it. CLI: --data DIR, --src SERVERDIR,
--check (plan and report only).
"""
import argparse
import json
import os
import sys

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "server", "tables", "data")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))), "mobile-ref-running", "kofas_server", "server")
QUEST_EVENT_INDEX = 107
STAGE_TABLE = "QuestEventStageTable.json"
DISPLAY_TABLE = "RewardDisplayTable.json"
STRINGS_TABLE = "strings_en.json"
BALANCE_TABLE = "StageBalanceTable.json"
STRINGS_SOURCE = os.path.join("tabel_teks", "SystemTable.json")
GROUP_FIELD = "firstClearRewardDisplayGroup"
ID_FIELD = "rewardDisplayIndex"
GROUP_KEY = "rewardDisplayGroup"
BALANCE_ID = "stageBalanceIndex"
BALANCE_JOIN = "singleStageBalanceIndex"
LEVEL_SOURCE = "monsterLevel"
STRING_KEYS = ("System.Contents.BattlePower.MosterLevel.Name", "System.MonsterLv.Awakened.Name")


class AdaptationError(RuntimeError):
    """Raised when the masters diverge from the known real table shapes."""


def _load(path):
    if not os.path.exists(path):
        raise AdaptationError("missing table file: %s" % path)
    return json.loads(open(path, "rb").read().decode("utf-8"))


def _dump_like(raw, data):
    """Serialize data with the byte shape of raw (indent 1, original line ending and
    trailing-newline presence)."""
    text = json.dumps(data, ensure_ascii=False, indent=1)
    eol = "\r\n" if raw.count(b"\r\n") * 2 > raw.count(b"\n") else "\n"
    text = text.replace("\n", eol)
    if raw.endswith(b"\n") and not text.endswith(eol):
        text += eol
    return text.encode("utf-8")


def _display_schema():
    """Field names of RewardDisplayProto from the project's real schema.json, resolved
    relative to this module (never from a staging data dir and never inferred from a sample
    of existing rows)."""
    path = os.path.join(os.path.dirname(DATA), "schema.json")
    if not os.path.exists(path):
        raise AdaptationError("missing project schema: %s" % path)
    doc = json.loads(open(path, "rb").read().decode("utf-8"))
    table = (doc.get("tables") or {}).get("RewardDisplayTable")
    proto = table.get("proto") if isinstance(table, dict) else None
    fields = ((doc.get("protos") or {}).get(proto) or {}).get("fields")
    if not isinstance(fields, list) or not fields:
        raise AdaptationError("schema.json has no RewardDisplayProto fields (proto %r)" % proto)
    names = {f.get("name", "").lstrip("_") for f in fields if isinstance(f, dict)}
    names.discard("")
    if ID_FIELD not in names or GROUP_KEY not in names:
        raise AdaptationError("RewardDisplayProto schema lacks %s/%s" % (ID_FIELD, GROUP_KEY))
    return names


def _defaultish(v):
    """Protocol default: absent/None, 0, 0.0 or '' (bools are values, not defaults)."""
    return v is None or (not isinstance(v, bool) and (v == 0 or v == ""))


def _fields_equal(a, b):
    """Equal outright, or both sides protocol defaults (absent field vs 0/''/None)."""
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    if a == b:
        return True
    return _defaultish(a) and _defaultish(b)


def _tower_stages(data_dir):
    rows = _load(os.path.join(data_dir, STAGE_TABLE)).get("rows")
    if not isinstance(rows, list):
        raise AdaptationError("%s has no rows list" % STAGE_TABLE)
    stages = [r for r in rows if isinstance(r, dict) and r.get("questEventIndex") == QUEST_EVENT_INDEX]
    if not stages:
        raise AdaptationError("no QuestEventStage rows with questEventIndex %d" % QUEST_EVENT_INDEX)
    return stages


def _consumed_groups(stages):
    groups = set()
    for r in stages:
        g = r.get(GROUP_FIELD)
        if not isinstance(g, int) or g <= 0:
            raise AdaptationError("stage %s has invalid %s: %r"
                                  % (r.get("questEventStageIndex"), GROUP_FIELD, g))
        groups.add(g)
    return sorted(groups)


def _balance_levels(stages, data_dir):
    """{balanceIndex: level} joined from the stages; validates the join unambiguously."""
    targets = {}
    for r in stages:
        b = r.get(BALANCE_JOIN)
        lvl = r.get(LEVEL_SOURCE)
        if isinstance(b, bool) or not isinstance(b, int) or b <= 0:
            raise AdaptationError("stage %s has invalid %s: %r"
                                  % (r.get("questEventStageIndex"), BALANCE_JOIN, b))
        if isinstance(lvl, bool) or not isinstance(lvl, int) or lvl <= 0:
            raise AdaptationError("stage %s has invalid %s: %r"
                                  % (r.get("questEventStageIndex"), LEVEL_SOURCE, lvl))
        prev = targets.get(b)
        if prev is not None and prev != lvl:
            raise AdaptationError("balance %r shared by stages with different %s (%d vs %d)"
                                  % (b, LEVEL_SOURCE, prev, lvl))
        targets[b] = lvl
    doc = _load(os.path.join(data_dir, BALANCE_TABLE))
    rows = doc.get("rows")
    if not isinstance(rows, list) or not rows:
        raise AdaptationError("%s has no rows list" % BALANCE_TABLE)
    by_index = {}
    for r in rows:
        idx = r.get(BALANCE_ID)
        if idx in targets:
            by_index.setdefault(idx, []).append(r)
    missing = [b for b in sorted(targets) if b not in by_index]
    if missing:
        raise AdaptationError("%s lacks balance rows %s" % (BALANCE_TABLE, missing[:5]))
    fills = {}
    for b in sorted(targets):
        if len(by_index[b]) != 1:
            raise AdaptationError("balance %r matched %d rows in %s (ambiguous join)"
                                  % (b, len(by_index[b]), BALANCE_TABLE))
        row = by_index[b][0]
        local = row.get(LEVEL_SOURCE)
        if local is None:
            fills[b] = targets[b]
        elif isinstance(local, bool) or not isinstance(local, int):
            raise AdaptationError("balance %r has non-integer %s %r (corrupt value; aborting)"
                                  % (b, LEVEL_SOURCE, local))
        elif local == 0:
            fills[b] = targets[b]
        elif local != targets[b]:
            raise AdaptationError("balance %r already has %s %r, target %d (unknown value; aborting)"
                                  % (b, LEVEL_SOURCE, local, targets[b]))
    return fills


def plan(data_dir, src_server_dir):
    """Build the full change set without writing anything.

    Returns {"stages", "groups", "new_rows", "skipped_equal", "string_adds",
    "balance_fills"}; raises AdaptationError on any divergence (missing source group,
    duplicate/colliding ids, changed existing row, missing/divergent source string,
    ambiguous balance join or unknown local level).
    """
    stages = _tower_stages(data_dir)
    groups = _consumed_groups(stages)
    wanted = set(groups)
    balance_fills = _balance_levels(stages, data_dir)

    pc_doc = _load(os.path.join(data_dir, DISPLAY_TABLE))
    pc_rows = pc_doc.get("rows")
    if not isinstance(pc_rows, list) or not pc_rows:
        raise AdaptationError("%s has no rows list" % DISPLAY_TABLE)
    schema = _display_schema()
    by_id = {}
    for r in pc_rows:
        by_id.setdefault(r.get(ID_FIELD), []).append(r)

    src_doc = _load(os.path.join(src_server_dir, "tabel", DISPLAY_TABLE))
    src_rows = src_doc.get("baris")
    if not isinstance(src_rows, list):
        raise AdaptationError("source %s has no baris list" % DISPLAY_TABLE)
    src_by_group = {}
    for r in src_rows:
        if r.get(GROUP_KEY) in wanted:
            src_by_group.setdefault(r[GROUP_KEY], []).append(r)
    missing = [g for g in groups if not src_by_group.get(g)]
    if missing:
        raise AdaptationError("source has no RewardDisplay rows for groups %s" % missing)

    new_rows, skipped, seen_ids = [], 0, set()
    for g in groups:
        for r in src_by_group[g]:
            rid = r.get(ID_FIELD)
            if not isinstance(rid, int):
                raise AdaptationError("source row for group %s has invalid %s: %r" % (g, ID_FIELD, rid))
            if rid in seen_ids:
                raise AdaptationError("source rows contain duplicate %s %r" % (ID_FIELD, rid))
            seen_ids.add(rid)
            row = {k: r[k] for k in schema if k in r}
            if ID_FIELD not in row:
                raise AdaptationError("source row %r has no %s after schema filter" % (rid, ID_FIELD))
            existing = by_id.get(rid)
            if existing:
                for other in existing:
                    diff = [k for k in sorted(schema)
                            if not _fields_equal(row.get(k), other.get(k))]
                    if diff:
                        raise AdaptationError("existing %s %r differs on %s" % (ID_FIELD, rid, diff))
                skipped += 1
                continue
            new_rows.append(row)
    new_rows.sort(key=lambda x: x[ID_FIELD])

    strings = _load(os.path.join(data_dir, STRINGS_TABLE))
    if not isinstance(strings, dict):
        raise AdaptationError("%s is not a string map" % STRINGS_TABLE)
    src_strings = _load(os.path.join(src_server_dir, STRINGS_SOURCE))
    teks = src_strings.get("teks") if isinstance(src_strings, dict) else None
    if not isinstance(teks, dict):
        raise AdaptationError("source %s has no teks map" % STRINGS_SOURCE)
    string_adds = {}
    for key in STRING_KEYS:
        value = teks.get(key)
        if not isinstance(value, str) or not value:
            raise AdaptationError("source %s lacks %s" % (STRINGS_SOURCE, key))
        local = strings.get(key)
        if local is not None and local != value:
            raise AdaptationError("%s already exists with divergent value %r (source %r)"
                                  % (key, local, value))
        if local is None:
            string_adds[key] = value

    return {"stages": len(stages), "groups": groups, "new_rows": new_rows,
            "skipped_equal": skipped, "string_adds": string_adds,
            "balance_fills": balance_fills}


def adapt_current_master(data_dir, src_server_dir):
    """Apply the plan; returns 'noop' when nothing changes, else 'adapted'. Writes only the
    three target files (RewardDisplay rows, the two strings, the balance levels), only when
    their content actually changes."""
    p = plan(data_dir, src_server_dir)
    if not p["new_rows"] and not p["string_adds"] and not p["balance_fills"]:
        return "noop"
    if p["new_rows"]:
        path = os.path.join(data_dir, DISPLAY_TABLE)
        raw = open(path, "rb").read()
        doc = json.loads(raw.decode("utf-8"))
        doc["rows"].extend(p["new_rows"])
        with open(path, "wb") as fh:
            fh.write(_dump_like(raw, doc))
    if p["string_adds"]:
        path = os.path.join(data_dir, STRINGS_TABLE)
        raw = open(path, "rb").read()
        doc = json.loads(raw.decode("utf-8"))
        doc.update(p["string_adds"])
        with open(path, "wb") as fh:
            fh.write(_dump_like(raw, doc))
    if p["balance_fills"]:
        path = os.path.join(data_dir, BALANCE_TABLE)
        raw = open(path, "rb").read()
        doc = json.loads(raw.decode("utf-8"))
        for r in doc["rows"]:
            lvl = p["balance_fills"].get(r.get(BALANCE_ID))
            if lvl is not None:
                r[LEVEL_SOURCE] = lvl
        with open(path, "wb") as fh:
            fh.write(_dump_like(raw, doc))
    return "adapted"


def main():
    parser = argparse.ArgumentParser(
        description="append Phantom Tower RewardDisplay rows and the MosterLevel typo string "
                    "(visibility only; no payments touched)")
    parser.add_argument("--data", default=DATA, help="tables data dir (default: project master)")
    parser.add_argument("--src", default=SRC, help="mobile reference server dir (default: sibling checkout)")
    parser.add_argument("--check", action="store_true", help="plan only; write nothing")
    args = parser.parse_args()
    try:
        p = plan(args.data, args.src)
    except (ValueError, KeyError, AdaptationError) as exc:
        print("plan failed: %s" % exc, file=sys.stderr)
        return 1
    print("stages: %d | groups: %d | new reward rows: %d | equal rows skipped: %d | strings to add: %d | balance levels to fill: %d"
          % (p["stages"], len(p["groups"]), len(p["new_rows"]), p["skipped_equal"],
             len(p["string_adds"]), len(p["balance_fills"])))
    if args.check:
        print("check only; nothing written")
        return 0
    try:
        status = adapt_current_master(args.data, args.src)
    except AdaptationError as exc:
        print("adapt failed: %s" % exc, file=sys.stderr)
        return 1
    print("noop; nothing written" if status == "noop" else "adapted: RewardDisplay +%d, strings +%d, StageBalance levels +%d"
          % (len(p["new_rows"]), len(p["string_adds"]), len(p["balance_fills"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
