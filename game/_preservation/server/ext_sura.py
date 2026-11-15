"""Sura Dungeon (QuestEvent 10801, questEventType 6) -- Dungeon > Challenge Dungeon (real mobile tables,
tools/import_dungeons.py; ModeTable 108).

Scene_SuraStageList reads SuraDungeonStageTable (stages 1..24 in sequence; the phase is the
suraDungeonDifficultyIndex column): suraDungeon/info answers the phase's stage states, stageStart/End
fight the stage's QuestEventStage (Scene_Single_SuraDungeon), and stageMopUp is the Auto-Clear paying
SuraDungeonDifficultyTable.suraDungeonMopUpRewardIndex (9393000x) once per requested run, listed the way
questEventMopUp lists it (RewardContentsList.Count is the run number -- NetworkManagerWEB.
TakeRewardContentsList groups by it; RewardItemList sums the items). A win pays the
stage's questEventStageClearRewardGroup every time and questEventStageFirstClearRewardGroup only on the
stage that advances "clear", like the client's own event battles (gameapi's questEventStage flow).
Progress lives in save.json "sura" ({"clear": highest stage, "max": all-time, "plays": {stage: wins},
"run": {"sid", "token"} of the battle in progress, "mopup": {"day": ymd, "n": count}}); a legacy "run"
that stored the bare stage index still reads as that stage, with no token to check.

The stage's targetConditionMainGroupIndex (1001..1024) never reaches the server: Scene_Single_SuraDungeon
applies the penalty client-side (SuraTargetConditionChecker matches the deck against PenaltyTable's
targetConditionType/SubType of the same targetConditionGroupIndex and adds PenaltyBuffTable's debuff).
PenaltyTable/PenaltyBuffTable and the BuffTable row their debuff needs are staged by
tools/import_sura_penalties.py; until that staging is applied the client reads them empty and fights
without penalties.

Auto-Clear stays unlimited per the maintainer's request (info always reports FreeMopUpPlayCount 0),
although QuestEvent 10801 itself says isAbleMopUp 0 / mopUpMaxCount 3; with nothing of a phase swept it
answers ResultCode 1 instead of inventing a reward."""
import time

import gameapi as G
import ext_phantom as P

SURA_AP = 10

EMPTY_LISTS = ("RewardItemList", "RewardBattleCardList", "RewardCharacterList", "ClearRewardList",
               "GlobalDropRewardList", "RewardContentsList", "FirstClearRewardList", "RewardImprintStoneList",
               "GuildBuffList", "presetCharacterReward", "presetCharacterCoreReward")


def fail(message):
    return {"ResultCode": 1, "ResultMessage": message}


def sura_rows():
    return (sorted(G.table_rows("SuraDungeonStageTable"), key=lambda r: int(r.get("suraDungeonStageIndex") or 0)),
            {int(r.get("suraDungeonDifficultyIndex") or 0): r for r in G.table_rows("SuraDungeonDifficultyTable")})


def progress(st, pr):
    """-> (highest stage cleared, the next stage's row, or the last one when all 24 are cleared)."""
    clear = min(int(pr.get("clear") or 0), int(st[-1]["suraDungeonStageIndex"]) if st else 0)
    return clear, next((r for r in st if int(r["suraDungeonStageIndex"]) > clear), st[-1] if st else None)


def today_count(pr):
    m = pr.get("mopup") or {}
    return int(m.get("n") or 0) if m.get("day") == time.strftime("%Y-%m-%d") else 0


def run_stage(run):
    """The stage of the battle in progress; "run" used to store the bare stage index."""
    return int(run.get("sid") or 0) if isinstance(run, dict) else int(run or 0)


@G.api("suraDungeon/info")
def sura_info(req):
    st, _df = sura_rows()
    if not st:
        return fail("SuraDungeonStageTable missing")
    with G._lock:
        state = G.load_state()
        if state is None:
            return fail("no account")
        pr = state.setdefault("sura", {})
        clear, nxt = progress(st, pr)
        phase = int((nxt or {}).get("suraDungeonDifficultyIndex") or 1)
        G.save_state(state)
    plays = pr.get("plays") or {}
    return G.ok(SuraDungeon={"SuraDungeonDifficultyIndex": phase, "SuraDungeonClearStageIndex": clear,
                             "SuraDungeonClearStageIndexMax": max(clear, int(pr.get("max") or 0)),
                             "FreeMopUpPlayCount": 0, "PayMopUpPlayCount": 0},
                SuraDungeonStageList=[{"SuraDungeonStageIndex": int(r["suraDungeonStageIndex"]),
                                       "BattleResult": 1 if int(r["suraDungeonStageIndex"]) <= clear else 0,
                                       "PlayCount": max(1, int(plays.get(str(r["suraDungeonStageIndex"])) or 0))
                                       if int(r["suraDungeonStageIndex"]) <= clear else 0}
                                      for r in st if int(r.get("suraDungeonDifficultyIndex") or 0) == phase])


