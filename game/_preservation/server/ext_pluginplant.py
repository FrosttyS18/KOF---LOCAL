"""Plugin Plant - the client's equipmentDungeon/* (tools/gen_pluginplant.py has the tables and the REAL / OURS split;
client notes in recon/plugin_plant_client.md).

save.json "pluginPlant": {questEventIndex: {"diff": EquipmentDungeonDifficulty index, "stage": questEventStageIndex,
"chars": [3], "support": [3], "relation": int, "hp": [3], "active": 0/1 (a run in progress: the team is fixed),
"lastClear": the highest cleared tier's difficulty index, "cleared": [questEventStageIndex ...] (first clears)}}.
On the wire (REA): EquipmentDungeonWEBData.equipmentDungeonStageIndex is the QuestEventStage index (the client looks
it up in its QuestEventStage list; our EquipmentDungeonStage rows use the same number), changeFlag 0 = the team may
change (no run), 1 = a run is on (EquipmentDungeonController.TeamChangeFlag = changeFlag == 0); lastClearDifficultyIndex
lets AUTO play a tier (IsAvailableAutoPlay = difficulty <= lastClear).
A win pays the stage's clear group (gold), rolls its module drop group (RewardGroupTable 9,160,000 + 10 x tier + stage,
randomRewardProbability / 10,000 each) and creates plugins of the plant's colour (ext_plugins.new_plugin; grade odds and
power from EquipmentRewardTable 100 + tier, plugin from EquipmentRewardGroupTable group 100 + colour): 1 a stage, 2 on
the last; the last stage also pays the tier clear group (AllClearRewardList) and, once a day per tier, the daily first
clear group (DailyAllClearRewardList), then the run ends (stage 1, team free, HP full). A loss keeps the run (HP saved).
The client reads (ParseEquipmentDungeonEnd, BattleResult 1 only): ClearRewardList + GlobalDropRewardList (RESULT
icons), rewardItemList (added to the bag), equipmentList (added to the plugin inventory and shown), AccountMoney.
OURS: the tier lock (start of a tier above the last cleared + 1 is refused: the client has no condition for it), drops.
"""
import random

import gameapi as G
import ext_plugins as PL

EVENT0, COLOURS, TIERS, STAGES = 9100, range(1, 6), 10, 6
DROP0, TIER_CLEAR0, DAILY0, CLEAR0 = 9_160_000, 9_170_000, 9_180_000, 9_150_000
REWARD0 = 100
FAIL = {"ResultCode": 1, "ResultMessage": "plugin plant refused"}

# QuestEventGroup.get_ScheduleTableData -> DungeonController.IsOpenDungeon(EDungeonType, scheduleIndex): Growth (2) for
# questEventType 3, AwakenQuest (7) for type 6, Event (3) for any other type; the type is the dungeon category's
# OperateSchedule SubCategory. The plants are type 9 -> Category 2 / SubCategory 3 (sent as SubCategory 2 the group had
# no schedule and BATTLE gave "ShortCut Err Cannot Go Shop", 2026-11-09).
PLANT_SUBCATEGORY = 3                    # EDungeonType.Event


def schedules():
    return [G.apidefaults.default("OperateSchedule", Version=1, Category=G.DUNGEON_CATEGORY, SubCategory=PLANT_SUBCATEGORY,
                                  Index=EVENT0 + c, Detail=G.apidefaults.default(
                                      "OperateScheduleData", SubGroup=[EVENT0 + c], OffOnSched=G.ALWAYS_OPEN))
            for c in COLOURS]


for _c in COLOURS:                       # drop any category-2 copies an older version added
    if EVENT0 + _c in G.DUNGEON_SCHEDULES:
        G.DUNGEON_SCHEDULES.remove(EVENT0 + _c)


def _with_schedules(fn):
    def handler(req):
        out = fn(req)
        if isinstance(out, dict) and isinstance(out.get("DownloadScheduleList"), list):
            out["DownloadScheduleList"] = out["DownloadScheduleList"] + schedules()
        return out
    return handler


for _name in ("player/poll", "session/poll"):
    G.APIS[_name] = _with_schedules(G.APIS[_name])


def colour(event):
    return int(event) - EVENT0


