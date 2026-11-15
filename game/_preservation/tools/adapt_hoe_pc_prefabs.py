"""Point the two Hall of Elements Monster-prefab elites at their Character prefab roots.

Reverse-engineering adaptation, not a recovered original value. The PC HighComedown trigger
graphs spawn every element's first-wave elite with MonsterSpawnType 9 (TagIn), and the spawn
coroutine only finishes when the real Animator enters the Tag_In state: ShowSpawnAnimation
yields WaitUntil(IsPlaying(27)) and only then calls MonsterActive (0x181767710). The monster
animation stack cannot do that -- MonsterAnimationController.Initialize loads the controller
whose ScriptString literal 0x3AA6018 names "KOFMonsterController", and that asset (bundle
prefabs_controller) carries no Tag_In state, no TagAction sub-state machine and no Tag_In
transition; the character stack's literal 0x3AA6180 names "KOFCharacterController", which has
Battle_Layer.TagAction.Tag_In. So an elite on a Prefabs/Monster root stays enable=false forever
after ChangeState(27) leaves the Animator in Idle_Battle, and the wave's ConditionSurveyLeftGroup
gate -- behaving correctly -- never releases. The three working elements' elites already carry
Character prefab roots in MonsterTable; only Green's Yuri (530015) and Yellow's King (530018)
carry Monster roots, exactly the two battles that stall. This tool rewrites only those two rows'
monsterPrefab to the same Character root convention ("Prefabs/Character/<Fighter>/<Fighter>",
root GameObject present in the cached prefabs_character_<fighter> bundle). monsterIndex/
IndexString, monsterType, aiGroup, stats, skills, growth and every other row stay untouched;
the graphs, gates, AI and difficulty are not modified.

Pending follow-up this tool does NOT do: import_dungeons.close_hoe_skill_chains now follows
each row's effective monsterPrefab (fixed alongside the 15 master rows), so the Character
skill chains are closed, but adapt_rows is not yet wired into the main import flow -- until
that integration lands, a fresh mobile re-import would reintroduce the Monster roots.

usage: adapt_hoe_pc_prefabs.py [--data DIR] [--cache DIR] [--check]
  --data   tables data dir holding MonsterTable.json (default: the project's master tables;
           staging dirs for review runs)
  --cache  the client cache root with assetbundles/ and assetbundles.info (default: the
           project's)
  --check  run the full preflight and report, writing nothing
"""
import argparse
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import read_unity_serialized

DATA = os.path.normpath(os.path.join(HERE, "..", "server", "tables", "data"))
CACHE = os.path.abspath(os.path.join(HERE, "..", "..", "storage", "cache"))
TABLE = "MonsterTable"

ADAPTATIONS = [
    {"monsterIndex": 530015, "monsterIndexString": "Monster.Yuri.Elite.HighComedown",
     "oldPrefab": "Prefabs/Monster/Yuri/Yuri", "newPrefab": "Prefabs/Character/Yuri/Yuri"},
    {"monsterIndex": 530018, "monsterIndexString": "Monster.King.Elite.HighComedown",
     "oldPrefab": "Prefabs/Monster/King/King", "newPrefab": "Prefabs/Character/King/King"},
]


class Divergence(Exception):
    pass


def bundle_of_prefab(path):
    parts = path.split("/")
    return "_".join(parts[:-1]).lower() if len(parts) > 1 else None


def bundle_file(cache, name):
    return os.path.join(cache, "assetbundles", hashlib.md5(name.encode()).hexdigest())


def bundle_manifest(cache):
    with open(os.path.join(cache, "assetbundles.info"), "rb") as f:
        d = f.read()
    i, names = 0, set()
    while i + 4 <= len(d):
        n = struct.unpack_from("<i", d, i)[0]
        name = d[i + 4:i + 4 + n].decode()
        i += 4 + n
        n2 = struct.unpack_from("<i", d, i)[0]
        val = d[i + 4:i + 4 + n2].decode()
        i += 4 + n2
        if len(val) == 32:
            names.add(name)
    return names


