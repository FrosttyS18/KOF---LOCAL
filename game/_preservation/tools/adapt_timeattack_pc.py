"""Move the nine Time Attack stages' flowTrigger into triggerName -- a PC ADAPTATION, not a
restoration: the original PC ChallengeStageTable bin (storage/cache/table/common/
challengestagetable.bin) uses the CDN's own scheme and could not be read, so the original
triggerName values are UNKNOWN; the rebuilt table carries the mobile source's rows verbatim
(triggerName empty, flowTrigger set for 30101-30109).

Native grounds (client v1.17.0, GameAssembly sha 07beb870...):
- Scene_Single_Story$$LoadingProcess 0x1815E9290 preloads the flow string (StoryModel+112)
  with NO callback and loads the trigger string (StoryModel+120) with the LoadedTrigger
  callback; with triggerName empty the callback path never runs (live-measured v1022:
  StoryModel+112 set, +120 NULL, EventManager treeOwner null, trigger stale SuraDungeon_01,
  MonsterManager 0, no blocked tasks, no exception -- NOW LOADING forever).
- BaseLoadedTrigger 0x1815EA780 -> EventManager$$LoadTrigger 0x1816820F0 stores trigger(+0x90)
  and flow/frame(+0xA8); EventManager$$SetFlowTriggerData 0x181686DE0 then instantiates the
  TRIGGER itself as the flow when the frame is empty -- exactly one prefab, no duplication
  (a filled frame would instead instantiate frame as flow AND trigger as data, i.e. two
  graphs). This is also the pattern Sura (singleTriggerName) and Prove already run on PC.

So the minimal faithful move is: triggerName := old flowTrigger, flowTrigger := "" -- swap,
never duplicate. Nothing else in the rows changes (AI/stats/resourceMap/skills/score units
untouched). Every root is verified against the PC bundle before any write: the GameObject
named after the flowTrigger basename must exist and its component->Transform->MonoBehaviour
PPtr subtree must carry a NodeCanvas.BehaviourTree payload holding the real terminal
contracts (ActionGameEnd plus ConditionLoadComplete or ActionSpawnMonster) -- pointer links
and payload tokens only, no proximity matching.

usage: adapt_timeattack_pc.py [--data DIR]   (default: the project's tables/data)
"""
import argparse
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import import_dungeons as base      # load_data/save_data keep the file format identical
import read_unity_serialized        # canonical bundle parse + pointer-only graph walk


STAGES = tuple(range(30101, 30110))
EXPECTED_PREFIX = "Prefabs/EventSystem/Trigger/TimeAttack/"
STAGE_PATHS = {
    30101: EXPECTED_PREFIX + "TimeAttack_Stage_01",
    30102: EXPECTED_PREFIX + "TimeAttack_Stage_02",
    30103: EXPECTED_PREFIX + "TimeAttack_Stage_03",
    30104: EXPECTED_PREFIX + "TimeAttack_Stage_04",
    30105: EXPECTED_PREFIX + "TimeAttack_Veteran",
    30106: EXPECTED_PREFIX + "TimeAttack_TK",
    30107: EXPECTED_PREFIX + "TimeAttack_Gintama",
    30108: EXPECTED_PREFIX + "TimeAttack_SS_Mary_Terry",
    30109: EXPECTED_PREFIX + "TimeAttack_BS_Nameless_EvilAsh",
}
BUNDLE_NAME = "prefabs_eventsystem_trigger_timeattack"
CACHE = os.path.normpath(os.path.join(HERE, "..", "..", "storage", "cache"))
GRAPH_MARKER = b"NodeCanvas.BehaviourTree"
GRAPH_CONTRACT = b"ActionGameEnd"
GRAPH_ALTERNATES = (b"ConditionLoadComplete", b"ActionSpawnMonster")


def fail(msg):
    sys.exit(f"adapt_timeattack_pc: {msg}")


def basename(path):
    return path.split("/")[-1] if path and "/" in path else ""


def bundle_manifest():
    d = open(os.path.join(CACHE, "assetbundles.info"), "rb").read()
    i, names = 0, {}
    while i + 4 <= len(d):
        n = struct.unpack_from("<i", d, i)[0]
        name = d[i + 4:i + 4 + n].decode()
        i += 4 + n
        n2 = struct.unpack_from("<i", d, i)[0]
        val = d[i + 4:i + 4 + n2].decode()
        i += 4 + n2
        if len(val) == 32:
            names[name] = val
    return names