def is_plant(event):
    return 1 <= colour(event) <= 5


def stage_index(c, t, s):
    return 910000 + c * 1000 + t * 10 + s


def split(stage):
    """questEventStageIndex -> (colour, tier, stage no.)"""
    rest = stage - 910000
    return rest // 1000, rest % 1000 // 10, rest % 10


def diff_index(c, t):
    return c * 100 + t


def diff_row(index):
    return next((r for r in G.table_rows("EquipmentDungeonDifficultyTable")
                 if r["equipmentDungeonDifficultyIndex"] == index), {})


def run_of(state, event):
    runs = state.setdefault("pluginPlant", {})
    c = colour(event)
    return runs.setdefault(str(event), {"diff": diff_index(c, 1), "stage": stage_index(c, 1, 1), "chars": [0, 0, 0],
                                        "support": [0, 0, 0], "relation": 0, "hp": [0, 0, 0], "active": 0,
                                        "lastClear": 0, "cleared": []})


def web(event, run, state=None):
    ch, sup, hp = (list(run[k]) + [0, 0, 0] for k in ("chars", "support", "hp"))
    if not run.get("active") and not any(ch[:3]) and state is not None:
        # No run: EquipmentDungeonController.SetTeamDeck (TeamChangeFlag on) rebuilds SeqDataList from these indexes
        # and every fighter missing from it reads HP ratio 0 = "KO" on the ready screen (REA + in game, 2026-11-09).
        # The client only sends deckUpdate once a run is fixed, so report the deck it shows (story TEAM 1).
        d = next((d for d in state.get("decks", []) if d["no"] == PLANT_DECK), None) or             next((d for d in state.get("decks", []) if d["no"] == 1), None)
        if d:
            ch = list(d["chars"]) + [0, 0, 0]
            sup = list(d.get("strikers") or [0, 0, 0]) + [0, 0, 0]
    return G.apidefaults.default(
        "EquipmentDungeonWEBData", questEventIndex=int(event), equipmentDungeonDifficultyIndex=run["diff"],
        equipmentDungeonStageIndex=run["stage"], characterIndex1=ch[0], characterIndex2=ch[1], characterIndex3=ch[2],
        supportCharacterIndex1=sup[0], supportCharacterIndex2=sup[1], supportCharacterIndex3=sup[2],
        character1Hp=hp[0], character2Hp=hp[1], character3Hp=hp[2], teamRelationIndex=run.get("relation", 0),
        changeFlag=1 if run.get("active") else 0, dailyRewardTime=0, dailyRewardRemainTime=0,
        lastClearDifficultyIndex=run.get("lastClear", 0))


def end_run(run):
    c, t, _ = split(run["stage"])
    run.update(stage=stage_index(c, t, 1), active=0, hp=[0, 0, 0])


def handle(req, fn):
    event = int(req.get("questEventIndex") or 0)
    if not is_plant(event):
        return FAIL
    with G._lock:
        state = G.load_state()
        if state is None:
            return FAIL
        run = run_of(state, event)
        out = fn(state, event, run)
        if out.get("ResultCode") == 0:
            sync_deck(state, run)
            G.save_state(state)
        return out


PLANT_DECK = 72      # TeamDeckType.StageEntryEvent: QuestEventTable.teamDeckType of the plants; the client's
                     # EquipmentDungeonController.OriginTeamDeck is a TeamDeck(72) too (REA 2026-11-09)


def sync_deck(state, run):
    """Keep save deck 72 (sent in player/profile TeamDeckList) = the plant team, so the ready screen shows it."""
    chars = [int(x) for x in (run.get("chars") or [])][:3]
    if not any(chars):
        return
    decks = state.setdefault("decks", [])
    d = next((d for d in decks if d["no"] == PLANT_DECK), None)
    if d is None:
        d = {"no": PLANT_DECK}
        decks.append(d)
    d["chars"] = (chars + [0, 0, 0])[:3]
    d["strikers"] = ([int(x) for x in (run.get("support") or [])] + [0, 0, 0])[:3]
    d["relation"] = int(run.get("relation") or 0)


