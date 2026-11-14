"""Buff Select Dungeon (QuestEvent 8101, questEventType 6) -- Dungeon > Challenge Dungeon (real mobile
tables, tools/import_dungeons.py; ModeTable 110, ShortCut 2000, GameMode 26).

A 50-floor tower whose floors are BuffSelectDungeonStageTable rows (each names its QuestEventStage
810101..810150): the team of 3 carries its HP between floors, a won floor offers a pick of 3 buffs
(BuffSelectDungeonBuffTable buffMainType 3) that stack for the next floors, and floors 11+ curse the
run (one curse 11-30, two 31-40, three 41+ -- the community build's rule, not recovered from official
data). Rankings are offline (self only). Progress lives in save.json "buffselect": {"clear": floor,
"max": floor, "team": {...}, "hp": {character: %}, "picks": {floor: [buffs]}, "choice": {...}}."""
import random

import gameapi as G
import ext_phantom as P

BS_AP = 8
BS_SEASON, BS_START, BS_END = 1, 1767225600000, 4102444800000

TEAM_KEYS = ("CharacterIndex1", "CharacterIndex2", "CharacterIndex3", "SupportCharacterIndex1",
             "SupportCharacterIndex2", "SupportCharacterIndex3", "TeamRelationIndex", "GroupGrowthIndex")
MAIN_KEYS = TEAM_KEYS[:3]


def floors():
    return sorted(G.table_rows("BuffSelectDungeonStageTable"), key=lambda r: int(r.get("stageIndex") or 0))


def curses(n):
    n = int(n)
    if n <= 10:
        return []
    if n <= 30:
        return [2001 + (n % 3)]
    if n <= 40:
        return [2001 + (n % 3), 2001 + ((n + 1) % 3)]
    return [2001, 2002, 2003]


def buffs():
    return [int(r["dungeonBuffIndex"]) for r in G.table_rows("BuffSelectDungeonBuffTable")
            if int(r.get("buffMainType") or 0) == 3]


def dungeon_view(pr):
    l = floors()
    top = int(l[-1]["stageIndex"]) if l else 0
    clear = min(int(pr.get("clear") or 0), top)
    choice = pr.get("choice") or {}
    tim = pr.get("team") or {}
    d = {"Season": BS_SEASON, "PlayStageIndex": min(clear + 1, top) if top else 0, "LastClearStageIndex": clear,
         "BuffSelectStageIndex": int(choice.get("floor") or 0) if choice.get("options") else 0,
         "BuffSelectIndexList": ",".join(str(i) for i in choice.get("options") or []), "BossHpInfo": ""}
    for k in TEAM_KEYS:
        d[k] = int(tim.get(k) or 0)
    return d


def char_states(pr, extra=()):
    hp = pr.setdefault("hp", {})
    tim = pr.get("team") or {}
    ids = []
    for k in TEAM_KEYS[:6]:
        c = int(tim.get(k) or 0)
        if c and c not in ids:
            ids.append(c)
    for c in list(hp) + list(extra):
        c = int(c)
        if c and c not in ids:
            ids.append(c)
    return [{"CharacterIndex": c, "RemainHp": max(0, min(100, int(hp.get(str(c), 100)))),
             "Status": 1 if int(hp.get(str(c), 100)) > 0 else 0} for c in ids]


def picks_list(pr):
    return [{"StageIndex": int(s), "BuffIndex": ",".join(str(i) for i in lst)}
            for s, lst in sorted((pr.get("picks") or {}).items(), key=lambda x: int(x[0])) if lst]


def save_team(pr, req):
    t = {"CharacterIndex1": req.get("CharacterIndex1"), "CharacterIndex2": req.get("CharacterIndex2"),
         "CharacterIndex3": req.get("CharacterIndex3"),
         "SupportCharacterIndex1": req.get("supportCharacterIndex1"),
         "SupportCharacterIndex2": req.get("supportCharacterIndex2"),
         "SupportCharacterIndex3": req.get("supportCharacterIndex3"),
         "TeamRelationIndex": req.get("TeamRelationIndex"), "GroupGrowthIndex": req.get("GroupGrowthIndex")}
    pr["team"] = {k: int(v or 0) for k, v in t.items()}


@G.api("questEvent/buffDungeonInfo")
def bs_info(req):
    state = G.load_state() or {}
    pr = state.get("buffselect", {})
    return G.ok(BuffSelectDungeonSeason={"Season": BS_SEASON, "StartDate": BS_START, "EndDate": BS_END,
                                         "StageBuffList": [{"StageIndex": int(r["stageIndex"]),
                                                            "DungeonBuffIndexList": ",".join(
                                                                str(i) for i in curses(r["stageIndex"]))}
                                                           for r in floors() if curses(r["stageIndex"])]},
                Dungeon=dungeon_view(pr), StageList=picks_list(pr), CharacterList=char_states(pr))


@G.api("questEvent/buffDungeonCharacter")
def bs_character(req):
    with G._lock:
        state = G.load_state()
        save_team(state.setdefault("buffselect", {}), req)
        G.save_state(state)
    return G.ok(Dungeon=dungeon_view(state["buffselect"]), CharacterList=char_states(state["buffselect"]))


