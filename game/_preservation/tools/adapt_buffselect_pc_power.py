"""Restore the BuffSelect dungeon buffs' power curve under the client's Max clamp (PC adaptation).

Native contract (FULL Ghidra C, root-reviewed turn 178; log ghidra-buffpower-full.log):
BuffBase.get_MergeValue (0x1809CC080, raw 0x9CA680) returns
Round(mod0*Base + mod1 + Base + (Level-1)*PerLv, 5) and BuffBase.get_Value (0x1809CBEF0, raw
0x9CA4F0) returns addValues[1] + stack*merge -- then CLAMPS against sv_buffPowerMax
(BuffProto+0x28): the positive branch keeps MIN(value, Max) and the negative branch keeps
MAX(value, Max). The root's cached-holder proof (cached-buff-power-v1026.json) shows the loaded
1026 BuffTable carries svBase=svPerLv=0.05 for 64000010 with **Max=0** -- protobuf default --
so every positive pick clamps to 0 and every negative pick raises to 0. That, not the value
pipeline, is the proven cause of the measured 0.0.

The fix uses only numbers already in each row: fold buffPowerBase := buffPowerPerLv (first
pick already grants PerLv; curve PerLv*level at stack 1) and set
buffPowerMax := buffPowerPerLv * buffMaxLevel -- the cap exactly at the row's own maximum
level (positive picks maxLevel 20 -> caps 0.6..2.4; the three negative curses maxLevel 1 ->
cap -0.1, so their negative branch MAX keeps the debuff instead of raising it to 0). No rate,
level, duration or any other field is rebalanced or invented. (64000010's subtype 51 is
critical rate, not defense.)

Accepted states, all validated before a single byte is written: fresh original (base 0, max
absent or 0 -- the protobuf default), the interim 1026 fold (base == perLv, max absent or 0),
and the complete adaptation (base == perLv and max == perLv*maxLevel -- a no-op re-run).
Anything else aborts: unknown base or max, max sign disagreeing with the derived cap, a
non-finite number, an invalid buffMaxLevel (must be an integer >= 1), a missing referenced
row, a duplicate, or a row whose buffIndexString is not under "Buff.BuffSelect." (an unrelated
table row sharing the index is never adapted).

usage: adapt_buffselect_pc_power.py [--data DIR]
  --data  tables data dir (default: the project's master; staging dirs for review runs)
"""
import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, "..", "server", "tables", "data"))
REF_TABLE = "BuffSelectDungeonBuffTable"
TABLE = "BuffTable"
REF_FIELD = "buffIndex"


class Divergence(Exception):
    pass


def referenced_buffs(data=DATA):
    """buffIndex values the dungeon's own table references -- the only rows ever touched."""
    path = os.path.join(data, REF_TABLE + ".json")
    if not os.path.isfile(path):
        raise Divergence("%s missing from %s" % (REF_TABLE, data))
    out = set()
    for r in json.load(open(path, encoding="utf-8"))["rows"]:
        v = r.get(REF_FIELD)
        if v is None or v == "":
            continue
        try:
            out.add(int(v))
        except (TypeError, ValueError):
            raise Divergence("%s: %s %r is not an integer" % (REF_TABLE, REF_FIELD, v))
    if not out:
        raise Divergence("%s references no %s at all" % (REF_TABLE, REF_FIELD))
    return out