@G.api("equipmentDungeon/info")
def info(req):
    return handle(req, lambda state, event, run: G.ok(equipmentDungeon=web(event, run, state)))


@G.api("equipmentDungeon/deckUpdate")
def deck_update(req):
    def fn(state, event, run):
        chars = [int(x) for x in (req.get("characterIndexList") or [])][:3]
        sup = [int(x) for x in (req.get("supportCharacterIndexList") or [])][:3]
        run.update(chars=chars + [0] * (3 - len(chars)), support=sup + [0] * (3 - len(sup)),
                   relation=int(req.get("teamRelationIndex") or 0))
        return G.ok(characterIndexList=run["chars"], supportCharacterIndexList=run["support"],
                    teamRelationIndex=run["relation"])
    return handle(req, fn)


@G.api("equipmentDungeon/deckReset")
def deck_reset(req):
    def fn(state, event, run):
        end_run(run)
        run.update(chars=[0, 0, 0], support=[0, 0, 0], relation=0)
        return G.ok()
    return handle(req, fn)


@G.api("equipmentDungeon/reset")
def reset(req):
    """REAL: back to stage 1 of the plant at no cost; the team stays chosen (deckReset clears it)."""
    def fn(state, event, run):
        end_run(run)
        return G.ok(equipmentDungeon=web(event, run, state))
    return handle(req, fn)


