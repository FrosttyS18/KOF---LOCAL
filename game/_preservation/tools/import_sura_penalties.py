"""Stage the Sura Dungeon penalty closure for the project tables -- ONLY a staging copy; the master
tables are never written here.

The 24 Sura stages carry a targetConditionMainGroupIndex each (1001..1024, derived from the project's
SuraDungeonStageTable on every run, never hardcoded). The whole chain is client-side combat data:
Scene_Single_SuraDungeon's SetSuraDungeonPanelty reads the stage row's group, SuraTargetConditionChecker
matches the deck against PenaltyTable of the same targetConditionGroupIndex (every Sura row is
targetConditionType 2 with a per-stage targetConditionSubType CP requirement -- strings_en.json
Sura.Penalty.Desc: "Fighters below {Power} CP: ATK -0.5% per 1% CP short (max -40%)"), and
SetPaneltyBuff(level) applies PenaltyBuffTable's debuff of the group: buff 63000001 (BuffTable
"Sura Penalty: ATK Down", attack_reduce, -0.005 power per level of 80 = the -40% cap) at the level the
CP shortfall earns. The server APIs never see any of it; the client just needs the tables in its packs.

This writes the output folder (default tools/out_sura_penalties) for the maintainer/Codex to apply:
full new master-format files for tables the project lacks (PenaltyTable, PenaltyBuffTable) and
additions files for tables it has (BuffTable rows, strings_en entries) plus a manifest recording
sources, origin and counts. Applying = copy the new files into server/tables/data, append the
additions, then tools/build_tables.py + tools/make_tablepacks.py and a server/game restart.

Preflight guards, all before any write (an aborted run leaves the output folder untouched):
- the mobile source must exist; rows come from its principal tabel/ first, falling back to the
  cadangan_tabel/ backup copy with the origin recorded -- a table absent in both aborts, and the two
  disagreeing on a needed group's row aborts naming it (no silent pick);
- every group the stages reference must be covered by both penalty tables in the source: a partial
  community source is reported, never padded;
- every group's buff must exist in the source BuffTable when the project tables lack it; a buff in
  neither place aborts;
- the PC schema must carry each table and rows are filtered to its fields;
- a key already in the project tables with different content aborts as a collision; identical content
  is an idempotent no-op. The buff and string closure reads every consumed group row -- the project's
  own where already applied, the source's for the rest -- so a partial apply (penalties in, buff or
  texts still out) heals instead of declaring the closure complete; a fully applied closure stages
  nothing.

usage: import_sura_penalties.py <kofas_server folder> [--data DIR] [--out DIR]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # the embedded python's _pth never adds the script's own folder
import import_dungeons as base   # read-only helpers only: fields_of/load_data/mobile_rows/mobile_texts

STAGES = "SuraDungeonStageTable"
GROUP_COLUMNS = ("targetConditionMainGroupIndex", "targetConditionSubGroupIndex")
GROUP_COLUMN = "targetConditionGroupIndex"
PENALTY_TABLES = (("PenaltyTable", "targetConditionIndex"), ("PenaltyBuffTable", "targetConditionBuffIndex"))
BUFF_TABLE, BUFF_KEY = "BuffTable", "buffIndex"
TEXT_TABLES = ("PenaltyStringTable", "BuffTable", "SystemTable")
OUT_DEFAULT = os.path.join(HERE, "out_sura_penalties")


def strict_int(value, what):
    """Protocol ints: real ints and integer-valued strings pass; anything else aborts, never a silent 0."""
    if isinstance(value, bool) or not (isinstance(value, int) or
                                       (isinstance(value, str) and value.strip().lstrip("+-").isdigit())):
        sys.exit("!! %s: not an integer (%r)" % (what, value))
    return int(value)


def by_key(rows, key, table):
    """Rows by key; duplicate keys must be identical (first wins), a conflict aborts."""
    by = {}
    for r in rows:
        k = strict_int(r.get(key), "%s.%s" % (table, key))
        if k in by and by[k] != r:
            sys.exit("!! %s: conflicting rows under %s %d" % (table, key, k))
        by.setdefault(k, r)
    return by


def stage_groups():
    """The targetCondition groups the project's Sura stages reference (sub column: 0/absent = none)."""
    groups = {}
    for r in base.load_data(STAGES)["rows"]:
        for col in GROUP_COLUMNS:
            g = r.get(col) or 0
            if g:
                groups.setdefault(strict_int(g, "%s.%s of stage %r" % (STAGES, col, r.get("suraDungeonStageIndex"))),
                                  []).append(int(r.get("suraDungeonStageIndex") or 0))
    if not groups:
        sys.exit("!! no targetCondition groups in the project's %s" % STAGES)
    return groups


