"""Prove Dungeon / Dungeon of Trials (QuestEvent 10901, questEventType 6) -- Battle > Dungeon of Trials
(real mobile tables, tools/import_dungeons.py; ModeTable 109, Scene_Single_Prove).

A 3v3 duel against three random bosses: ProveDungeonStageTable picks the stage (30) and its
bossGroupIndex, ProveDungeonRandomBossTable the pool (highTierBossMin/Max of the stage decide how many
tier-2 bosses). proveDungeon/rematch rerolls the bosses for the stage's bossRematchCost rubies;
stageEnd wins at WinRoundCount >= 3 and pays proveDungeonWinRewardGroup (first clear) or
proveDungeonAllKillBonus (repeat / Auto-Clear). Progress lives in save.json "prove"
({"stage": current, "max": highest, "team": [3], "support": [], "bosses": [3]})."""
import random

import gameapi as G
import ext_phantom as P

PROVE_AP = 8

EMPTY_LISTS = ("RewardItemList", "RewardBattleCardList", "RewardCharacterList", "RewardContentsList",
               "HandicapRewardContentsList", "RewardImprintStoneList", "GuildBuffList",
               "presetCharacterReward", "presetCharacterCoreReward")


def stage_rows():
    return sorted(G.table_rows("ProveDungeonStageTable"), key=lambda r: int(r.get("proveDungeonStageIndex") or 0))


def random_bosses(row):
    pool = [r for r in G.table_rows("ProveDungeonRandomBossTable")
            if int(r.get("randomBossGroupIndex") or 0) == int(row.get("bossGroupIndex") or 1)]
    tier2 = [int(r["randomBossIndex"]) for r in pool if int(r.get("randomBossTier") or 0) >= 2]
    tier1 = [int(r["randomBossIndex"]) for r in pool if int(r.get("randomBossTier") or 0) < 2] or tier2
    lo, hi = int(row.get("highTierBossMin") or 0), int(row.get("highTierBossMax") or 0)
    k = min(3, random.randint(min(lo, hi), max(lo, hi))) if tier2 else 0
    picked = random.sample(tier2, min(k, len(tier2))) if k else []
    picked += random.sample([i for i in tier1 if i not in picked], min(3 - len(picked), len(tier1)))
    random.shuffle(picked)
    return picked


def current(state):
    """-> (stage number, its row); rolls the bosses when the stage changed."""
    rows = stage_rows()
    last = int(rows[-1]["proveDungeonStageIndex"]) if rows else 0
    pr = state.setdefault("prove", {})
    n = min(int(pr.get("stage") or 1), last) if last else 0
    pr["stage"] = n
    row = next((r for r in rows if int(r["proveDungeonStageIndex"]) == n), {})
    if n and (len(pr.get("bosses") or []) != 3 or int(pr.get("boss_stage") or 0) != n):
        pr["bosses"] = random_bosses(row)
        pr["boss_stage"] = n
    return n, row


@G.api("proveDungeon/info")
def prove_info(req):
    with G._lock:
        state = G.load_state()
        n, row = current(state)
        pr = state["prove"]
        G.save_state(state)
    return G.ok(ProveDungeonStageIndex=n, RematchProveDungeonStageIndex=0, SuraDungeonDifficultyIndex=1,
                BossRematchCost=int(row.get("bossRematchCost") or 0),
                CharacterIndexList=list(pr.get("team") or []),
                SupportCharacterIndexList=list(pr.get("support") or []),
                RandomBossIndexList=list(pr.get("bosses") or []), PlayCount=0)


@G.api("proveDungeon/deckUpdate")
def prove_deck(req):
    with G._lock:
        state = G.load_state()
        pr = state.setdefault("prove", {})
        pr["team"] = [int(x or 0) for x in req.get("CharacterIndexList") or []]
        pr["support"] = [int(x or 0) for x in req.get("SupportCharacterIndexList") or []]
        G.save_state(state)
    return G.ok(CharacterIndexList=pr["team"], SupportCharacterIndexList=pr["support"])


@G.api("proveDungeon/rematch")
def prove_rematch(req):
    with G._lock:
        state = G.load_state()
        n, row = current(state)
        pr = state["prove"]
        cost = max(0, int(req.get("BossRematchCost") or row.get("bossRematchCost") or 0))
        wallet = state.setdefault("money", dict(G.START_MONEY))
        if int(wallet.get("Cash") or 0) >= cost:
            wallet["Cash"] = int(wallet.get("Cash", 0)) - cost
            pr["bosses"] = random_bosses(row)
            pr["boss_stage"] = n
        G.save_state(state)
    return G.ok(ProveDungeonStageIndex=n, RandomBossIndexList=list(pr.get("bosses") or []),
                AccountMoney=G.money(state))


@G.api("proveDungeon/stageStart")
def prove_start(req):
    with G._lock:
        state = G.load_state()
        state.setdefault("prove", {})["run"] = G.now_ms()
        G.save_state(state)
    return G.ok(PlayToken=G.now_ms())


@G.api("proveDungeon/stageEnd")
def prove_end(req):
    won = int(req.get("WinRoundCount") or 0) >= 3
    out = {k: [] for k in EMPTY_LISTS}
    with G._lock:
        state = G.load_state()
        n, row = current(state)
        pr = state["prove"]
        rows = stage_rows()
        last = int(rows[-1]["proveDungeonStageIndex"]) if rows else 0
        if won:
            first = n > int(pr.get("max") or 0)
            group = row.get("proveDungeonWinRewardGroup") if first else row.get("proveDungeonAllKillBonus")
            out["RewardContentsList"] = G.give_rewards(state, group or 0)[0]
            if first:
                pr["max"] = n
            pr["stage"] = min(n + 1, last)
            pr["bosses"] = []
            team = [c for c in (pr.get("team") or []) if c][:3]
            out["AccountLevelUpFlag"], out["AccountLevelUpRewardList"] = P.battle_exp(
                state, {"PlayerAccount": {}, "CharacterList": [{"CharacterIndex": c} for c in team]}, PROVE_AP)
        G.save_state(state)
    out.update(PlayCount=0, PostSendFlag=False, AccountMoney=G.money(state),
               PlayerAccount=G.apidefaults.default("PlayerAccount", Usn=G.USN, Exp=state["exp"]))
    return G.ok(**out)


@G.api("proveDungeon/stageMopUp")
def prove_mopup(req):
    out = {k: [] for k in EMPTY_LISTS}
    runs = max(1, int(req.get("MopUpCount") or 1))
    with G._lock:
        state = G.load_state()
        _n, row = current(state)
        rewards = []
        for _ in range(runs):
            rewards += G.give_rewards(state, row.get("proveDungeonAllKillBonus") or 0)[0]
        G.save_state(state)
    out["RewardContentsList"] = rewards
    out.update(PlayCount=0, PostSendFlag=False, AccountMoney=G.money(state),
               PlayerAccount=G.apidefaults.default("PlayerAccount", Usn=G.USN, Exp=state["exp"]))
    return G.ok(**out)
