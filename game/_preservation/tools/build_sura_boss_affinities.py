"""Deterministic stdlib patcher: Tier-1 Sura boss synastry AFFINITY values (visual parity).

Root-proven motivation (TEMP evidence native-analysis/root-sura-tier1-affinity-visual.json,
root screenshot): the 2020 original videos (https://www.youtube.com/watch?v=-ezlyZN4Plw,
boss HUD icons at ~170/299/467/618/767/907 s) show Tier-1 bosses Iori=Blue, Leona=Red,
Yashiro=Green, Chris=Yellow, Shermie=Purple, Darkness=White. With the client enum
SynastryTypeChange_Buff.SubTypes 1..6 = A..F (dump.cs 382515; Purple=1, Blue=2, Red=3,
Green=4, Yellow=5, White=6 per the visual cross-check) the intended per-stage values are
[2, 3, 4, 5, 1, 6]. The master today carries [2, 3, 2, 4, 2, 5] (stages 3 and 5 duplicate
Blue), and the native MonsterManager affinity override renders e.g. Yashiro blue even though
his clone MonsterTable row is White(6) -- an adaptation gap, not a data-recovery claim.

Scope is EXACTLY four fields in server/tables/data/QuestEventStageTable.json:
setSynastryBossMonsterValue of questEventStageIndex 3800103=4, 3800104=5, 3800105=1,
3800106=6. Rows 3800101/02 (2/3) and every other row/key (normal/elite/dungeonType/...) are
byte-preserved: the table must round-trip byte-identically through json indent=1 with CRLF
and no trailing newline before any patch is planned, and the structural diff must list
exactly those four (row, field) pairs. Unexpected current values (someone edited by hand,
partial application) are REFUSED; the fully-applied state is reported idempotent.

Default is analysis only (dry-run report of the planned diff). --apply is explicit and
guarded: it requires the game (ALLSTAR.exe) and the local server port 18080 to be CLOSED
(both checked without relying on python -X utf8; tasklist bytes are decoded with
errors="replace"), writes a scope-limited backup (only QuestEventStageTable.json) into a NEW
system-temp directory that is never deleted, then writes the patched table and re-reads +
re-validates it (idempotent, round-trip, four-field diff). ROOT is derived from this file's
location (tools/ -> _preservation), no user path is hardcoded, no new dependencies.

usage: python build_sura_boss_affinities.py            # dry-run analysis (default)
       python build_sura_boss_affinities.py --apply    # guarded patch + backup + re-verify
"""
import argparse
import copy
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # tools/ -> game/_preservation
TABLE_REL = os.path.join("server", "tables", "data", "QuestEventStageTable.json")
FIELD = "setSynastryBossMonsterValue"
TIER1_IDS = list(range(3800101, 3800107))
BASELINE = {3800101: 2, 3800102: 3, 3800103: 2, 3800104: 4, 3800105: 2, 3800106: 5}
PLAN = {3800103: 4, 3800104: 5, 3800105: 1, 3800106: 6}
GAME_EXE = "ALLSTAR.exe"
SERVER_PORT = 18080


def canonical_bytes(data):
    """Table formatting contract: json indent=1, CRLF line endings, no trailing newline."""
    return json.dumps(data, indent=1, ensure_ascii=False).replace("\n", "\r\n").encode("utf-8")


def load_table(path):
    with open(path, "rb") as f:
        raw = f.read()
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise SystemExit("tabela não é o documento {_comment, rows} esperado: %s" % path)
    if canonical_bytes(data) != raw:
        raise SystemExit("tabela não reproduz byte a byte com indent=1/CRLF/sem newline "
                         "final; recusando garantir diff mínimo")
    return raw, data


def rows_by_id(data):
    out = {}
    for row in data["rows"]:
        rid = row.get("questEventStageIndex")
        if rid in TIER1_IDS:
            out.setdefault(rid, []).append(row)
    return out


def classify(data):
    """baseline -> patchable; applied -> idempotent; anything else (mixed, hand-edited,
    duplicated/missing rows) -> refused."""
    by_id = rows_by_id(data)
    for rid in TIER1_IDS:
        if len(by_id.get(rid, [])) != 1:
            return "refused", {"reason": "questEventStageIndex %d aparece %d vezes"
                               % (rid, len(by_id.get(rid, [])))}
    values = {}
    for rid in TIER1_IDS:
        row = by_id[rid][0]
        if FIELD not in row:
            return "refused", {"reason": "%d não tem o campo %s" % (rid, FIELD)}
        values[rid] = row[FIELD]
    if values == {**BASELINE, **PLAN}:
        return "applied", {"values": values}
    if values != BASELINE:
        return "refused", {"reason": "valores atuais inesperados %r (esperava baseline %r "
                         "ou aplicado %r; estado editado à mão não é patcheado)"
                         % (values, BASELINE, {**BASELINE, **PLAN})}
    return "baseline", {"values": values}


