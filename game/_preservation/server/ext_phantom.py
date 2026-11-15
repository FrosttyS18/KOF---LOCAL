"""Tower of Illusion (QuestEvent 107, questEventType 8) -- Dungeon > Challenge Dungeon's phantom tower
(real mobile tables, tools/import_dungeons.py).

The floors are QuestEventStageTable rows of event 107 with stageType != 4. The client enters a floor
only when its openValue == lastClearStageIndex + 1, so the tower stays server-driven:
questEvent/phantomTowerInfo without a body answers the tower state (an absent PhantomTower object
NREs the client), phantomTowerStart/End run a floor like a QuestEvent battle (Scene_Single_Event,
subtype 82), and phantomTowerMopUp pays the top floor's questEventCrucibleTowerClearRewardGroup once
a day. The Auto-Clear button itself only shows while QuestEventTable.isAbleMopUp is 1; the endpoint
answers anyway. Progress lives in save.json "phantom" (last floor, mopup ms, register ms)."""
import time

import gameapi as G

ILUSION_QE = 107
ILUSION_AP = 10

EMPTY_LISTS = ("RewardItemList", "RewardCharacterList", "RewardBattleCardList", "CharacterList",
               "ClearRewardList", "AffectionRewardList1", "AffectionRewardList2", "AffectionRewardList3",
               "GuildBuffList", "GlobalDropRewardList", "AccountLevelUpRewardList", "RewardImprintStoneList",
               "presetCharacterReward", "presetCharacterCoreReward")


def floors():
    return sorted((r for r in G.table_rows("QuestEventStageTable")
                   if int(r.get("questEventIndex") or 0) == ILUSION_QE and int(r.get("stageType") or 0) != 4),
                  key=lambda r: int(r.get("questEventStageIndex") or 0))


def today(ms):
    return time.strftime("%Y-%m-%d", time.localtime(ms or 0)) == time.strftime("%Y-%m-%d")


def tower_info(l):
    pr = (G.load_state() or {}).get("phantom", {})
    ids = [int(r.get("questEventStageIndex") or 0) for r in l]
    last = min(int(pr.get("last") or 0), ids[-1] if ids else 0)
    nxt = (last + 1) if last else (ids[0] if ids else 0)
    mopup = int(pr.get("mopup") or 0)
    return {"stageIndex": min(nxt, ids[-1]) if ids else 0, "lastClearStageIndex": last, "mopupTime": mopup,
            "mopupCount": 1 if mopup and today(mopup) else 0, "regTime": int(pr.get("reg") or 0)}


def battle_exp(state, req, ap):
    """Rank EXP for the run and fighter EXP/affection from the client's battle result team (questEventEnd's)."""
    account = req.get("PlayerAccount") or {}
    before = max(state.get("exp", 0), int(account.get("Exp") or 0))
    state["exp"] = before + G.QUEST_EVENT_EXP_PER_AP * ap
    for n, c in enumerate(c for c in req.get("CharacterList") or [] if c.get("CharacterIndex")):
        fighter = G.character_state(state, int(c["CharacterIndex"]))
        fighter["exp"] = max(fighter.get("exp", 0), int(c.get("Exp", 0)))
        fighter["affection"] = max(fighter.get("affection", 0), int(c.get("AffectionExp") or 0)) + (
            G.AFFINITY_LEADER if n == 0 else G.AFFINITY_OTHERS)
    return G.apply_rank_up(state, before)


@G.api("questEvent/phantomTowerInfo")
def phantom_info(req):
    return G.ok(PhantomTower=tower_info(floors()))


@G.api("questEvent/phantomTowerStart")
def phantom_start(req):
    with G._lock:
        state = G.load_state()
        pr = state.setdefault("phantom", {})
        if not pr.get("reg"):
            pr["reg"] = G.now_ms()
        pr["run"] = int(req.get("QuestEventStageIndex") or 0)
        G.save_state(state)
    return G.ok(StrikerType=0, StrikerUsn=0, StrikerGameDb=0, StrikerNickName="",
                QuestEventPlayToken=G.now_ms(), LuckySpawn=0, DropGoldLucky=0, DropGoldJaco=0,
                DropGoldElite=0, DropGoldBoss=0, DropGoldGimmick1=0, DropGoldGimmick2=0,
                DropGoldGimmick3=0, AccountMoney=G.money(state))


@G.api("questEvent/phantomTowerEnd")
def phantom_end(req):
    sid = int(req.get("QuestEventStageIndex") or 0)
    row = next((r for r in floors() if int(r.get("questEventStageIndex") or 0) == sid), {})
    won = int(req.get("BattleResult") or 0) == G.WIN
    out = {k: [] for k in EMPTY_LISTS}
    with G._lock:
        state = G.load_state()
        pr = state.setdefault("phantom", {})
        if won and row:
            if sid > int(pr.get("last") or 0):
                out["ClearRewardList"] = G.give_rewards(
                    state, row.get("questEventStageFirstClearRewardGroup", 0))[0]
                pr["last"] = sid
            out["AccountLevelUpFlag"], out["AccountLevelUpRewardList"] = battle_exp(state, req, ILUSION_AP)
        G.save_state(state)
    out.update(QuestEventStageIndex=sid, BattleResult=int(req.get("BattleResult") or 0), PostSendFlag=False,
               AccountMoney=G.money(state),
               PlayerAccount=G.apidefaults.default("PlayerAccount", Usn=G.USN, Exp=state["exp"]))
    return G.ok(**out)


@G.api("questEvent/phantomTowerMopUp")
def phantom_mopup(req):
    l = floors()
    inf = tower_info(l)
    last = int(inf["lastClearStageIndex"])
    row = next((r for r in l if int(r.get("questEventStageIndex") or 0) == last), {})
    out = {k: [] for k in EMPTY_LISTS + ("RewardContentsList", "AdsList")}
    with G._lock:
        state = G.load_state()
        pr = state.setdefault("phantom", {})
        if row and row.get("questEventCrucibleTowerClearRewardGroup"):
            out["RewardContentsList"] = G.give_rewards(
                state, row.get("questEventCrucibleTowerClearRewardGroup", 0))[0]
            pr["mopup"] = G.now_ms()
        G.save_state(state)
    out.update(QuestEventStageIndex=last, AccountLevelUpFlag=0, PostSendFlag=False,
               AccountMoney=G.money(state),
               PlayerAccount=G.apidefaults.default("PlayerAccount", Usn=G.USN, Exp=state["exp"]))
    return G.ok(**out)
