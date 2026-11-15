"""Adapt the BuffSelect AiGroupTable rows 840..845 to what the PC client really loads.

Reverse-engineering adaptation, guarded table edit only -- no asset is created or verified here
(the coordinator's alias/preflight step owns that). The PC cause is proven and SCOPED to the
spawned prefab's folder: GetMonster (0x181761E60) only routes a Prefabs/Character/ prefab to
CharacterManager.CreateCharacter<CharacterInitializer_Boss> (MonsterType==4, 0x3AB66E0) or
<CharacterInitializer_Monster> (0x3AB66D0), and BOTH of those SetAI (0x181092170 / 0x1810954E0)
append StringDefine.BehaviourTreePath_Mob ("_Mob") to the AiGroupTable base node before loading
the graph. A Prefabs/Monster/ prefab keeps MonsterInitializer_AI, whose SetAI (0x1810A2280)
loads the base AS-IS -- the suffix rule applies to Character-rooted spawns only, never to every
monster. Two consequences this tool fixes inside the table:

  1. The six legacy grade-1 rows (aiGroupIndex 8401..8451) were reconstructed pointing at
     Prefabs/AI/GuildCoop/ai_outer_god_3_3 (840) / ai_outer_god_3_4 (the rest) with no
     aiOperationValue. They are restored to the oracle's original Prefabs/AI/BuffSelect/* path
     and aiOperationValue 1.0; the LOCAL aiGroupIndex and every other field stay verbatim.
  2. Group 845's bosses are Character-rooted fighters, and its original base is
     BuffSelect_FighterBoss_Mob: with the PC's appended suffix the runtime would ask for
     BuffSelect_FighterBoss_Mob_Mob, which exists nowhere, while the PC-cached
     prefabs_ai_buffselect already ships the same graph as BuffSelect_FighterBoss_Mob. So every
     existing 845 row's base becomes Prefabs/AI/BuffSelect/BuffSelect_FighterBoss (the suffix
     completes it). Group 843 stays BuffSelect_Goenitz_1_Normal -- its Character-rooted Goenitz
     boss needs the Goenitz_Mob alias the coordinator provides separately (asset and runtime
     still pending), and substituting a fighter or GuildCoop is never an option. Group 842's
     four Red bosses spawn through Prefabs/Monster/ prefabs, so MonsterInitializer_AI loads
     BuffSelect_MonsterBoss as-is: no alias is needed or requested, and the row keeps the oracle
     path exactly as imported -- like 840/841/844, which are guarded to stay exact.

The oracle is mobile-ref-running's AiGroupTable keyed by (aiGroup, aiGrade); both mobile
references agree on 840..845. It is EXTERNAL INPUT and is validated as such: every consumed
pair's aiBaseNodeName must be a non-empty string under Prefabs/AI/BuffSelect/ and its
aiOperationValue a real number (the source's 1.0) -- anything else aborts before any write;
a silent None is never generated. Only pairs that already exist locally are touched -- no
grade is added, no other group changes. Each row must sit in a known state: its current
aiBaseNodeName equal to the oracle original, the already-adapted target, or (grade 1 only)
the known GuildCoop legacy value; anything else aborts before any write, as do duplicate
(aiGroup, aiGrade) pairs, a duplicate aiGroupIndex ANYWHERE in the table (a 840..845 target
colliding with another group's index included), a missing aiOperationValue outside the six
legacy rows, an unknown aiOperationValue, or any field the oracle does not carry. Nothing is
invented: paths and the 1.0 come from the oracle.

usage: adapt_buffselect_pc_ai.py [--data DIR] [--src ORACLE_TABEL_DIR] [--check]
  --data   tables data dir holding AiGroupTable.json (default: the project's master tables;
           staging dirs for review runs)
  --src    oracle tabel/ dir (default: the mobile-ref-running reference next to the checkout)
  --check  run the full preflight and report, writing nothing
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, "..", "server", "tables", "data"))
SRC = os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", "mobile-ref-running",
                                    "kofas_server", "server", "tabel"))
TABLE = "AiGroupTable"
GROUPS = range(840, 846)
GUILDCOOP_LEGACY = {840: "Prefabs/AI/GuildCoop/ai_outer_god_3_3"}   # every other legacy grade-1
GUILDCOOP_DEFAULT = "Prefabs/AI/GuildCoop/ai_outer_god_3_4"         # row points here today
STRIP_MOB_GROUPS = (845,)   # original base ends in _Mob; the PC appends _Mob again at load
KEY_FIELDS = ("aiGroup", "aiGrade")


class Divergence(Exception):
    pass


def oracle_pairs(src):
    path = os.path.join(src, TABLE + ".json")
    if not os.path.isfile(path):
        raise Divergence("oracle %s missing" % path)
    out = {}
    for r in json.load(open(path, encoding="utf-8")).get("baris", []):
        key = (r.get("aiGroup"), r.get("aiGrade"))
        if key[0] not in GROUPS:
            continue
        if key in out:
            raise Divergence("oracle carries duplicate (aiGroup, aiGrade) pair %s -- refusing" % (key,))
        out[key] = r
    return out


def target_path(group, src_path):
    """The base the PC should carry: the oracle path (already validated as a real BuffSelect
    string), minus a trailing _Mob for the groups whose original base already ends in it (the
    runtime appends _Mob back and loads the same graph)."""
    if group in STRIP_MOB_GROUPS and src_path.endswith("_Mob"):
        return src_path[:-len("_Mob")]
    return src_path


def preflight(rows, oracle):
    """[(row, field, old, new)] still to apply, guarding everything first: duplicate
    (aiGroup, aiGrade) pairs inside 840..845, a duplicate aiGroupIndex ANYWHERE in the table
    (one of the six groups colliding with another group's index included), unknown pairs,
    oracle rows that are not a real BuffSelect AI path with a real number operation value,
    unknown paths, wrong/missing aiOperationValue and unexpected fields abort before any
    write; a row already sitting on its target (a re-run) demands nothing."""
    local, by_index = {}, {}
    for r in rows:
        idx = r.get("aiGroupIndex")
        key = (r.get("aiGroup"), r.get("aiGrade"))
        if idx is not None:
            if idx in by_index:
                raise Divergence("duplicate aiGroupIndex %r on %s and %s -- refusing"
                                 % (idx, by_index[idx], key))
            by_index[idx] = key
        if r.get("aiGroup") not in GROUPS:
            continue
        if key in local:
            raise Divergence("duplicate (aiGroup, aiGrade) pair %s -- refusing" % (key,))
        local[key] = r
    pending = []
    for key in sorted(local, key=lambda k: (k[0], k[1] if k[1] is not None else -1)):
        row = local[key]
        if key not in oracle:
            raise Divergence("%s: pair %s exists locally but not in the oracle -- refusing"
                             % (TABLE, key))
        src_row = oracle[key]
        src_path = src_row.get("aiBaseNodeName")
        if not isinstance(src_path, str) or not src_path.startswith("Prefabs/AI/BuffSelect/"):
            raise Divergence("%s %s: oracle aiBaseNodeName %r is not a non-empty string under "
                             "Prefabs/AI/BuffSelect/ -- refusing" % (TABLE, key, src_path))
        want_op = src_row.get("aiOperationValue")
        if isinstance(want_op, bool) or not isinstance(want_op, (int, float)):
            raise Divergence("%s %s: oracle aiOperationValue %r is not a real number -- "
                             "refusing" % (TABLE, key, want_op))
        want_path = target_path(key[0], src_path)
        for field, want in (("aiGroup", key[0]), ("aiGrade", key[1])):
            if row.get(field) != want:
                raise Divergence("%s %s: %s %r disagrees with the pair -- refusing"
                                 % (TABLE, key, field, row.get(field)))
        extra = set(src_row) - {"aiGroupIndex", "aiBaseNodeName", "aiOperationValue",
                                "aiGroup", "aiGrade"}
        if extra:
            raise Divergence("%s %s: oracle carries unexpected field %r -- refusing"
                             % (TABLE, key, sorted(extra)))
        extra = set(row) - {"aiGroupIndex", "aiBaseNodeName", "aiOperationValue",
                            "aiGroup", "aiGrade"}
        if extra:
            raise Divergence("%s %s: local row carries unexpected field %r -- refusing"
                             % (TABLE, key, sorted(extra)))
        current = row.get("aiBaseNodeName")
        legacy = (GUILDCOOP_LEGACY.get(key[0], GUILDCOOP_DEFAULT) if key[1] == 1 else None)
        if current == want_path:
            pass                                            # already adapted: nothing to do
        elif current == src_path:
            pending.append((row, "aiBaseNodeName", current, want_path))
        elif current == legacy:
            pending.append((row, "aiBaseNodeName", current, want_path))
        else:
            raise Divergence("%s %s: aiBaseNodeName %r is neither the oracle original %r, the "
                             "PC target %r nor the known GuildCoop legacy %r -- refusing to guess"
                             % (TABLE, key, current, src_path, want_path, legacy))
        op = row.get("aiOperationValue")
        if op is None:
            if current == legacy:
                pending.append((row, "aiOperationValue", None, want_op))
            else:
                raise Divergence("%s %s: aiOperationValue missing outside the six legacy "
                                 "grade-1 rows -- refusing" % (TABLE, key))
        elif op != want_op:
            raise Divergence("%s %s: aiOperationValue %r is neither the oracle %r nor the "
                             "legacy absence -- refusing" % (TABLE, key, op, want_op))
    return pending


def adapt_current_master(data=DATA, src=SRC):
    """Adapt AiGroupTable.json in place: full preflight before any write; the file is rewritten
    (same dump format as import_dungeons.save_data) only when something changed."""
    path = os.path.join(data, TABLE + ".json")
    doc = json.load(open(path, encoding="utf-8"))
    pending = preflight(doc["rows"], oracle_pairs(src))
    for row, field, old, new in pending:
        row[field] = new
    if pending:
        json.dump(doc, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return pending


def main():
    parser = argparse.ArgumentParser(description="Adapt the BuffSelect AiGroupTable rows 840..845 "
                                                 "to the PC's _Mob-suffix reality (see docstring)")
    parser.add_argument("--data", default=DATA, help="tables data dir (default: project master)")
    parser.add_argument("--src", default=SRC, help="oracle tabel/ dir (default: mobile-ref-running)")
    parser.add_argument("--check", action="store_true", help="preflight only; write nothing")
    args = parser.parse_args()
    try:
        if args.check:
            doc = json.load(open(os.path.join(args.data, TABLE + ".json"), encoding="utf-8"))
            pending = preflight(doc["rows"], oracle_pairs(args.src))
        else:
            pending = adapt_current_master(args.data, args.src)
    except (Divergence, OSError, ValueError) as e:
        print("adapt_buffselect_pc_ai: aborting, nothing written: %s" % e, file=sys.stderr)
        return 1
    if not pending:
        print("adapt_buffselect_pc_ai: %s already adapted, nothing to do" % TABLE)
        return 0
    for row, field, old, new in pending:
        print("adapt_buffselect_pc_ai: %s (%s,%s) %s %s -> %s%s"
              % (TABLE, row.get("aiGroup"), row.get("aiGrade"), field, old, new,
                 "" if not args.check else " (check only)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
