"""Core Dungeon "Altar of Illusion" (event 3501) and Awaken EXP Dungeon "EXP Crush" (event 3601); tools/gen_powerdungeons.py
has the tables and the REAL / OURS split.

Both are QuestEvents, so the ordinary questEvent/* handlers run them (the Awaken EXP capsules are plain clear rewards,
paid by questEventEnd and AUTO-CLEAR like the EXP dungeon's). This module adds:
  - the Awaken EXP dungeon's schedule (gameapi.DUNGEON_SCHEDULES; the Core Dungeon's is already there) so it opens in the
    Power Up list;
  - the Core Dungeon's random core drops of a won run (questEvent/questEventEnd) and of every AUTO-CLEAR run
    (questEvent/questEventMopUp): the stage's drop group (RewardGroupTable group 3,502,000 + stage no., item rows whose
    randomRewardProbability / 10,000 is the chance of each; a group the generic reward code never pays) is rolled per run.
    The cores go into the save's items and into the reply (ClearRewardList / RewardContentsList for the RESULT,
    RewardItemList for the client's bag).
The unlock "Clear Story Quest '94 Chapter 5" (ContentsUnlockTable 111) is the real one: the client asks adventure/selectStageList
for stage 110599 and wants its state 2; this build has no chapter 5, so a test account reaches the dungeon by setting
save.json stages["110599"] = {"result": 1, "plays": 1} (or `adventure/stageEnd`-style progress that writes it).
"""
import random

import gameapi as G

CORE_EVENT, AWAKEN_EVENT = 3501, 3601
CORE_STAGE0 = 350100
CORE_STAGES = range(CORE_STAGE0 + 1, CORE_STAGE0 + 5)
CORE_DROP_BASE = 3_502_000

for _schedule in (CORE_EVENT, AWAKEN_EVENT):
    if _schedule not in G.DUNGEON_SCHEDULES:
        G.DUNGEON_SCHEDULES.append(_schedule)


def is_core(index):
    return index in CORE_STAGES


def roll(index, rng=random, rows=None):
    """One run's core drops of a stage -> [(item, count)]"""
    group = CORE_DROP_BASE + index - CORE_STAGE0
    drops = []
    for r in (rows if rows is not None else G.table_rows("RewardGroupTable")):
        if r.get("rewardGroup") != group or r.get("rewardType") != G.ITEM_GOODS:
            continue
        if rng.randrange(10_000) < r.get("randomRewardProbability", 10_000):
            drops.append((r["contentsIndex"], r.get("contentsCountMin", 1)))
    return drops


def merged(drops):
    out = {}
    for item, count in drops:
        out[item] = out.get(item, 0) + count
    return out


def store(state, drops):
    inv = G.items(state)
    for item, count in drops:
        inv[str(item)] = int(inv.get(str(item), 0)) + count


def _end(inner):
    def handler(req):
        out = inner(req)
        index = int(req.get("QuestEventStageIndex") or 0)
        if not (is_core(index) and isinstance(out, dict) and out.get("ResultCode") == 0
                and int(req.get("BattleResult") or 0) == G.WIN):
            return out
        with G._lock:
            state = G.load_state()
            drops = roll(index)
            store(state, drops)
            G.save_state(state)
        got = merged(drops)
        out["ClearRewardList"] = list(out.get("ClearRewardList") or []) + [
            G.reward(G.ITEM_GOODS, n, item) for item, n in got.items()]
        out["RewardItemList"] = list(out.get("RewardItemList") or []) + [
            {"ItemIndex": item, "Qty": n, "Lock": 0, "UpdateTime": G.now_ms()} for item, n in got.items()]
        return out
    return handler


def _mopup(inner):
    def handler(req):
        out = inner(req)
        index = int(req.get("QuestEventStageIndex") or 0)
        if not (is_core(index) and isinstance(out, dict) and out.get("ResultCode") == 0):
            return out
        contents = list(out.get("RewardContentsList") or [])
        runs = max([c.get("Count", 0) for c in contents] + [0])
        if not runs:
            return out
        with G._lock:
            state = G.load_state()
            for run in range(1, runs + 1):
                drops = roll(index)
                store(state, drops)
                contents += [G.mopup_reward(G.ITEM_GOODS, n, run, item) for item, n in merged(drops).items()]
            G.save_state(state)
        out["RewardContentsList"] = contents
        out["RewardItemList"] = G.gained_items(contents)
        return out
    return handler


G.APIS["questEvent/questEventEnd"] = _end(G.APIS["questEvent/questEventEnd"])
G.APIS["questEvent/questEventMopUp"] = _mopup(G.APIS["questEvent/questEventMopUp"])