@G.api("equipmentDungeon/start")
def start(req):
    def fn(state, event, run):
        stage = int(req.get("equipmentDungeonStageIndex") or 0)
        c, t, s = split(stage)
        diff = int(req.get("equipmentDungeonDifficultyIndex") or diff_index(c, t))
        if c != colour(event) or not (1 <= t <= TIERS and 1 <= s <= STAGES) or diff != diff_index(c, t):
            return FAIL
        last_tier = run.get("lastClear", 0) % 100
        if t > last_tier + 1:
            return {"ResultCode": 1, "ResultMessage": f"Clear Tier {t - 1} first."}
        if run.get("active") and (run["diff"] != diff or run["stage"] != stage):
            return {"ResultCode": 1, "ResultMessage": "A run is in progress: reset it first."}
        if not run.get("active"):
            if s != 1:
                return {"ResultCode": 1, "ResultMessage": "A run starts at Stage 1."}
            run.update(active=1, diff=diff, stage=stage)
        if not any(run.get("chars") or []):
            # The client sends deckUpdate only when the team changes mid-run: the run's team is the one it starts
            # with (characterList / playDeckInfo). Without it the next info named fighter 0 -> every slot "KO".
            team = [int(x.get("CharacterIndex") or x.get("characterIndex") or 0)
                    for x in (req.get("characterList") or []) if isinstance(x, dict)]
            deck = req.get("playDeckInfo") or {}
            team = [t for t in team if t] or [int(x) for x in (deck.get("PlayFighterArray") or []) if x]
            strikers = [int(x) for x in (deck.get("PlayStrikerArray") or [])]
            run["chars"] = (team + [0, 0, 0])[:3]
            run["support"] = (strikers + [0, 0, 0])[:3]
        hp =[int(req.get(f"characterHp{i}") or 0) for i in (1, 2, 3)]
        if any(hp):
            run["hp"] = hp
        token = G.now_ms()
        run["token"] = token
        gold = sum(r.get("contentsCountMin", 0) for r in G.table_rows("RewardGroupTable")
                   if r.get("rewardGroup") == CLEAR0 + c * 1000 + t * 10 + s and r.get("rewardType") == G.GOLD_GOODS)
        return G.ok(playToken=token, DropGoldJaco=gold * 2 // 3, DropGoldBoss=gold - gold * 2 // 3)
    return handle(req, fn)


def roll_drops(group, rng=random):
    out = []
    for r in G.table_rows("RewardGroupTable"):
        if r.get("rewardGroup") == group and r.get("rewardType") == G.ITEM_GOODS \
                and rng.randrange(10_000) < r.get("randomRewardProbability", 10_000):
            out.append((r["contentsIndex"], r.get("contentsCountMin", 1)))
    return out


def roll_plugins(state, c, t, count, rng=random):
    rw = next((r for r in G.table_rows("EquipmentRewardTable") if r["equipmentRewardIndex"] == REWARD0 + t), None)
    pool = [dict(x) for x in G.table_rows("EquipmentRewardGroupTable") if x["equipmentRewardGroup"] == REWARD0 + c]
    got = []
    for _ in range(count if rw and pool else 0):
        grade = PL.pick([{"g": g, "prob": rw[f"grade0{g}Prob"]} for g in range(1, 6)])["g"]
        eq = PL.pick(pool)
        level = max(1, rng.randint(rw["equipmentLvMin"], rw["equipmentLvMax"]))
        got.append(PL.new_plugin(state, eq["equipmentIndex"], grade, level))
    return got


@G.api("equipmentDungeon/end")
def end(req):
    def fn(state, event, run):
        result = int(req.get("battleResult") or 0)
        won = result == G.WIN and not int(req.get("selfCancel") or 0)
        c, t, s = split(run["stage"])
        hp = [int(req.get(f"characterHp{i}") or 0) for i in (1, 2, 3)]
        for ch in req.get("characterList") or []:          # fighter EXP / affinity as the client reports them
            if ch.get("CharacterIndex"):
                f = G.character_state(state, int(ch["CharacterIndex"]))
                f["affection"] = max(f.get("affection", 0), int(ch.get("AffectionExp") or 0))
        clear, gained, plugins, all_clear, daily_clear, first = [], [], [], [], [], False
        if won and run.get("active"):
            first = run["stage"] not in run.setdefault("cleared", [])
            if first:
                run["cleared"].append(run["stage"])
            clear = G.give_rewards(state, CLEAR0 + c * 1000 + t * 10 + s)[0]
            inv = G.items(state)
            for item, n in roll_drops(DROP0 + t * 10 + s):
                inv[str(item)] = int(inv.get(str(item), 0)) + n
                clear.append(G.reward(G.ITEM_GOODS, n, item))
            plugins = roll_plugins(state, c, t, 3)   # REAL: 3 NEW plugins on a Tier 1 result (video PE1FyEjWWAE)
            if s == STAGES:
                d = diff_index(c, t)
                row = diff_row(d)
                all_clear = G.give_rewards(state, row.get("equipmentDifficultyClearRewardGroup", TIER_CLEAR0 + d))[0]
                today = G.daily(state).setdefault("pluginPlantDaily", [])
                if d not in today:
                    today.append(d)
                    daily_clear = G.give_rewards(state, row.get("equipmentDifficultyDailyFirstClearRewardGroup",
                                                                DAILY0 + d))[0]
                run["lastClear"] = max(run.get("lastClear", 0), d)
                end_run(run)
            else:
                run.update(stage=stage_index(c, t, s + 1), hp=hp if any(hp) else run.get("hp", [0, 0, 0]))
        elif run.get("active"):
            run["hp"] = hp
        gained = {}
        for r in clear + all_clear + daily_clear:
            if r["GoodsType"] == G.ITEM_GOODS:
                gained[r["ContentsIndex"]] = gained.get(r["ContentsIndex"], 0) + r["ContentsCount"]
        worn = PL.equipped_by(state)
        return G.ok(
            resultEquipment=web(event, run, state), battleResult=result, firstClearFlag=1 if first else 0,
            accountLevelUpFlag=0, playerAccount=G.apidefaults.default("PlayerAccount", Usn=G.USN, Exp=state.get("exp", 0)),
            characterList=[G.simple(G.character_state(state, int(ch["CharacterIndex"])), "CharacterSimple",
                                    G.start_grades())
                           for ch in req.get("characterList") or [] if ch.get("CharacterIndex")],
            rewardItemList=[{"ItemIndex": k, "Qty": n, "Lock": 0, "UpdateTime": G.now_ms()} for k, n in gained.items()],
            ClearRewardList=clear, FirstClearRewardList=[], DailyAllClearRewardList=daily_clear,
            AllClearRewardList=all_clear, GlobalDropRewardList=[], AccountLevelUpRewardList=[],
            RemainItem=None, AccountMoney=G.money(state),
            equipmentList=[PL.web(state, p, worn) for p in plugins], tempEquipmentList=[], GradeUpEquipmentNoList=[])
    return handle(req, fn)
