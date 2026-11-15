"""Sura Dungeon (QuestEvent 10801, questEventType 6) -- Dungeon > Challenge Dungeon (real mobile tables,
tools/import_dungeons.py; ModeTable 108).

Scene_Single_SuraStageList reads SuraDungeonStageTable (stages 1..24 in sequence; the phase is the
suraDungeonDifficultyIndex column): suraDungeon/info answers the phase's stage states, stageStart/End
fight the stage's QuestEventStage (Scene_Single_SuraDungeon), and stageMopUp is the daily Auto-Clear
paying SuraDungeonDifficultyTable.suraDungeonMopUpRewardIndex. Progress lives in save.json "sura"
({"clear": highest stage, "max": all-time, "mopup": {"day": ymd, "n": count}})."""
import time

import gameapi as G
import ext_phantom as P

SURA_AP = 10

EMPTY_LISTS = ("RewardItemList", "RewardBattleCardList", "RewardCharacterList", "ClearRewardList",
               "GlobalDropRewardList", "RewardContentsList", "FirstClearRewardList", "RewardImprintStoneList",
               "GuildBuffList", "presetCharacterReward", "presetCharacterCoreReward")


def sura_rows():
    return (sorted(G.table_rows("SuraDungeonStageTable"), key=lambda r: int(r.get("suraDungeonStageIndex") or 0)),
            {int(r.get("suraDungeonDifficultyIndex") or 0): r for r in G.table_rows("SuraDungeonDifficultyTable")})


def today_count(pr):
    m = pr.get("mopup") or {}
    return int(m.get("n") or 0) if m.get("day") == time.strftime("%Y-%m-%d") else 0


@G.api("suraDungeon/info")
def sura_info(req):
    st, df = sura_rows()
    with G._lock:
        state = G.load_state()
        pr = state.setdefault("sura", {})
        clear = min(int(pr.get("clear") or 0), int(st[-1]["suraDungeonStageIndex"]) if st else 0)
        nxt = next((r for r in st if int(r["suraDungeonStageIndex"]) > clear), st[-1] if st else None)
        phase = int((nxt or {}).get("suraDungeonDifficultyIndex") or 1)
        G.save_state(state)
    return G.ok(SuraDungeon={"SuraDungeonDifficultyIndex": phase, "SuraDungeonClearStageIndex": clear,
                             "SuraDungeonClearStageIndexMax": max(clear, int(pr.get("max") or 0)),
                             "FreeMopUpPlayCount": 0, "PayMopUpPlayCount": 0},
                SuraDungeonStageList=[{"SuraDungeonStageIndex": int(r["suraDungeonStageIndex"]),
                                       "BattleResult": 1 if int(r["suraDungeonStageIndex"]) <= clear else 0,
                                       "PlayCount": 1 if int(r["suraDungeonStageIndex"]) <= clear else 0}
                                      for r in st if int(r.get("suraDungeonDifficultyIndex") or 0) == phase])


@G.api("suraDungeon/stageStart")
def sura_start(req):
    with G._lock:
        state = G.load_state()
        state.setdefault("sura", {})["run"] = int(req.get("SuraDungeonStageIndex") or 0)
        G.save_state(state)
    return G.ok(PlayToken=G.now_ms())


@G.api("suraDungeon/stageEnd")
def sura_end(req):
    st, _df = sura_rows()
    sid = int(req.get("SuraDungeonStageIndex") or 0)
    row = next((r for r in st if int(r.get("suraDungeonStageIndex") or 0) == sid), {})
    q = G.quest_event_stage_row(int(row.get("questEventStageIndex") or 0))
    won = int(req.get("BattleResult") or 0) == G.WIN
    out = {k: [] for k in EMPTY_LISTS}
    first = 0
    with G._lock:
        state = G.load_state()
        pr = state.setdefault("sura", {})
        if won and q:
            first_clear, clear = [], []
            if sid == int(pr.get("clear") or 0) + 1:
                first = 1
                first_clear = G.give_rewards(state, q.get("questEventStageFirstClearRewardGroup", 0))[0]
                clear = G.give_rewards(state, q.get("questEventStageClearRewardGroup", 0))[0]
                pr["clear"] = sid
                pr["max"] = max(int(pr.get("max") or 0), sid)
            out["FirstClearRewardList"] = first_clear
            out["ClearRewardList"] = clear
            out["AccountLevelUpFlag"], out["AccountLevelUpRewardList"] = P.battle_exp(state, req, SURA_AP)
        G.save_state(state)
    out.update(BattleResult=int(req.get("BattleResult") or 0), FirstClearFlag=first, PostSendFlag=False,
               AccountMoney=G.money(state),
               PlayerAccount=G.apidefaults.default("PlayerAccount", Usn=G.USN, Exp=state["exp"]))
    return G.ok(**out)


@G.api("suraDungeon/stageMopUp")
def sura_mopup(req):
    st, df = sura_rows()
    with G._lock:
        state = G.load_state()
        pr = state.setdefault("sura", {})
        clear = min(int(pr.get("clear") or 0), int(st[-1]["suraDungeonStageIndex"]) if st else 0)
        nxt = next((r for r in st if int(r["suraDungeonStageIndex"]) > clear), st[-1] if st else None)
        phase = int((nxt or {}).get("suraDungeonDifficultyIndex") or 1)
        all_done = bool(st) and clear >= int(st[-1]["suraDungeonStageIndex"])
        for_phase = phase if all_done else phase - 1
        rewards = G.give_rewards(state, (df.get(for_phase) or {}).get("suraDungeonMopUpRewardIndex", 0))[0] \
            if for_phase >= 1 else []
        if not rewards:
            rewards = [G.reward(G.GOLD_GOODS, 1000)]
            state["money"]["Gold"] = state["money"].get("Gold", 0) + 1000
        mopup = pr.get("mopup") or {}
        n = (int(mopup.get("n") or 0) if mopup.get("day") == time.strftime("%Y-%m-%d") else 0) \
            + max(1, int(req.get("MopUpCount") or 1))
        pr["mopup"] = {"day": time.strftime("%Y-%m-%d"), "n": n}
        G.save_state(state)
    out = {k: [] for k in EMPTY_LISTS + ("AdsList",)}
    out["RewardContentsList"] = [dict(r, Count=1) for r in rewards]
    out["RewardItemList"] = [{"ItemIndex": r["ContentsIndex"], "Qty": r["ContentsCount"], "Lock": 0,
                              "UpdateTime": G.now_ms()} for r in rewards if r["GoodsType"] == G.ITEM_GOODS]
    out.update(SuraDungeonDifficultyIndex=phase, PostSendFlag=False, RemainItem=None,
               AccountMoney=G.money(state),
               PlayerAccount=G.apidefaults.default("PlayerAccount", Usn=G.USN, Exp=state["exp"]))
    return G.ok(**out)