@G.api("questEvent/buffDungeonStart")
def bs_start(req):
    with G._lock:
        state = G.load_state()
        pr = state.setdefault("buffselect", {})
        save_team(pr, req)
        pr["run"] = int(req.get("StageIndex") or 0)
        G.save_state(state)
    return G.ok(QuestEventPlayToken=G.now_ms(), DropLuckyList=[], DropJacoList=[], DropEliteList=[],
                DropBossList=[], DropGimmickList=[], LuckySpawn=0, DropGoldLucky=0, DropGoldJaco=0,
                DropGoldElite=0, DropGoldBoss=0, DropGoldGimmick1=0, DropGoldGimmick2=0, DropGoldGimmick3=0,
                AccountMoney=G.money(state))


@G.api("questEvent/buffDungeonEnd")
def bs_end(req):
    n = int(req.get("StageIndex") or 0)
    row = next((r for r in floors() if int(r.get("stageIndex") or 0) == n), {})
    q = G.quest_event_stage_row(int(row.get("questEventStageIndex") or 0))
    won = int(req.get("BattleResult") or 0) == G.WIN
    out = {k: [] for k in ("RewardItemList", "RewardBattleCardList", "RewardCharacterList", "ClearRewardList",
                           "AffectionRewardList1", "AffectionRewardList2", "AffectionRewardList3",
                           "AccountLevelUpRewardList", "RewardImprintStoneList", "presetCharacterList",
                           "presetCharacterCoreList", "CharacterList")}
    first = 0
    with G._lock:
        state = G.load_state()
        pr = state.setdefault("buffselect", {})
        hp = pr.setdefault("hp", {})
        main = [int((pr.get("team") or {}).get(k) or 0) for k in MAIN_KEYS]
        if won and q:
            for c, h in zip(main, (req.get("Character1Hp"), req.get("Character2Hp"), req.get("Character3Hp"))):
                if c:
                    hp[str(c)] = max(0, min(100, int(h if h is not None else 100)))
            for c in list(hp):
                if int(hp[c]) <= 0 and int(c) not in main:
                    hp[c] = 30
            if n > int(pr.get("clear") or 0):
                pr["clear"] = n
            if n > int(pr.get("max") or 0):
                first = 1
                pr["max"] = n
                out["ClearRewardList"] = G.give_rewards(
                    state, q.get("questEventStageFirstClearRewardGroup", 0))[0]
            options = sorted(random.sample(buffs(), 3))
            pr["choice"] = {"floor": n, "options": options}
            account = req.get("PlayerAccount") or {}
            before = max(state.get("exp", 0), int(account.get("Exp") or 0))
            state["exp"] = before + G.QUEST_EVENT_EXP_PER_AP * BS_AP
            out["AccountLevelUpFlag"], out["AccountLevelUpRewardList"] = G.apply_rank_up(state, before)
        else:
            for c in main:
                if c:
                    hp[str(c)] = 100
        G.save_state(state)
    out.update(QuestEventStageIndex=int(q.get("questEventStageIndex") or 0),
               BattleResult=int(req.get("BattleResult") or 0), FirstClearFlag=first, PostSendFlag=False,
               Dungeon=dungeon_view(pr), StageList=picks_list(pr), DungeonCharacterList=char_states(pr),
               AccountMoney=G.money(state),
               PlayerAccount=G.apidefaults.default("PlayerAccount", Usn=G.USN, Exp=state["exp"]))
    return G.ok(**out)


@G.api("questEvent/buffDungeonFighterBuff")
def bs_pick(req):
    b = int(req.get("DungeonBuffIndex") or 0)
    with G._lock:
        state = G.load_state()
        pr = state.setdefault("buffselect", {})
        choice = pr.get("choice") or {}
        floor_n = int(choice.get("floor") or pr.get("clear") or 0)
        if b and b in buffs():
            pr.setdefault("picks", {}).setdefault(str(floor_n), []).append(b)
        pr["choice"] = {}
        G.save_state(state)
    taken = (pr.get("picks") or {}).get(str(floor_n), [])
    return G.ok(Dungeon=dungeon_view(pr), Stage={"StageIndex": floor_n,
                                                 "BuffIndex": ",".join(str(i) for i in taken)})


@G.api("questEvent/buffDungeonRevive")
def bs_revive(req):
    c = int(req.get("CharacterIndex") or 0)
    with G._lock:
        state = G.load_state()
        pr = state.setdefault("buffselect", {})
        if c:
            pr.setdefault("hp", {})[str(c)] = 100
        G.save_state(state)
    return G.ok(CharacterList=char_states(pr), RemainItem=None)


@G.api("questEvent/buffDungeonRankingList")
def bs_ranking(req):
    return G.ok(MyRanking=None, RankingList=[], RankingUserList=[], FriendGuildInfoList=[])


@G.api("questEvent/buffDungeonRankingInfoDetail")
def bs_rank_detail(req):
    state = G.load_state() or {}
    pr = state.get("buffselect", {})
    return G.ok(BestRecord=int(pr.get("clear") or 0), BestRecordTime=0, TeamRelationIndex=0, CharacterList=[],
                BattleCardList=[], CharacterCoresList=[], ImprintStoneList=[], CharacterAwakenCoreList=[],
                ListBuff=[], AccountGrowthStatList=[], AccountExtraList=[])