def source_rows(src, table, key):
    """-> (rows by key, origin); principal tabel/ first, the cadangan backup recorded as fallback."""
    loaded = []
    for sub, origin in (("tabel", "principal"), (os.path.join("cadangan_tabel"), "backup")):
        rows = base.mobile_rows(src if sub == "tabel" else os.path.join(src, sub), table)
        if rows:
            loaded.append((by_key(rows, key, table), origin))
    if not loaded:
        sys.exit("!! %s absent in both the principal tabel/ and the cadangan backup of the source" % table)
    return loaded


def penalty_table(src, schema, table, key, groups):
    """One penalty table staged: group coverage, principal==backup, schema fields, master collisions."""
    if table not in schema["tables"]:
        sys.exit("!! PC schema has no %s" % table)
    loaded = source_rows(src, table, key)
    by_group = {}
    for r in loaded[0][0].values():
        g = strict_int(r.get(GROUP_COLUMN), "%s.%s" % (table, GROUP_COLUMN))
        if g in by_group and by_group[g] != r:
            sys.exit("!! %s: conflicting rows for group %d" % (table, g))
        by_group.setdefault(g, r)
    if len(loaded) > 1:
        backup = {strict_int(r.get(GROUP_COLUMN), "%s.%s" % (table, GROUP_COLUMN)): r
                  for r in loaded[1][0].values()}
        for g in sorted(groups):
            if by_group.get(g) != backup.get(g):
                sys.exit("!! %s: principal and backup disagree on group %d" % (table, g))
    gap = sorted(g for g in groups if g not in by_group)
    if gap:
        sys.exit("!! %s: no row for group(s) %s -- the community source is partial, nothing staged"
                 % (table, gap))
    allowed = base.fields_of(schema, table)
    master = by_key(base.load_data(table)["rows"], key, table)
    rows, consumed = [], []
    for g in sorted(groups):
        row = {k: v for k, v in by_group[g].items() if k in allowed}
        k = strict_int(row.get(key), "%s.%s" % (table, key))
        if k in master:
            if master[k] != row:
                sys.exit("!! %s: key %d already in the project tables with different content" % (table, k))
            consumed.append(master[k])   # the project's own row is the one the client reads
            continue                     # identical: already applied, an idempotent no-op
        rows.append(row)
        consumed.append(row)
    return table, rows, consumed, loaded[0][1], len(master)


def stage_buffs(src, schema, consumed_penalty_buffs):
    """BuffTable rows the penalty buffs need and the project tables lack. The closure reads every
    consumed PenaltyBuffTable row of the stage groups (the project's own where applied, the source's
    for the rest), so a partial apply -- penalties in, buff out -- still heals instead of passing."""
    needed = {strict_int(r.get("targetConditionPenaltyBuffIndex"), "PenaltyBuffTable buff index")
              for r in consumed_penalty_buffs}
    master = by_key(base.load_data(BUFF_TABLE)["rows"], BUFF_KEY, BUFF_TABLE)
    missing = sorted(needed - set(master))
    consumed = [master[b] for b in sorted(needed) if b in master]
    if not missing:
        return [], consumed, "already present", needed
    if BUFF_TABLE not in schema["tables"]:
        sys.exit("!! PC schema has no %s" % BUFF_TABLE)
    loaded = source_rows(src, BUFF_TABLE, BUFF_KEY)
    by = loaded[0][0]
    gap = [b for b in missing if b not in by]
    if gap:
        sys.exit("!! BuffTable: no row for buff(s) %s in either source" % gap)
    if len(loaded) > 1:
        for b in missing:
            if loaded[1][0].get(b) != by.get(b):
                sys.exit("!! BuffTable: principal and backup disagree on buff %d" % b)
    allowed = base.fields_of(schema, BUFF_TABLE)
    staged = [{k: v for k, v in by[b].items() if k in allowed} for b in missing]
    return staged, consumed + staged, loaded[0][1], needed


