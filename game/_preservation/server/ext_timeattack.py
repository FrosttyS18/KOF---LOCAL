"""Time Attack (the client's Challenge system) -- Dungeon > Challenge Dungeon > Time Attack (real mobile
tables, tools/import_dungeons.py; ModeTable 301, ShortCut 175, Scene_Single_ChallengeModeReady).

ChallengeScheduleTable lists the schedules (each names its ChallengeStageTable stage, a score group and
a daily reward group). challenge/eventInfo answers the play info and every fighter that may be picked,
eventStart/End run the 3-round timed battle (the time is the score: the best ClearRankTime is kept),
rankingList/rankingCharacterInfo answer the (offline: self-only) ranking. The term is the day as
YYYYMMDD01, ChallengeScheduleProto.Term style. Progress lives in save.json "timeattack" per schedule:
{"best": ms, "day": ymd, "plays": n, "total": n, "reward_day": ymd, "missions": [...], "team": [3]}."""
import time

import gameapi as G

TA_AP = 10


def schedule(no):
    return next((r for r in G.table_rows("ChallengeScheduleTable")
                 if int(r.get("challengeScheduleIndex") or 0) == int(no or 0)), {})


def score_rows(no):
    group = int(schedule(no).get("challengeScoreGroup") or no)
    return sorted((r for r in G.table_rows("ChallengeScoreTable")
                   if int(r.get("challengeScoreGroup") or 0) == group),
                  key=lambda r: int(r.get("challengeScoreIndex") or 0))


def team(pr):
    t = [int(c) for c in (pr.get("team") or []) if int(c or 0)]
    return (t + [0, 0, 0])[:3]


@G.api("challenge/eventInfo")
def ta_info(req):
    no = int(req.get("ChallengeScheduleIndex") or 0)
    stage = int(schedule(no).get("challengeStageIndex") or 0)
    state = G.load_state() or {}
    pr = state.get("timeattack", {}).get(str(no), {})
    mopup_day = time.strftime("%Y-%m-%d")
    plays = int(pr.get("plays") or 0) if pr.get("day") == mopup_day else 0
    best = int(pr.get("best") or 0)
    tim = team(pr)
    fighters = []
    for c in G.owned_characters(state):
        fighters.append({"ChallengeScheduleIndex": no, "ChallengeStageIndex": stage,
                         "OrderByNo": len(fighters) + 1, "RandomFlag": 1, "CharacterIndex": c["index"]})
    return G.ok(ServerUtcTime=G.now_ms(),
                ChallengePlayInfo={"ChallengeScheduleIndex": no, "ChallengeStageIndex": stage, "BattleType": 1,
                                   "CharacterIndex1": tim[0], "CharacterIndex2": tim[1], "CharacterIndex3": tim[2],
                                   "SupportCharacterIndex1": 0, "SupportCharacterIndex2": 0,
                                   "SupportCharacterIndex3": 0, "TermPlayCount": plays, "DayPlayCount": plays,
                                   "TotalPlayCount": int(pr.get("total") or 0),
                                   "Term": int(time.strftime("%Y%m%d") + "01"),
                                   "BattleResult": 1 if best else 0, "FirstPlayRewardTime": 0,
                                   "ScoreRewardList": ",".join(str(i) for i in pr.get("missions") or [])},
                UserPlayList=[{"ChallengeScheduleIndex": no, "Term": int(time.strftime("%Y%m%d") + "01")}],
                ChallengeCharacterInfoList=fighters, ChallengeWeekRankingInfoList=[],
                ChallengeCharacterInfoStrikerList=[], blockUserInfoList=[])


@G.api("challenge/eventStart")
def ta_start(req):
    no = int(req.get("ChallengeScheduleIndex") or 0)
    tim = [int(c.get("CharacterIndex") or 0) for c in req.get("CharacterList") or [] if c.get("CharacterIndex")]
    with G._lock:
        state = G.load_state()
        pr = state.setdefault("timeattack", {}).setdefault(str(no), {})
        pr["run"] = G.now_ms()
        pr["team"] = (tim + [0, 0, 0])[:3]
        G.save_state(state)
    return G.ok(StrikerType=0, StrikerUsn=0, StrikerGameDb=0, StrikerNickName="", StrikerCharacter=None,
                ChallengePlayToken=G.now_ms(), PlayStrikeTime=0, RankingValue=int(pr.get("best") or 0),
                LuckySpawn=0, StrikerBattleCardList=[], CharacterCoresList=[], DropLuckyList=[], DropJacoList=[],
                DropEliteList=[], DropBossList=[], DropGimmickList=[], StrikerImprintStoneList=[],
                StrikerAwakenCoreList=[], StrikerAccountGrowthStatList=[], DropGoldLucky=0, DropGoldJaco=0,
                DropGoldElite=0, DropGoldBoss=0, DropGoldGimmick1=0, DropGoldGimmick2=0, DropGoldGimmick3=0,
                AccountMoney=G.money(state))