def plan_diff(data):
    """Structural diff of the ONLY change this tool may make; anything else aborts."""
    patched = copy.deepcopy(data)
    by_id = rows_by_id(patched)
    changes = []
    for rid, value in sorted(PLAN.items()):
        row = by_id[rid][0]
        old = row[FIELD]
        row[FIELD] = value
        changes.append({"questEventStageIndex": rid, FIELD: {"old": old, "new": value}})
    stray = []
    for old_row, new_row in zip(data["rows"], patched["rows"]):
        if old_row is not new_row and old_row != new_row:
            for key in old_row:
                if old_row.get(key) != new_row.get(key) and \
                        not (old_row.get("questEventStageIndex") in PLAN and key == FIELD):
                    stray.append((old_row.get("questEventStageIndex"), key))
    return patched, changes, stray


def game_running():
    try:
        proc = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                              timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit("guarda: não consegui enumerar processos (%s); recusando" % exc)
    if proc.returncode != 0:
        raise SystemExit("guarda: tasklist falhou (código %d); recusando" % proc.returncode)
    text = proc.stdout.decode("utf-8", errors="replace")
    return next((line.split('","')[0].strip('"') for line in text.splitlines()
                 if GAME_EXE.lower() in line.lower()), None)


def server_port_open(port=SERVER_PORT):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1.0)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Tier-1 Sura boss affinity patch "
                                             "(4 fields; default dry-run)")
    ap.add_argument("--table", default=os.path.join(ROOT, TABLE_REL),
                    help="table path (default: derived from this tool's location)")
    ap.add_argument("--apply", action="store_true",
                    help="explicit: guarded write with scoped backup and re-verification")
    args = ap.parse_args(argv)

    raw, data = load_table(args.table)
    state, info = classify(data)
    report = {"table": os.path.abspath(args.table), "bytes": len(raw), "state": state,
              "info": info, "plan": PLAN, "changes": [], "applied": False, "backup": None,
              "refusal": info.get("reason") if state == "refused" else None}
    if state == "refused":
        print(json.dumps(report, indent=1))
        return 2
    if state == "applied":
        report["changes"] = [{"questEventStageIndex": rid, FIELD: {"old": BASELINE[rid],
                                                                  "new": PLAN[rid]}}
                             for rid in sorted(PLAN)]
        print(json.dumps(report, indent=1))
        return 0

    patched, changes, stray = plan_diff(data)
    report["changes"] = changes
    if stray:
        report["refusal"] = "plano toca mais que os quatro campos %s: %r" % (FIELD, stray)
        print(json.dumps(report, indent=1))
        return 2
    new_bytes = canonical_bytes(patched)
    if new_bytes.count(b"\r\n") != raw.count(b"\r\n"):
        report["refusal"] = "contagem de linhas mudou; recusando diff não mínimo"
        print(json.dumps(report, indent=1))
        return 2
    if not args.apply:
        report["dryRun"] = True
        print(json.dumps(report, indent=1))
        return 0

    game = game_running()
    if game:
        report["refusal"] = "guarda: jogo %s está aberto; feche antes de aplicar" % game
        print(json.dumps(report, indent=1))
        return 2
    if server_port_open():
        report["refusal"] = "guarda: porta %d do servidor local está aberta; feche antes de " \
                            "aplicar" % SERVER_PORT
        print(json.dumps(report, indent=1))
        return 2

    backup_dir = tempfile.mkdtemp(prefix="sura-boss-affinity-backup-")
    backup_path = os.path.join(backup_dir, "QuestEventStageTable.json.orig")
    shutil.copyfile(args.table, backup_path)
    report["backup"] = backup_path
    with open(args.table, "wb") as f:
        f.write(new_bytes)
    re_raw, re_data = load_table(args.table)
    re_state, _ = classify(re_data)
    _, re_changes, re_stray = plan_diff(re_data)
    recheck = {"roundTrip": canonical_bytes(re_data) == re_raw, "state": re_state,
               "idempotentNext": re_state == "applied", "stray": re_stray}
    report["recheck"] = recheck
    report["applied"] = (recheck["roundTrip"] and recheck["stray"] == []
                         and len(re_changes) == 4)
    with open(os.path.join(backup_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print(json.dumps(report, indent=1))
    return 0 if report["applied"] else 2


if __name__ == "__main__":
    sys.exit(main())
