"""Battle Card Dungeon "Back Alley Mop-up Operation" (tools/gen_backalley.py has the tables and the REAL / OURS split).

A QuestEvent (event 3401, subtype 34, stages 340101-340108), so the ordinary questEvent/* handlers already run it; this module
adds what they do not know:
  - the dungeon's schedule (gameapi.DUNGEON_SCHEDULES) so it opens in the Power Up list;
  - the battle-card drops of a won run (questEvent/questEventEnd) and of every AUTO-CLEAR run (questEvent/questEventMopUp):
    RewardGroupTable rows of the stage's clear group with rewardType 12 (CARD): contentsIndex = a card enhancement material
    (stacked BattleCardTable row 800001-5, always dropped: probability 10,000) or 0 = a random battle card (chance =
    randomRewardProbability / 10,000, contentsGrade = the top grade). The drops go into save.json "cards" (material stacks as
    ext_cards.add_material, cards as gameapi.gacha_card) and into the reply: ClearRewardList / RewardContentsList (GoodsType 12,
    shown on the RESULT) and RewardBattleCardList (the client's card inventory update).
  - the random card: ACTIVE stages (stage index 340101-4) drop special cards (cardType 3), PASSIVE stages (340105-8) option and
    set cards (types 2 and 4); the grade is picked from 4 .. the top grade (weights 6 / 3 / 1 for 4 / 5 / 6 stars, ours, among
    the grades the type has); 70 % of the cards come from the newest 40 of the type (by yearIndex: "recent banner cards",
    REAL by the video, the split ours).
The battledungeon/* APIs of the client are the PROVE dungeon (boss rematches), not this dungeon.
"""
import random

import gameapi as G
import ext_cards as C

EVENT = 3401
ACTIVE_STAGES, PASSIVE_STAGES = range(340101, 340105), range(340105, 340109)
CARD_GOODS = 12
GRADE_WEIGHT = {4: 6, 5: 3, 6: 1}      # ours
RECENT_SHARE, RECENT_COUNT = 0.7, 40   # ours

if EVENT not in G.DUNGEON_SCHEDULES:
    G.DUNGEON_SCHEDULES.append(EVENT)


def is_ours(index):
    return index in ACTIVE_STAGES or index in PASSIVE_STAGES


def stage_group(index):
    row = G.quest_event_stage_row(index)
    return row.get("questEventStageClearRewardGroup", 0)


def pool(index, top, rows=None):
    """BattleCardTable rows a random drop of this stage can be: the stage family's types, start grade 4 .. top"""
    types = (3,) if index in ACTIVE_STAGES else (2, 4)
    rows = rows if rows is not None else G.table_rows("BattleCardTable")
    return [r for r in rows if r.get("cardType") in types and 4 <= r.get("cardStartGrade", 0) <= top
            and r.get("pictureBookShow", 1) and not 800_000 <= r["battleCardIndex"] < 800_100]


def pick_card(index, top, rng=random, rows=None):
    cards = pool(index, top, rows)
    if not cards:
        return None
    grades = sorted({r["cardStartGrade"] for r in cards})
    grade = rng.choices(grades, weights=[GRADE_WEIGHT.get(g, 1) for g in grades])[0]
    same = [r for r in cards if r["cardStartGrade"] == grade]
    recent = sorted(same, key=lambda r: (r.get("yearIndex", 0), r["battleCardIndex"]), reverse=True)[:RECENT_COUNT]
    chosen = recent if rng.random() < RECENT_SHARE else same
    return rng.choice(chosen)["battleCardIndex"]


def roll(index, rng=random, rows=None):
    """One run's drops of a stage -> [(cardIndex, count)] (materials always, a random card by its chance)"""
    drops = []
    for r in G.table_rows("RewardGroupTable"):
        if r.get("rewardGroup") != stage_group(index) or r.get("rewardType") != CARD_GOODS:
            continue
        if rng.randrange(10_000) >= r.get("randomRewardProbability", 10_000):
            continue
        card = r.get("contentsIndex", 0)
        if card == 0:
            card = pick_card(index, r.get("contentsGrade", 6), rng, rows)
        if card:
            drops.append((card, r.get("contentsCountMin", 1)))
    return drops


def store(state, drops):
    """Put the drops into the save -> the BattleCard protos for the reply (materials: their stacks as they stand now)"""
    stacks, made = [], []
    for card, count in drops:
        if C.MATERIAL_BASE <= card < C.MATERIAL_END:
            stacks.append(C.add_material(state, card, count)["no"])
        else:
            for _ in range(count):
                made.append(G.gacha_card(state, card))
    allc = {c["BattleCardNo"]: c for c in G.battle_cards(state)}
    return made + [allc[n] for n in dict.fromkeys(stacks) if n in allc]


def merged(drops):
    out = {}
    for card, count in drops:
        out[card] = out.get(card, 0) + count
    return out


def _end(inner):
    def handler(req):
        out = inner(req)
        index = int(req.get("QuestEventStageIndex") or 0)
        if not (is_ours(index) and isinstance(out, dict) and out.get("ResultCode") == 0
                and int(req.get("BattleResult") or 0) == G.WIN):
            return out
        with G._lock:
            state = G.load_state()
            drops = roll(index)
            cards = store(state, drops)
            G.save_state(state)
        out["ClearRewardList"] = list(out.get("ClearRewardList") or []) + [
            G.reward(CARD_GOODS, n, card) for card, n in merged(drops).items()]
        out["RewardBattleCardList"] = cards
        return out
    return handler


def _mopup(inner):
    def handler(req):
        out = inner(req)
        index = int(req.get("QuestEventStageIndex") or 0)
        if not (is_ours(index) and isinstance(out, dict) and out.get("ResultCode") == 0):
            return out
        runs = max([c.get("Count", 0) for c in out.get("RewardContentsList") or []] + [0])
        if not runs:
            return out
        with G._lock:
            state = G.load_state()
            all_drops = []
            contents = list(out.get("RewardContentsList") or [])
            for run in range(1, runs + 1):
                drops = roll(index)
                all_drops += drops
                contents += [G.mopup_reward(CARD_GOODS, n, run, card) for card, n in merged(drops).items()]
            cards = store(state, all_drops)
            G.save_state(state)
        out["RewardContentsList"] = contents
        out["RewardBattleCardList"] = cards
        return out
    return handler


G.APIS["questEvent/questEventEnd"] = _end(G.APIS["questEvent/questEventEnd"])
G.APIS["questEvent/questEventMopUp"] = _mopup(G.APIS["questEvent/questEventMopUp"])
