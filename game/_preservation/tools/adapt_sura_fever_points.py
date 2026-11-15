"""Derive Sura Fever extraValue candidates from existing Daruma rows (offline reconstruction).

The original Sura extraValue master data is unavailable in this package. The maintainer has
explicitly authorized closest-original ADAPTATIONS when the original is missing, reusing
EXISTING Fever weights from the live game's own Daruma rows with an honest label:
  type 1 (normal)  <- extraValue of Daruma rows 910029/910031/910032/910034 and 915 equivalents
  type 2 (upper)   <- extraValue of Daruma rows 910030/910033 and 915 equivalents
  type 3 (boss)    <- upper weight (EXPLICIT adaptation; no original Sura source exists)
Weights are only derived from those rows -- never invented. Everything else in MonsterTable
(791 other rows, max gauge 10000, triggers, stats, AI) is untouched: only the extraValue key
of monsterIndex 560001..560023 is added.

Default mode is a read-only report of the missing originals. Candidate generation REQUIRES
--fallback-from-daruma and --output (a path outside the repository and outside the client
cache; never in-place masters). Existing nonzero equal extraValue is idempotent; a different
nonzero value aborts. The output is a full candidate table for root review -- nothing here
installs, rebuilds or patches anything.

usage: adapt_sura_fever_points.py [--data DIR] [--fallback-from-daruma] [--output FILE]
"""
import argparse
import json
import os
import sys

SURA_IDS = range(560001, 560024)
DARUMA_TYPE1 = (910029, 910031, 910032, 910034, 915029, 915031, 915032, 915034)
DARUMA_TYPE2 = (910030, 910033, 915030, 915033)
ADAPTATION_NOTE = ("Sura extraValue adapted from Daruma Fever weights (maintainer-authorized "
                   "fallback); original Sura values unavailable")


def find_data_dir(explicit):
    """Portable repo resolution: --data wins, else walk up from this script until a checkout
    marker (AGENTS.md + _preservation/server/tables/data) is found. Works both from a TEMP
    folder (falls back to error, telling the user to pass --data) and from <repo>/tools/."""
    if explicit:
        return explicit
    cur = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        if os.path.isfile(os.path.join(cur, "AGENTS.md")):
            for prefix in ("game", ""):
                cand = os.path.join(cur, prefix, "_preservation", "server", "tables", "data")
                if os.path.isdir(cand):
                    return cand
        cur = os.path.dirname(cur)
    return None


def load_table(data_dir):
    with open(os.path.join(data_dir, "MonsterTable.json"), encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict) or not isinstance(doc.get("rows"), list):
        raise SystemExit("error: MonsterTable.json has no rows list")
    return doc


def index_rows(rows):
    idx, dupes = {}, []
    for row in rows:
        if not isinstance(row, dict):
            raise SystemExit("error: MonsterTable row must be an object")
        mid = row.get("monsterIndex")
        if type(mid) is not int or mid <= 0:
            raise SystemExit(f"error: invalid monsterIndex {mid!r}")
        if mid in idx:
            dupes.append(mid)
        idx[mid] = row
    return idx, dupes


def derive_weights(idx):
    """Weights come only from the named Daruma rows; every listed row must exist, carry a
    positive int extraValue, and agree within its type group -- otherwise abort."""
    weights = {}
    for mtype, source_ids in ((1, DARUMA_TYPE1), (2, DARUMA_TYPE2)):
        values = []
        for sid in source_ids:
            row = idx.get(sid)
            if row is None:
                raise SystemExit(f"error: source Daruma row {sid} missing from MonsterTable")
            val = row.get("extraValue")
            if not isinstance(val, int) or isinstance(val, bool) or val <= 0:
                raise SystemExit(f"error: source row {sid} has invalid extraValue {val!r}")
            values.append((sid, row.get("monsterType"), val))
        types = {t for _, t, _ in values}
        vals = {v for _, _, v in values}
        if types != {mtype}:
            raise SystemExit(f"error: type {mtype} source rows disagree on monsterType: {values}")
        if len(vals) != 1:
            raise SystemExit(f"error: type {mtype} source rows disagree on extraValue: {values}")
        weights[mtype] = next(iter(vals))
    return weights