def stage_strings(src, consumed_rows):
    """Texts the consumed rows' tags reference (applied and newly staged alike): added when some source
    carries them, reported when none, never overwriting an existing string."""
    strings = json.load(open(os.path.join(base.DATA, "strings_en.json"), encoding="utf-8"))
    tags = sorted({v for r in consumed_rows for k, v in r.items() if k.endswith("Tag") and isinstance(v, str)}
                  - set(strings))
    texts = {}
    for t in TEXT_TABLES:
        texts.update(base.mobile_texts(src, t))
    add = {t: texts[t] for t in tags if t in texts}
    return add, [t for t in tags if t not in texts]


def main():
    ap = argparse.ArgumentParser(description="stage the Sura penalty closure (never writes the master tables)")
    ap.add_argument("src", help="kofas_server folder (tabel/ + cadangan_tabel/ + tabel_teks/)")
    ap.add_argument("--data", default=base.DATA, help="project tables data dir (default: the server's)")
    ap.add_argument("--out", default=OUT_DEFAULT, help="staging dir to write (default: tools/out_sura_penalties)")
    args = ap.parse_args()
    base.DATA = args.data
    if not os.path.isdir(os.path.join(args.src, "tabel")):
        sys.exit("usage: import_sura_penalties.py <kofas_server folder> [--data DIR] [--out DIR]")

    schema = json.load(open(base.SCHEMA, encoding="utf-8"))
    groups = stage_groups()
    penalties = [penalty_table(args.src, schema, t, k, groups) for t, k in PENALTY_TABLES]
    buffs, buff_consumed, buff_origin, needed_buffs = stage_buffs(args.src, schema, penalties[1][2])
    strings_add, strings_missing = stage_strings(
        args.src, [r for _t, _new, consumed, _o, _m in penalties for r in consumed] + buff_consumed)

    docs = []
    for table, rows, _consumed, origin, master_count in penalties:
        if not rows:
            continue
        docs.append(("%s.%s.json" % (table, "additions" if master_count else "rows"),
                     {"_comment": "real mobile table (tools/import_sura_penalties.py; %s for the project's "
                                  "server/tables/data/%s.json)" % ("additions" if master_count else
                                                                  "the full file, a new master table", table),
                      "rows": rows}))
    if buffs:
        docs.append(("BuffTable.additions.json",
                     {"_comment": "rows to append to the project's server/tables/data/BuffTable.json "
                                  "(tools/import_sura_penalties.py)", "rows": buffs}))
    if strings_add:
        docs.append(("strings_en.additions.json",
                     {"_comment": "entries to merge into the project's server/tables/data/strings_en.json "
                                  "(tools/import_sura_penalties.py)", "entries": strings_add}))
    if not docs:
        print("already applied: every penalty row, buff and string is in the project tables; nothing staged")
        return

    os.makedirs(args.out, exist_ok=True)
    for name, doc in docs:
        json.dump(doc, open(os.path.join(args.out, name), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    json.dump({"groups": {"count": len(groups), "derived_from": "server/tables/data/%s.json %s"
                                                        % (STAGES, list(GROUP_COLUMNS)),
                          "stages": {str(g): s for g, s in sorted(groups.items())}},
               "tables": [{"table": t, "rows": len(rows), "consumed": len(consumed), "origin": origin,
                           "master_rows_before": master}
                          for t, rows, consumed, origin, master in penalties],
               "buffs": {"needed": sorted(needed_buffs), "staged": [r[BUFF_KEY] for r in buffs],
                         "origin": buff_origin},
               "strings": {"added": strings_add, "no_text_anywhere": strings_missing},
               "apply": ["copy PenaltyTable.rows.json and PenaltyBuffTable.rows.json into "
                         "server/tables/data as PenaltyTable.json / PenaltyBuffTable.json, and append the "
                         "additions files to the tables that already exist",
                         "run tools/build_tables.py, then tools/make_tablepacks.py",
                         "restart the server and the game"],
               "source": os.path.abspath(args.src)},
              open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)

    for table, rows, _consumed, origin, master_count in penalties:
        if rows:
            print("%s: %d rows staged (%s) from %s" % (table, len(rows),
                                                       "additions" if master_count else "new file", origin))
    print("BuffTable: +%d row(s) %s from %s" % (len(buffs), [r[BUFF_KEY] for r in buffs], buff_origin))
    print("strings: +%d, %d without text anywhere (reported, not invented)"
          % (len(strings_add), len(strings_missing)))
    print("staged %d file(s) + manifest.json in %s" % (len(docs), args.out))


if __name__ == "__main__":
    main()