def check_bundle_asset(cache, manifest, prefab):
    """The Character root is the bundle's main GameObject: the container only lists the
    sub-prefabs, so the root is verified through the canonical serialized-file parser as a
    real GameObject whose m_Name equals the prefab's last path segment -- a matching name in
    a clip or loose string proves nothing."""
    name = bundle_of_prefab(prefab)
    root = prefab.split("/")[-1]
    if name not in manifest:
        raise Divergence("%s: bundle %r missing from assetbundles.info" % (prefab, name))
    path = bundle_file(cache, name)
    if not os.path.isfile(path):
        raise Divergence("%s: bundle file %r not cached" % (prefab, path))
    _, gameobjects, _, _, _ = read_unity_serialized.index_bundle(path)
    if not any(g.get("name") == root for g in gameobjects.values()):
        raise Divergence("%s: root GameObject %r not found in bundle %r" % (prefab, root, name))


def preflight(rows, cache=None, manifest=None):
    """Guard every adaptation against the wrong table: exact row count, monsterIndex and
    monsterIndexString must match, the current monsterPrefab must be the mobile Monster root
    or already the adapted Character root (idempotent re-runs), and each target bundle must
    be cached with its exact root asset. Returns the changes still to apply."""
    pending = []
    for a in ADAPTATIONS:
        hits = [r for r in rows if r.get("monsterIndex") == a["monsterIndex"]]
        if len(hits) != 1:
            raise Divergence("monsterIndex %d: expected exactly one row, found %d"
                             % (a["monsterIndex"], len(hits)))
        row = hits[0]
        if row.get("monsterIndexString") != a["monsterIndexString"]:
            raise Divergence("monsterIndex %d: IndexString %r != %r"
                             % (a["monsterIndex"], row.get("monsterIndexString"),
                                a["monsterIndexString"]))
        current = row.get("monsterPrefab")
        if current == a["oldPrefab"]:
            pending.append((row, a))
        elif current != a["newPrefab"]:
            raise Divergence("monsterIndex %d: monsterPrefab %r is neither the mobile %r nor "
                             "the adapted %r -- refusing to guess"
                             % (a["monsterIndex"], current, a["oldPrefab"], a["newPrefab"]))
    if cache is not None:
        for a in ADAPTATIONS:
            check_bundle_asset(cache, manifest, a["newPrefab"])
    return pending


def adapt_rows(rows, cache=None, manifest=None):
    """Apply the adaptation to a row list (usable on the mobile source rows before a merge
    or on the project table's rows); returns [(monsterIndex, old, new)] actually changed."""
    changed = []
    for row, a in preflight(rows, cache, manifest):
        row["monsterPrefab"] = a["newPrefab"]
        changed.append((a["monsterIndex"], a["oldPrefab"], a["newPrefab"]))
    return changed


def adapt_current_master(data=DATA, cache=CACHE):
    """Adapt MonsterTable.json in place: full preflight before any write, and the file is
    rewritten (same dump format as import_dungeons.save_data) only when something changed."""
    path = os.path.join(data, TABLE + ".json")
    doc = json.load(open(path, encoding="utf-8"))
    pending = preflight(doc["rows"], cache, bundle_manifest(cache))
    if not pending:
        return []
    for row, a in pending:
        row["monsterPrefab"] = a["newPrefab"]
    json.dump(doc, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return [(a["monsterIndex"], a["oldPrefab"], a["newPrefab"]) for row, a in pending]


def main():
    parser = argparse.ArgumentParser(description="Adapt the two Monster-prefab HoE elites to "
                                                 "their Character prefab roots (see module docstring)")
    parser.add_argument("--data", default=DATA, help="tables data dir (default: project master)")
    parser.add_argument("--cache", default=CACHE, help="client cache root (default: project cache)")
    parser.add_argument("--check", action="store_true", help="preflight only; write nothing")
    args = parser.parse_args()
    try:
        if args.check:
            doc = json.load(open(os.path.join(args.data, TABLE + ".json"), encoding="utf-8"))
            pending = [(a["monsterIndex"], a["oldPrefab"], a["newPrefab"])
                       for row, a in preflight(doc["rows"], args.cache, bundle_manifest(args.cache))]
        else:
            pending = adapt_current_master(args.data, args.cache)
    except (Divergence, OSError, ValueError) as e:
        print("adapt_hoe_pc_prefabs: aborting, nothing written: %s" % e, file=sys.stderr)
        return 1
    if not pending:
        print("adapt_hoe_pc_prefabs: %s already adapted, nothing to do" % TABLE)
    for index, old, new in pending:
        print("adapt_hoe_pc_prefabs: %s %d %s -> %s%s"
              % (TABLE, index, old, new, "" if not args.check else " (check only)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