def main():
    ap = argparse.ArgumentParser(description="Sura Fever extraValue adaptation (candidate only)")
    ap.add_argument("--data", help="tables/data dir (default: resolve repo relative to this script)")
    ap.add_argument("--fallback-from-daruma", action="store_true",
                    help="required to generate a candidate; default is a read-only report")
    ap.add_argument("--output", help="candidate MonsterTable.json path (required with the flag; "
                                     "must be outside the repo and client cache)")
    args = ap.parse_args()

    data_dir = find_data_dir(args.data)
    if not data_dir:
        raise SystemExit("error: could not locate the repo tables/data dir; pass --data DIR")
    doc = load_table(data_dir)
    rows = doc["rows"]
    idx, dupes = index_rows(rows)
    if dupes:
        raise SystemExit(f"error: duplicate monsterIndex rows: {sorted(set(dupes))[:10]}")
    if len(rows) != 814:
        raise SystemExit(f"error: expected 814 rows (791 + 23 Sura), found {len(rows)}")

    weights = derive_weights(idx)
    mapping = {}
    for sid in SURA_IDS:
        row = idx.get(sid)
        if row is None:
            raise SystemExit(f"error: Sura row {sid} missing from MonsterTable")
        mtype = row.get("monsterType")
        if type(mtype) is not int or mtype not in (1, 2, 3):
            raise SystemExit(f"error: Sura row {sid} has unexpected monsterType {mtype!r}")
        mapping[sid] = weights[2] if mtype == 3 else weights[mtype]

    missing = [sid for sid in SURA_IDS if "extraValue" not in idx[sid]]
    conflicts = []
    for sid, want in mapping.items():
        have = idx[sid].get("extraValue", 0)
        if isinstance(have, int) and not isinstance(have, bool):
            if have == 0:
                continue
            if have != want:
                conflicts.append((sid, have, want))
        else:
            conflicts.append((sid, have, want))

    report = {
        "mode": "readonly-report" if not args.fallback_from_daruma else "candidate",
        "source": {"type1": {"ids": list(DARUMA_TYPE1), "extraValue": weights[1]},
                   "type2": {"ids": list(DARUMA_TYPE2), "extraValue": weights[2]}},
        "mapping": {"type1->": weights[1], "type2->": weights[2],
                    "type3->": weights[2], "type3Note": "explicit adaptation, not original"},
        "sura": {"count": len(mapping), "missingExtraValue": len(missing),
                 "presentZero": sum("extraValue" in idx[sid] and idx[sid]["extraValue"] == 0
                                    for sid in SURA_IDS),
                 "conflicts": conflicts},
        "limitation": "original Sura extraValue unavailable; Daruma-derived adaptation",
        "adaptation": ADAPTATION_NOTE,
    }
    if conflicts:
        report["aborted"] = "existing nonzero extraValue differs from derived weight"
    print(json.dumps(report, indent=1))

    if not args.fallback_from_daruma:
        print("readonly report only; pass --fallback-from-daruma (and --output) for a candidate")
        return
    if conflicts:
        raise SystemExit("error: aborting -- existing nonzero extraValue conflicts (see report)")
    if not args.output:
        raise SystemExit("error: --output is required with --fallback-from-daruma")
    out = os.path.realpath(args.output)

    def repo_root_above(path):
        cur = os.path.realpath(path)
        for _ in range(10):
            if os.path.isfile(os.path.join(cur, "AGENTS.md")) and any(os.path.isdir(
                    os.path.join(cur, prefix, "_preservation", "server", "tables", "data"))
                    for prefix in ("game", "")):
                return cur
            nxt = os.path.dirname(cur)
            if nxt == cur:
                return None
            cur = nxt
        return None

    forbidden = {r for r in (repo_root_above(data_dir),
                             repo_root_above(os.path.dirname(os.path.abspath(__file__)))) if r}
    input_master = os.path.realpath(os.path.join(data_dir, "MonsterTable.json"))
    # catch an --output that lands inside ANY KOF checkout, even when --data lives in a
    # sandbox TEMP dir unrelated to the script location: probe upward from the output itself
    probe = os.path.dirname(out)
    for _ in range(10):
        nxt = os.path.dirname(probe)
        if nxt == probe:
            break
        if (os.path.isfile(os.path.join(probe, "AGENTS.md"))
                and (os.path.isdir(os.path.join(probe, "game", "_preservation", "server"))
                     or os.path.isdir(os.path.join(probe, "_preservation", "server")))):
            forbidden.add(probe)
            break
        probe = nxt
    for root in forbidden:
        try:
            inside = os.path.commonpath([out, root]) == root
        except ValueError:
            inside = False
        if inside:
            raise SystemExit(f"error: --output must live outside the repo/cache ({root}), "
                             f"refusing {out}")
    if out == input_master or os.path.dirname(out) == os.path.realpath(data_dir):
        raise SystemExit(f"error: --output must not overwrite the masters in place "
                         f"({data_dir}), refusing {out}")

    patched = 0
    for row in rows:
        mid = row.get("monsterIndex")
        if mid in mapping:
            row["extraValue"] = mapping[mid]
            patched += 1
    if patched != 23:
        raise SystemExit(f"error: patched {patched} rows, expected 23")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print(f"candidate written: {out} (patched extraValue on 23 Sura rows only)")


if __name__ == "__main__":
    main()