def preflight_rows(rows, data=DATA):
    """Validated view of `rows` against the referenced set: {buffIndex: row} plus the changes
    each referenced row still needs ([(buffIndex, perLv, maxCap)]; [] when every row already
    carries the complete adaptation). Raises Divergence on any unknown state -- the importer
    runs this over current rows + planned mobile rows so a divergence aborts BEFORE any table
    is written."""
    wanted = referenced_buffs(data)
    hits = {}
    for r in rows:
        idx = r.get("buffIndex")
        if isinstance(idx, int) and idx in wanted:
            if idx in hits:
                raise Divergence("%s: duplicate buffIndex %d" % (TABLE, idx))
            hits[idx] = r
    missing = sorted(wanted - set(hits))
    if missing:
        raise Divergence("%s: referenced buffs missing from %s: %s" % (TABLE, TABLE, missing))
    pending = []
    for idx in sorted(hits):
        row = hits[idx]
        tag = row.get("buffIndexString")
        per_lv = row.get("buffPowerPerLv")
        base = row.get("buffPowerBase")
        max_lv = row.get("buffMaxLevel")
        cur_max = row.get("buffPowerMax", 0)
        if not isinstance(tag, str) or not tag.startswith("Buff.BuffSelect."):
            raise Divergence("%s %d: buffIndexString %r is not a Buff.BuffSelect.* row -- "
                             "an unrelated buff shares the index, refusing" % (TABLE, idx, tag))
        for name, v in (("buffPowerPerLv", per_lv), ("buffPowerBase", base),
                        ("buffPowerMax", cur_max)):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise Divergence("%s %d: %s %r is not a finite number" % (TABLE, idx, name, v))
        if per_lv == 0:
            raise Divergence("%s %d: buffPowerPerLv is 0 -- the dungeon's picks include "
                             "debuffs, so only zero is invalid" % (TABLE, idx))
        if isinstance(max_lv, bool) or not isinstance(max_lv, int) or max_lv < 1:
            raise Divergence("%s %d: buffMaxLevel %r is not an integer >= 1 -- the cap is "
                             "derived from it, refusing" % (TABLE, idx, max_lv))
        cap = per_lv * max_lv
        base_ok = base in (0, per_lv)
        max_ok = cur_max in (0, cap)
        if not base_ok and not max_ok:
            raise Divergence("%s %d: buffPowerBase %r and buffPowerMax %r are both unknown "
                             "(fresh is base 0/max 0; interim base==perLv/max 0; adapted "
                             "base==perLv/max==perLv*maxLevel=%r)" % (TABLE, idx, base, cur_max, cap))
        if base not in (0, per_lv):
            raise Divergence("%s %d: buffPowerBase %r is neither 0 (fresh/interim) nor %r "
                             "(adapted) -- refusing to guess" % (TABLE, idx, base, per_lv))
        if cur_max not in (0, cap):
            raise Divergence("%s %d: buffPowerMax %r is neither the protobuf default 0 nor "
                             "the derived cap %r (perLv %r * buffMaxLevel %d) -- refusing"
                             % (TABLE, idx, cur_max, cap, per_lv, max_lv))
        if base == per_lv and cur_max == cap:
            continue
        pending.append((idx, per_lv, cap))
    return hits, pending


def mutate_tables(data=DATA):
    """[(buffIndex, perLv, maxCap)] of the referenced rows still needing the fold; [] when the
    complete adaptation is already in place. Raises Divergence before any write on divergence."""
    path = os.path.join(data, TABLE + ".json")
    doc = json.load(open(path, encoding="utf-8"))
    hits, pending = preflight_rows(doc["rows"], data)
    for idx, per_lv, cap in pending:
        hits[idx]["buffPowerBase"] = per_lv
        hits[idx]["buffPowerMax"] = cap
    if pending:
        json.dump(doc, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return pending


def main():
    ap = argparse.ArgumentParser(description="fold BuffSelect buff power base:=perLv and "
                                             "max:=perLv*maxLevel under the client's clamp "
                                             "(see module docstring for the native contract)")
    ap.add_argument("--data", default=DATA, help="tables data dir (default: project master)")
    args = ap.parse_args()
    try:
        changed = mutate_tables(args.data)
    except (Divergence, OSError, ValueError) as exc:
        print("adapt_buffselect_pc_power: aborting, nothing written: %s" % exc, file=sys.stderr)
        return 1
    if not changed:
        print("adapt_buffselect_pc_power: %s already adapted, nothing to do" % TABLE)
    for idx, per_lv, cap in changed:
        print("adapt_buffselect_pc_power: %s %d buffPowerBase := %r, buffPowerMax := %r "
              "(perLv*buffMaxLevel; clamped curve %r/level, cap %r)"
              % (TABLE, idx, per_lv, cap, per_lv, cap))
    return 0


if __name__ == "__main__":
    sys.exit(main())