@G.api("challenge/eventEnd")
def ta_end(req):
    no = int(req.get("ChallengeScheduleIndex") or 0)
    sc = schedule(no)
    stage = int(sc.get("challengeStageIndex") or 0)
    won = int(req.get("BattleResult") or 0) == G.WIN
    seconds = int(req.get("ClearTime") or 0)
    ms = int(req.get("ClearRankTime") or 0) or seconds * 1000
    day = time.strftime("%Y-%m-%d")
    out = {k: [] for k in ("RewardItemList", "RewardCharacterList", "RewardBattleCardList",
                           "RewardImprintStoneList", "presetCharacterReward", "presetCharacterCoreReward")}
    first = 0
    with G._lock:
        state = G.load_state()
        pr = state.setdefault("timeattack", {}).setdefault(str(no), {})
        if won and no:
            if not int(pr.get("total") or 0):
                first = 1
            pr["total"] = int(pr.get("total") or 0) + 1
            pr["plays"] = (int(pr.get("plays") or 0) if pr.get("day") == day else 0) + 1
            pr["day"] = day
            rewards = []
            if pr.get("reward_day") != day:
                pr["reward_day"] = day
                rewards += G.give_rewards(state, sc.get("challengeRewardGroup", 0))[0]
            done = [int(i) for i in pr.get("missions") or []]
            for r in score_rows(no):
                i = int(r["challengeScoreIndex"])
                if i not in done and seconds <= int(r.get("needTime") or 0):
                    done.append(i)
                    rewards += G.give_rewards(state, r.get("scoreRewardGroup", 0))[0]
            pr["missions"] = sorted(done)
            if not pr.get("best") or ms < int(pr["best"]):
                pr["best"] = ms
                pr["cp"] = int(req.get("TeamPower") or 0)
                pr["t"] = G.now_ms()
            account = req.get("PlayerAccount") or {}
            before = max(state.get("exp", 0), int(account.get("Exp") or 0))
            state["exp"] = before + G.QUEST_EVENT_EXP_PER_AP * TA_AP
            out["RewardItemList"] = [{"ItemIndex": r["ContentsIndex"], "Qty": r["ContentsCount"], "Lock": 0,
                                      "UpdateTime": G.now_ms()} for r in rewards if r["GoodsType"] == G.ITEM_GOODS]
            out["AccountLevelUpFlag"], out["AccountLevelUpRewardList"] = G.apply_rank_up(state, before)
        G.save_state(state)
    out.update(ChallengeStageIndex=stage, BattleResult=int(req.get("BattleResult") or 0), FirstClearFlag=first,
               PostSendFlag=False,
               ChallengeTermInfo={"Term": int(time.strftime("%Y%m%d") + "01"),
                                  "TermPlayCount": int(pr.get("plays") or 0) if pr.get("day") == day else 0,
                                  "DayPlayCount": int(pr.get("plays") or 0) if pr.get("day") == day else 0,
                                  "TotalPlayCount": int(pr.get("total") or 0)},
               ScoreRewardList=",".join(str(i) for i in pr.get("missions") or []),
               CharacterList=[], AccountMoney=G.money(state),
               PlayerAccount=G.apidefaults.default("PlayerAccount", Usn=G.USN, Exp=state["exp"]))
    return G.ok(**out)


@G.api("challenge/rankingList")
def ta_ranking(req):
    no = int(req.get("ChallengeScheduleIndex") or 0)
    stage = int(schedule(no).get("challengeStageIndex") or 0)
    state = G.load_state() or {}
    pr = state.get("timeattack", {}).get(str(no), {})
    best = int(pr.get("best") or 0)
    ranking, users = [], []
    if best:
        ranking = [{"Usn": G.USN, "Score": float(best), "GameDb": 1, "NickName": state.get("nickname", "player"),
                    "Rank": 1}]
        u = {"ChallengeScheduleIndex": no, "ChallengeStageIndex": stage, "Usn": G.USN, "BattleType": 1,
             "RankingValue": best, "TeamPower": int(pr.get("cp") or 0),
             "CreateTime": int(pr.get("t") or G.now_ms()), "UpdateTime": int(pr.get("t") or G.now_ms())}
        for k, c in enumerate(team(pr), 1):
            u["CharacterIndex%d" % k] = c
            if c:
                u["Grade%d" % k] = next((x.get("grade", 3) for x in state.get("characters", [])
                                         if x["index"] == c), 3)
        users = [u]
    return G.ok(ServerUtcTime=G.now_ms(),
                MyRanking={"Rank": 1 if best else 0, "RankRate": 1 if best else 0, "Score": float(best),
                           "Time": best},
                RankingList=ranking, RankingUserList=users, FriendGuildInfoList=[])


@G.api("challenge/rankingCharacterInfo")
def ta_rank_chars(req):
    state = G.load_state() or {}
    pr = state.get("timeattack", {}).get(str(int(req.get("ChallengeScheduleIndex") or 0)), {})
    chars = []
    for c in team(pr):
        if c:
            row = next((x for x in state.get("characters", []) if x["index"] == c), {})
            chars.append({"CharacterIndex": c, "Grade": row.get("grade", 3), "Exp": row.get("exp", 0),
                          "AffectionExp": row.get("affection", 0), "Awaken": row.get("awaken", 0),
                          "AwakenExp": row.get("awakenExp", 0), "CreateTime": row.get("created", G.now_ms())})
    return G.ok(CharacterList=chars, BattleCardList=[], CharacterCoresList=[], ListBuff=[], ImprintStoneList=[],
                CharacterAwakenCoreList=[], AccountGrowthStatList=[], AccountExtraList=[], guildNo=0, guildName="")
