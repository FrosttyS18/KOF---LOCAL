"""Point the two Hall of Elements Monster-prefab elites at the PC's fighter-NPC combo:
their Character prefab root plus the mode's FighterBoss AI group (706).

Reverse-engineering adaptation, not a recovered original value, in two steps the PC client
forces. (1) The PC HighComedown trigger graphs spawn every element's first-wave elite with
MonsterSpawnType 9 (TagIn), and the spawn coroutine only finishes when the real Animator
enters the Tag_In state: ShowSpawnAnimation yields WaitUntil(IsPlaying(27)) and only then
calls MonsterActive (0x181767710). MonsterAnimationController.Initialize loads the controller
whose ScriptString literal 0x3AA6018 names "KOFMonsterController" (bundle prefabs_controller),
which carries no Tag_In state, no TagAction sub-state machine and no Tag_In transition; the
character stack's literal 0x3AA6180 names "KOFCharacterController", which has
Battle_Layer.TagAction.Tag_In. So the elite needs its "Prefabs/Character/<Fighter>/<Fighter>"
root (root GameObject present in the cached prefabs_character_<fighter> bundle), the root the
other three elements' elites already carry. (2) CharacterInitializer_AI.SetAI (0x1810908E0)
appends StringDefine.BehaviourTreePath_Mob ("_Mob", dump.cs 26369) to the AiGroupTable base
node before AttachBehaviourTree, while MonsterInitializer_AI.SetAI (0x1810A2280) loads the
base node as-is; the PC ships _Mob AI graphs only for the fighter-as-NPC families, so aiGroup
702 (Elite_Short_Normal) asks for Elite_Short_Normal_Mob -- absent from prefabs_ai_elite --
and the ResourceLoad task hangs into DATA DOWNLOAD HAS FAILED before combat. aiGroup 706
(FighterBoss_Normal) resolves to FighterBoss_Normal_Mob, present in
prefabs_ai_fighterboss_normal as a NodeCanvas MonoBehaviour: the warrior-NPC AI class the same
mode's three working elites already use. This tool rewrites only those two rows'
monsterPrefab and aiGroup; monsterIndex/IndexString, monsterType, aiGrade and every stat,
skill, growth and drop field stay untouched, and AiGroupTable itself is never edited.

import_dungeons runs preflight over the effective master rows and adapt_rows over the mobile
source rows of every Hall of Elements import, so the normal import keeps the master adapted.

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
AI_GROUP_PREFAB = "Prefabs/AI/FighterBoss/Normal/FighterBoss_Normal"
AI_ASSET = AI_GROUP_PREFAB.split("/")[-1] + "_Mob"

ADAPTATIONS = [
    {"monsterIndex": 530015, "monsterIndexString": "Monster.Yuri.Elite.HighComedown",
     "oldPrefab": "Prefabs/Monster/Yuri/Yuri", "newPrefab": "Prefabs/Character/Yuri/Yuri",
     "oldAiGroup": 702, "newAiGroup": 706},
    {"monsterIndex": 530018, "monsterIndexString": "Monster.King.Elite.HighComedown",
     "oldPrefab": "Prefabs/Monster/King/King", "newPrefab": "Prefabs/Character/King/King",
     "oldAiGroup": 702, "newAiGroup": 706},
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


def check_ai_asset(cache, manifest):
    """The AI graph is a NodeCanvas MonoBehaviour, not a GameObject: the target is verified
    through the canonical parser's monobehaviour map (mbs[name]) of the bundle the runtime
    derives from the group's base node (Prefabs/AI/FighterBoss/Normal/FighterBoss_Normal +
    StringDefine.BehaviourTreePath_Mob)."""
    bundle = bundle_of_prefab(AI_GROUP_PREFAB)
    if bundle not in manifest:
        raise Divergence("aiGroup %d: bundle %r missing from assetbundles.info"
                         % (ADAPTATIONS[0]["newAiGroup"], bundle))
    path = bundle_file(cache, bundle)
    if not os.path.isfile(path):
        raise Divergence("aiGroup %d: bundle file %r not cached"
                         % (ADAPTATIONS[0]["newAiGroup"], path))
    _, _, monobehaviours, _, _ = read_unity_serialized.index_bundle(path)
    if not any(m.get("name") == AI_ASSET for m in monobehaviours.values()):
        raise Divergence("aiGroup %d: AI graph %r not found in bundle %r"
                         % (ADAPTATIONS[0]["newAiGroup"], AI_ASSET, bundle))


def preflight(rows, cache=None, manifest=None):
    """Guard every adaptation against the wrong table: exact row count, monsterIndex and
    monsterIndexString must match, and each row must sit in one of the three states that
    really exist -- the mobile original (Monster root, aiGroup 702), the v1023 intermediate
    (Character root, aiGroup 702) or the adapted pair (Character root, aiGroup 706; a
    re-run finds nothing to do). Any other combination aborts before any write. The target
    Character roots and the FighterBoss_Normal_Mob AI graph must be cached (canonical parser
    checks). Returns [(row, adaptation, fields)] with the fields still to apply."""
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
        prefab, group = row.get("monsterPrefab"), row.get("aiGroup")
        for field, current, old, new in (("monsterPrefab", prefab, a["oldPrefab"], a["newPrefab"]),
                                         ("aiGroup", group, a["oldAiGroup"], a["newAiGroup"])):
            if current not in (old, new):
                raise Divergence("monsterIndex %d: %s %r is neither the mobile %r nor the "
                                 "adapted %r -- refusing to guess"
                                 % (a["monsterIndex"], field, current, old, new))
        if (prefab, group) == (a["oldPrefab"], a["newAiGroup"]):
            raise Divergence("monsterIndex %d: pair (monsterPrefab %r, aiGroup %r) never "
                             "shipped in any source -- refusing to guess"
                             % (a["monsterIndex"], prefab, group))
        fields = [f for f, current, old in
                  (("monsterPrefab", prefab, a["oldPrefab"]), ("aiGroup", group, a["oldAiGroup"]))
                  if current == old]
        if fields:
            pending.append((row, a, fields))
    if cache is not None:
        for a in ADAPTATIONS:
            check_bundle_asset(cache, manifest, a["newPrefab"])
        check_ai_asset(cache, manifest)
    return pending


def adapt_rows(rows, cache=None, manifest=None):
    """Apply the adaptation to a row list (usable on the mobile source rows before a merge
    or on the project table's rows); returns [(monsterIndex, field, old, new)] changed."""
    changed = []
    for row, a, fields in preflight(rows, cache, manifest):
        for field in fields:
            old = a["oldPrefab"] if field == "monsterPrefab" else a["oldAiGroup"]
            new = a["newPrefab"] if field == "monsterPrefab" else a["newAiGroup"]
            row[field] = new
            changed.append((a["monsterIndex"], field, old, new))
    return changed


def adapt_current_master(data=DATA, cache=CACHE):
    """Adapt MonsterTable.json in place: full preflight before any write, and the file is
    rewritten (same dump format as import_dungeons.save_data) only when something changed."""
    path = os.path.join(data, TABLE + ".json")
    doc = json.load(open(path, encoding="utf-8"))
    pending = preflight(doc["rows"], cache, bundle_manifest(cache))
    if not pending:
        return []
    changed = []
    for row, a, fields in pending:
        for field in fields:
            old = a["oldPrefab"] if field == "monsterPrefab" else a["oldAiGroup"]
            new = a["newPrefab"] if field == "monsterPrefab" else a["newAiGroup"]
            row[field] = new
            changed.append((a["monsterIndex"], field, old, new))
    json.dump(doc, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return changed


def main():
    parser = argparse.ArgumentParser(description="Adapt the two Monster-prefab HoE elites to "
                                                 "the fighter-NPC pair (Character root, "
                                                 "FighterBoss AI group; see module docstring)")
    parser.add_argument("--data", default=DATA, help="tables data dir (default: project master)")
    parser.add_argument("--cache", default=CACHE, help="client cache root (default: project cache)")
    parser.add_argument("--check", action="store_true", help="preflight only; write nothing")
    args = parser.parse_args()
    try:
        if args.check:
            doc = json.load(open(os.path.join(args.data, TABLE + ".json"), encoding="utf-8"))
            changed = [(a["monsterIndex"], f,
                        a["oldPrefab"] if f == "monsterPrefab" else a["oldAiGroup"],
                        a["newPrefab"] if f == "monsterPrefab" else a["newAiGroup"])
                       for row, a, fields
                       in preflight(doc["rows"], args.cache, bundle_manifest(args.cache))
                       for f in fields]
        else:
            changed = adapt_current_master(args.data, args.cache)
    except (Divergence, OSError, ValueError) as e:
        print("adapt_hoe_pc_prefabs: aborting, nothing written: %s" % e, file=sys.stderr)
        return 1
    if not changed:
        print("adapt_hoe_pc_prefabs: %s already adapted, nothing to do" % TABLE)
    for index, field, old, new in changed:
        print("adapt_hoe_pc_prefabs: %s %d %s %s -> %s%s"
              % (TABLE, index, field, old, new, "" if not args.check else " (check only)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