@G.api("suraDungeon/stageStart")
def sura_start(req):
    st, _df = sura_rows()
    sid = int(req.get("SuraDungeonStageIndex") or 0)
    with G._lock:
        state = G.load_state()
        if state is None:
            return fail("no account")
        pr = state.setdefault("sura", {})
        clear, _nxt = progress(st, pr)
        if not any(int(r.get("suraDungeonStageIndex") or 0) == sid for r in st) or sid > clear + 1:
            return fail("Sura stage %d not open" % sid)
        token = G.now_ms()
        pr["run"] = {"sid": sid, "token": token}
        G.save_state(state)
    return G.ok(PlayToken=token)


@G.api("suraDungeon/stageEnd")
def sura_end(req):
    st, _df = sura_rows()
    sid = int(req.get("SuraDungeonStageIndex") or 0)
    row = next((r for r in st if int(r.get("suraDungeonStageIndex") or 0) == sid), None)
    if row is None:
        return fail("no Sura stage %d" % sid)
    q = G.quest_event_stage_row(int(row.get("questEventStageIndex") or 0))
    won = int(req.get("BattleResult") or 0) == G.WIN
    token = int(req.get("PlayToken") or 0)
    out = {k: [] for k in EMPTY_LISTS}
    first = 0
    with G._lock:
        state = G.load_state()
        if state is None:
            return fail("no account")
        pr = state.setdefault("sura", {})
        run = pr.get("run") or 0
        # the token check stays soft (relayDungeon's rule): reject only when both sides carry one
        if run_stage(run) != sid or (token and isinstance(run, dict) and int(run.get("token") or 0)
                                     and int(run["token"]) != token):
            return fail("no Sura run in progress")
        if won and not q:
            return fail("QuestEventStage %s missing" % row.get("questEventStageIndex"))
        pr.pop("run", None)
        if won:
            plays = pr.setdefault("plays", {})
            plays[str(sid)] = int(plays.get(str(sid)) or 0) + 1
            if sid == int(pr.get("clear") or 0) + 1:
                first = 1
                out["FirstClearRewardList"] = G.give_rewards(
                    state, q.get("questEventStageFirstClearRewardGroup", 0))[0]
                pr["clear"] = sid
                pr["max"] = max(int(pr.get("max") or 0), sid)
            out["ClearRewardList"] = G.give_rewards(state, q.get("questEventStageClearRewardGroup", 0))[0]
            out["AccountLevelUpFlag"], out["AccountLevelUpRewardList"] = P.battle_exp(state, req, SURA_AP)
        G.save_state(state)
    out.update(BattleResult=int(req.get("BattleResult") or 0), FirstClearFlag=first, PostSendFlag=False,
               AccountMoney=G.money(state),
               PlayerAccount=G.apidefaults.default("PlayerAccount", Usn=G.USN, Exp=state["exp"]))
    return G.ok(**out)


@G.api("suraDungeon/stageMopUp")
def sura_mopup(req):
    st, df = sura_rows()
    runs = max(1, int(req.get("MopUpCount") or 1))
    with G._lock:
        state = G.load_state()
        if state is None:
            return fail("no account")
        pr = state.setdefault("sura", {})
        clear, nxt = progress(st, pr)
        phase = int((nxt or {}).get("suraDungeonDifficultyIndex") or 1)
        all_done = bool(st) and clear >= int(st[-1]["suraDungeonStageIndex"])
        # Auto-Clear sweeps the last fully cleared phase: the one before the phase being played
        for_phase = phase if all_done else phase - 1
        group = int((df.get(for_phase) or {}).get("suraDungeonMopUpRewardIndex") or 0) if for_phase >= 1 else 0
        rewards = []
        if group and any(r.get("rewardGroup") == group for r in G.table_rows("RewardGroupTable")):
            for run in range(1, runs + 1):
                rewards += [G.mopup_reward(c["GoodsType"], c["ContentsCount"], run, c["ContentsIndex"])
                            for c in G.give_rewards(state, group)[0]]
        if not rewards:
            return fail("no Auto-Clear reward for Sura phase %d" % for_phase)
        pr["mopup"] = {"day": time.strftime("%Y-%m-%d"), "n": today_count(pr) + runs}
        G.save_state(state)
    out = {k: [] for k in EMPTY_LISTS + ("AdsList",)}
    out["RewardContentsList"] = rewards
    out["RewardItemList"] = G.gained_items(rewards)
    out.update(SuraDungeonDifficultyIndex=phase, PostSendFlag=False, RemainItem=None,
               AccountMoney=G.money(state),
               PlayerAccount=G.apidefaults.default("PlayerAccount", Usn=G.USN, Exp=state["exp"]))
    return G.ok(**out)