def verify_bundle(wanted):
    """{basename: proof} for every name in `wanted`: the PC bundle must be cached and each
    root must exist with a pointer-linked NodeCanvas graph holding the terminal contracts.
    Any miss raises SystemExit before the caller writes anything."""
    manifest = bundle_manifest()
    if BUNDLE_NAME not in manifest:
        fail(f"{BUNDLE_NAME} is not in the client manifest")
    path = os.path.join(CACHE, "assetbundles", hashlib.md5(BUNDLE_NAME.encode()).hexdigest())
    if not os.path.isfile(path):
        fail(f"{BUNDLE_NAME} has no cached file")
    _, gos, mbs, trs, _ = read_unity_serialized.index_bundle(path)
    proofs = {}
    for name in sorted(wanted):
        roots = [p for p, g in gos.items() if g["name"] == name]
        if not roots:
            fail(f"root GameObject {name!r} not found in the PC bundle -- aborting before write")
        graphs, monsters = [], set()
        for rp in roots:
            sub = read_unity_serialized.subtree_gameobjects(gos, trs, rp)
            for pid, m in mbs.items():
                if m["go_pid"] not in sub or GRAPH_MARKER not in m["payload"]:
                    continue
                payload = m["payload"]
                if GRAPH_CONTRACT not in payload or not any(a in payload for a in GRAPH_ALTERNATES):
                    fail(f"{name}: graph {pid:016x} lacks the terminal contracts "
                         f"({GRAPH_CONTRACT.decode()} + {'/'.join(a.decode() for a in GRAPH_ALTERNATES)})")
                graphs.append(f"{pid:016x}")
                monsters |= {x.decode() for x in
                             read_unity_serialized.MONSTER_TOKEN.findall(payload)}
        if not graphs:
            fail(f"{name}: no NodeCanvas.BehaviourTree linked by component PPtrs under the root")
        proofs[name] = {"root_pids": [f"{r:016x}" for r in roots], "graphs": graphs,
                        "monsters": len(monsters)}
    return proofs


def plan(rows):
    """-> (changes [(row, old_flow, new_trigger)], proofs). Guarded states only, with the exact
    id -> path mapping of STAGE_PATHS: original (trigger empty + that exact flow) or already
    adapted (that exact trigger + flow empty); anything else aborts before any write."""
    if len(rows) != len(STAGES) or {int(r.get("challengeStageIndex") or 0) for r in rows} != set(STAGES):
        fail(f"ChallengeStageTable must carry exactly {list(STAGES)} -- found "
             f"{sorted(int(r.get('challengeStageIndex') or 0) for r in rows)}")
    changes, wanted = [], set()
    for r in rows:
        idx = int(r.get("challengeStageIndex"))
        expected = STAGE_PATHS[idx]
        trigger, flow = r.get("triggerName") or "", r.get("flowTrigger") or ""
        if not trigger and flow == expected:
            wanted.add(basename(flow))
            changes.append((r, flow))
        elif flow == "" and trigger == expected:
            wanted.add(basename(trigger))
        else:
            fail(f"stage {idx}: expected triggerName=''+flowTrigger={expected!r} (or the adapted "
                 f"swap), found triggerName={trigger!r}, flowTrigger={flow!r} -- refusing")
    proofs = verify_bundle(wanted) if wanted else {}
    return changes, proofs


def apply(data_dir):
    base.DATA = data_dir
    doc = base.load_data("ChallengeStageTable")
    changes, proofs = plan(doc["rows"])
    for row, old_flow in changes:
        row["triggerName"] = old_flow
        row["flowTrigger"] = ""
    if changes:
        base.save_data("ChallengeStageTable", doc)
    return len(changes), proofs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=os.path.normpath(os.path.join(HERE, "..", "server",
                                                                        "tables", "data")),
                        help="tables data dir to update (default: the project's)")
    args = parser.parse_args()
    if not os.path.isfile(os.path.join(args.data, "ChallengeStageTable.json")):
        fail(f"{args.data} carries no ChallengeStageTable.json")
    changed, proofs = apply(args.data)
    if changed:
        print(f"adapted {changed} stages: flowTrigger -> triggerName, flowTrigger cleared "
              f"(roots verified: {len(proofs)})")
    else:
        print("all 9 stages already adapted -- nothing written")
    for name, p in sorted(proofs.items()):
        print(f"  {name}: roots={len(p['root_pids'])} graphs={len(p['graphs'])} monsters={p['monsters']}")


if __name__ == "__main__":
    main()
