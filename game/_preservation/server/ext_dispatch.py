"""Dispatch: the six dispatch/* APIs (list, start, complete, reset, acceleration, ticketRecharge). Tables and the REAL /
OURS split: tools/gen_dispatch.py. State: save.json "dispatch".

Flow (client: Controller_DispatchLobby / Model_DispatchLobby / UIPopup_DispatchTimeAcceleration):
- dispatch/list -> info {dispatchIndex, ticket, ticketRefreshTime, nextTicketRefreshTime, freeResetCount} + spotList
  [{dispatchSpot = DispatchSpotGroupTable index, status 1 ready / 2 in progress, characterArray "leader,s1,s2,s3",
  endTime ms, usedCash}]. The client counts "Proceed to Dispatch n / 3" from the status 2 spots and shows "5 / 5" from ticket.
- dispatch/start {dispatchIndex, dispatchSpot, addDispatch, CharacterList: leader first + supporters}: 1 ticket.
- dispatch/complete {dispatchSpot, usedCash, adsReward}: pays the RewardGroupTable group (gold, AP, items), the Prime
  Memory Shards of an S mission to the leader, and answers the End Dispatch screen (CharacterList[0] = the leader,
  completeRewardList). Before the time is up it costs rubies (usedCash = hours left x clearPrice, the client's sum).
- dispatch/reset: re-rolls the missions not in progress; 2 free a day, then a Dispatch Reset Ticket or rubies.
- dispatch/acceleration {dispatchSpot, UsedItem}: a Dispatch Time Reduction item shortens the mission.
- dispatch/ticketRecharge {UsedItem}: a Dispatch Ticket item adds a ticket (the client allows it at 0 tickets).
Everything here beyond the table rows is OURS: the list is 1 S mission + 6 weighted C / B / A ones (the guide's sample list
had exactly one S), a completed mission leaves the map until the next reset (the client hides unused spot slots), tickets
recharge one per DispatchMainTable.dispatchSpotKeyRecoveryTime minutes, the free resets and the list renew each day,
shards: EX leader dispatchDropExCount, UE leader dispatchDropUeCount, any other leader none (web: "the fighter must be
EX"), supporters SUPPORTER_SHARDS, a 1 % "great success" pays 10x shards (web: "a very small chance of 400"), the first
list gifts a few time-reduction items, tickets and reset tickets so the speed-up and + can be tried.
Add to gameapi.py: `import ext_dispatch`, and put `ext_dispatch.schedules()` into player_poll's DownloadScheduleList (the
lobby's DISPATCH button needs the OperateSchedule category 30, index = the DispatchMainTable row).
"""
import random

import gameapi as G

MAIN_INDEX = 1
OPS_CATEGORY = 30                 # EOperateCategory.DispatchEvent
STATUS_READY, STATUS_PROCESS = 1, 2
LEADER_ONLY = 0
SUPPORTER_SHARDS = {"ue": 10, "ex": 5}      # ours: the video says other members get some, "mostly for ultimates"
DONE_MARGIN_MS = 60000
ADS_DISPATCH = 12                           # AdsRewardTable row of the lobby's Ads unit (AdsType 12 = Dispatch)
GREAT_SUCCESS_CHANCE = 0.01
GREAT_SUCCESS_SHARDS = 10                   # x the normal count (40 -> 400)
GIFT = {1325: 10, 1326: 5, 1327: 2}         # once: 30M time reduction, Dispatch Ticket, Dispatch Reset Ticket
MINUTES = {1325: 30, 1313: 60, 1314: 120}   # what a time-reduction item takes off (ItemTable.onUseGetValue of 1313 / 1314 is 1)
SHARD_BASE = 7_000_000                      # shared naming: PrimeMemoryShard_<characterIndex> = 7,000,000 + characterIndex
UE_FRAME = 110
ITEM_GOODS = 13


def schedules():
    """OperateSchedule entry for player/poll's DownloadScheduleList (always open)."""
    return [G.apidefaults.default("OperateSchedule", Version=1, Category=OPS_CATEGORY, SubCategory=0, Index=MAIN_INDEX,
                                  Detail=G.apidefaults.default("OperateScheduleData", SubGroup=[MAIN_INDEX],
                                                               OffOnSched=1))]


# ---------------------------------------------------------------- tables
def main_row():
    return next((r for r in G.table_rows("DispatchMainTable") if r.get("dispatchMainIndex") == MAIN_INDEX), None)


def spot_rows(main):
    group = int(str(main.get("dispatchSpotGroup") or 0).split(",")[0] or 0)
    return {r["dispatchSpotGroupIndex"]: r for r in G.table_rows("DispatchSpotGroupTable")
            if r.get("dispatchSpotGroup") == group}


def error(code, message):
    return {"ResultCode": code, "ResultMessage": message}


# ---------------------------------------------------------------- state
def dstate(state, main):
    """state["dispatch"], created on first use; renewed (free resets, mission list) on a new day."""
    d = state.get("dispatch")
    if not d:
        d = state["dispatch"] = {"tickets": int(main["dispatchSpotKeyMax"]), "ticketNext": 0, "ticketLast": G.now_ms(),
                                 "resets": 0, "day": G.soul_day(), "list": [], "spots": {}, "gift": False}
    now = G.now_ms()
    # tickets: one more every dispatchSpotKeyRecoveryTime minutes while under the max
    top, step = int(main["dispatchSpotKeyMax"]), max(1, int(main["dispatchSpotKeyRecoveryTime"])) * 60000
    while d["tickets"] < top and d["ticketNext"] and d["ticketNext"] <= now:
        d["tickets"] += 1
        d["ticketLast"] = d["ticketNext"]
        d["ticketNext"] = d["ticketNext"] + step if d["tickets"] < top else 0
    if d["tickets"] >= top:
        d["tickets"], d["ticketNext"] = top, 0
    if d["day"] != G.soul_day():
        d["day"], d["resets"] = G.soul_day(), 0
        reroll(state, main)
    if not d["gift"]:
        d["gift"] = True
        inv = G.items(state)
        for k, n in GIFT.items():
            inv[str(k)] = int(inv.get(str(k), 0)) + n
    if not d["list"] and not any(s["status"] == STATUS_PROCESS for s in d["spots"].values()):
        reroll(state, main)
    return d


def take_ticket(d, main):
    d["tickets"] -= 1
    if not d["ticketNext"]:
        d["ticketNext"] = G.now_ms() + max(1, int(main["dispatchSpotKeyRecoveryTime"])) * 60000


def reroll(state, main):
    """New list: the missions in progress stay, the rest are 1 S mission + weighted C / B / A ones (distinct rows)."""
    d = state["dispatch"]
    rows = spot_rows(main)
    rank = G.account_level(state.get("exp", 0))
    kept = {i: s for i, s in d["spots"].items() if s["status"] == STATUS_PROCESS and int(i) in rows}
    pool = [r for r in rows.values() if r["dispatchSpotRankStart"] <= rank <= r["dispatchSpotRankEnd"]
            and str(r["dispatchSpotGroupIndex"]) not in kept]
    top = max((r["dispatchSpotClass"] for r in rows.values()), default=0)
    want = int(main["dispatchSpotCountMax"]) - len(kept)
    pick = []

    def draw(candidates, n):
        candidates = list(candidates)
        for _ in range(min(n, len(candidates))):
            weights = [max(1, c.get("spotProbability", 1)) for c in candidates]
            c = random.choices(candidates, weights)[0]
            candidates.remove(c)
            pick.append(c)

    if not any(rows[int(i)]["dispatchSpotClass"] == top for i in kept):
        draw([r for r in pool if r["dispatchSpotClass"] == top], 1)
    draw([r for r in pool if r not in pick and r["dispatchSpotClass"] != top], want - len(pick))
    draw([r for r in pool if r not in pick], want - len(pick))           # fewer than 7 usable missions: top up
    pick.sort(key=lambda r: (r["dispatchSpotClass"], r["dispatchSpotTime"], r["dispatchSpotGroupIndex"]))
    d["spots"] = dict(kept)
    for r in pick:
        d["spots"][str(r["dispatchSpotGroupIndex"])] = {"status": STATUS_READY, "chars": [], "end": 0, "cash": 0}
    d["list"] = [int(i) for i in list(kept) + [str(r["dispatchSpotGroupIndex"]) for r in pick]]


def spot_json(index, s):
    # characterArray must be null (not "") while nobody is sent: UIUnit_DispatchUnit.Initialize tests the string for null;
    # "" takes the "has a leader" branch, DispatchSpot.LeaderCharacter() returns null for "" and the NullReference aborts the
    # whole UIView_DispatchLobby.SetLobbyUI (every spot keeps the prefab placeholder, the header never gets its text)
    return G.apidefaults.default("DispatchSpot", dispatchSpot=int(index), status=s["status"],
                                 characterArray=",".join(str(c) for c in s["chars"]) or None, endTime=s["end"],
                                 usedCash=s.get("cash", 0))


def info_json(d, main):
    return G.apidefaults.default("DispatchInfo", dispatchIndex=MAIN_INDEX, ticket=d["tickets"],
                                 ticketRefreshTime=d["ticketLast"], nextTicketRefreshTime=d["ticketNext"],
                                 freeResetCount=d["resets"])


def spot_list(d):
    return [spot_json(i, d["spots"][str(i)]) for i in d["list"] if str(i) in d["spots"]]


def busy(d):
    return {c for s in d["spots"].values() if s["status"] == STATUS_PROCESS for c in s["chars"]}


def wallet(state):
    return state.setdefault("money", {})


def spend_rubies(state, n):
    have = G.money(state)["Cash"]
    if n > have:
        return False
    wallet(state)["Cash"] = have - n
    return True


def used_item(req):
    it = req.get("UsedItem") or {}
    return int(it.get("ItemIndex") or 0), max(1, int(it.get("Qty") or 1))


def item_count(state, index):
    return int(G.items(state).get(str(index), 0))


def request(req, work):
    """Run work(state, main, d) under the lock; save unless it returned an error reply."""
    with G._lock:
        state = G.load_state()
        main = main_row()
        if state is None or main is None:
            return error(1, "no account" if state is None else "dispatch is not built")
        d = dstate(state, main)
        reply = work(state, main, d)
        G.save_state(state)
        return reply


# ---------------------------------------------------------------- handlers
@G.api("dispatch/list")
def dispatch_list(req):
    return request(req, lambda state, main, d: G.ok(info=info_json(d, main), spotList=spot_list(d)))


@G.api("dispatch/start")
def dispatch_start(req):
    def work(state, main, d):
        index = str(int(req.get("dispatchSpot") or 0))
        spot, rows = d["spots"].get(index), spot_rows(main)
        chars = [int(c) for c in req.get("CharacterList") or []]
        if spot is None or spot["status"] != STATUS_READY or int(index) not in rows:
            return error(2, "no such mission")
        row = rows[int(index)]
        if len(chars) != int(row["dispatchSupportCount"]) + 1 or len(set(chars)) != len(chars):
            return error(3, "wrong team size")
        have = {c["index"] for c in G.owned_characters(state)}
        if any(c not in have or c in busy(d) for c in chars):
            return error(4, "a fighter is not available")
        if d["tickets"] < 1:
            return error(5, "no dispatch ticket")
        if sum(1 for s in d["spots"].values() if s["status"] == STATUS_PROCESS) >= int(main["dispatchSpotMax"]):
            return error(6, "all dispatch teams are out")
        take_ticket(d, main)
        spot.update(status=STATUS_PROCESS, chars=chars, end=G.now_ms() + int(row["dispatchSpotTime"]) * 60000, cash=0)
        return G.ok(info=info_json(d, main), spot=spot_json(index, spot), accountMoney=G.money(state))
    return request(req, work)


def class_of(state, index):
    """'ue' / 'ex' / '' for a fighter (CharacterTable.frameGrade 110 = UE; 100 or a changed-up one = EX)"""
    row = next((r for r in G.table_rows("CharacterTable") if r["characterIndex"] == index), {})
    if row.get("frameGrade") == UE_FRAME:
        return "ue"
    saved = next((c for c in state["characters"] if c["index"] == index), {})
    return "ex" if saved.get("ex") or index in G.ex_tables()[2] else ""


def shard_rewards(state, row, chars, great):
    """{fighter: shard count} of a finished S mission (the row's dropEx / dropUe flags)."""
    out = {}
    if not (row.get("dispatchDropEx") or row.get("dispatchDropUe")):
        return out
    for n, c in enumerate(chars):
        kind = class_of(state, c)
        if n == 0:
            count = row["dispatchDropUeCount"] if kind == "ue" else row["dispatchDropExCount"] if kind == "ex" else 0
        else:
            count = 0 if LEADER_ONLY else SUPPORTER_SHARDS.get(kind, 0)
        if count:
            out[c] = count * (GREAT_SUCCESS_SHARDS if great and n == 0 else 1)
    return out


@G.api("dispatch/complete")
def dispatch_complete(req):
    def work(state, main, d):
        index = str(int(req.get("dispatchSpot") or 0))
        spot, rows = d["spots"].get(index), spot_rows(main)
        if spot is None or spot["status"] != STATUS_PROCESS or int(index) not in rows:
            return error(2, "no mission in progress")
        row = rows[int(index)]
        left = spot["end"] - G.now_ms()
        paid = int(req.get("usedCash") or 0)
        if left > 0:
            if paid <= 0 or not spend_rubies(state, paid):
                return error(7, "the mission is not finished")
        ads = bool(req.get("adsReward"))
        great = G.random.random() < GREAT_SUCCESS_CHANCE
        contents, ids, _ = G.give_rewards(state, row["dispatchSpotReward"])
        if ads:                                  # no ads offline: the client never asks, but a doubled reward is honoured
            more, more_ids, _ = G.give_rewards(state, row["dispatchSpotReward"])
            contents, ids = contents + more, ids + more_ids
        inv = G.items(state)
        for c, n in shard_rewards(state, row, spot["chars"], great).items():
            item = SHARD_BASE + c
            inv[str(item)] = int(inv.get(str(item), 0)) + n
            ids.append(item)
            contents.append(G.reward(ITEM_GOODS, n, item))
        simple = G.simple(G.character_state(state, spot["chars"][0]), "CharacterSimple")
        del d["spots"][index]
        d["list"] = [i for i in d["list"] if str(i) != index]
        return G.ok(AccountMoney=G.money(state), CharacterList=[simple], RewardCharacterList=[], RewardBattleCardList=[],
                    RewardItemList=G.item_list(state, sorted(set(ids))), RewardImprintStoneList=[],
                    completeRewardList=contents, PostSendFlag=False, presetCharacterList=[],
                    presetCharacterCoreList=[], successType=2 if great else 1, adsReward=ads)
    return request(req, work)


@G.api("dispatch/reset")
def dispatch_reset(req):
    def work(state, main, d):
        remain = None
        if d["resets"] < int(main["dispatchSpotResetFree"]):
            d["resets"] += 1
        else:
            item, qty = used_item(req)
            price = int(req.get("usedCash") or 0)
            if item and item == int(main["dispatchSpotResetItem"]) and item_count(state, item) >= qty:
                G.use_items(state, [{"ItemIndex": item, "Qty": qty}])
                remain = G.item_list(state, [item])[0]
            elif not (price and price >= int(main["dispatchSpotResetPrice"]) and spend_rubies(state, price)):
                return error(8, "no reset left")
        reroll(state, main)
        return G.ok(AccountMoney=G.money(state), RemainItem=remain)
    return request(req, work)


@G.api("dispatch/acceleration")
def dispatch_acceleration(req):
    def work(state, main, d):
        index = str(int(req.get("dispatchSpot") or 0))
        spot = d["spots"].get(index)
        item, qty = used_item(req)
        if spot is None or spot["status"] != STATUS_PROCESS or item not in MINUTES or item_count(state, item) < qty:
            return error(9, "cannot speed up")
        G.use_items(state, [{"ItemIndex": item, "Qty": qty}])
        spot["end"] = spot["end"] - MINUTES[item] * qty * 60000
        if spot["end"] <= G.now_ms():             # finished: put the end a minute back, the client's clock (dtServerTimeNow)
            spot["end"] = G.now_ms() - DONE_MARGIN_MS   # lags the reply, and a spot only shows "Dispatch Complete" once passed
        return G.ok(spot=spot_json(index, spot), RemainItem=G.item_list(state, [item])[0])
    return request(req, work)


@G.api("ads/adsStart")
def ads_start(req):
    """The Skip button of the Dispatch Complete ads popup (UIUnit_Ads.SendAdsSkip: adsStart, then adsReward). No ads offline."""
    return G.ok(adsSkipDateTime=0)


@G.api("ads/adsReward")
def ads_reward(req):
    """Answers the skip: the client then sends dispatch/complete itself (RecvAdsReward -> message 0x386 -> SendDispatchComplete)."""
    with G._lock:
        state = G.load_state()
        return G.ok(AccountMoney=G.money(state) if state else None, RewardCharacterList=[], RewardBattleCardList=[],
                    RewardItemList=[], PostSendFlag=False, AdsList=[], ServerUtcTime=G.now_ms(), RewardList=[],
                    RewardImprintStoneList=[], presetCharacterReward=[], presetCharacterCoreReward=[])


@G.api("dispatch/ticketRecharge")
def dispatch_ticket_recharge(req):
    def work(state, main, d):
        item, qty = used_item(req)
        if item != int(main["dispatchKeyItemIndex"]) or item_count(state, item) < qty:
            return error(10, "no dispatch ticket item")
        top = int(main["dispatchSpotKeyMax"])
        if d["tickets"] >= top:
            return error(11, "tickets are full")
        qty = min(qty, top - d["tickets"])
        G.use_items(state, [{"ItemIndex": item, "Qty": qty}])
        d["tickets"] += qty
        if d["tickets"] >= top:
            d["ticketNext"] = 0
        return G.ok(info=info_json(d, main), RemainItem=G.item_list(state, [item])[0])
    return request(req, work)


@G.api("character/stageEntryList")
def stage_entry_list(req):
    """Which fighters a content accepts (FighterEntryManager.RecvStageEntry; Select Fighter lists CharacterIndexList).
    Only Dispatch has StageEntryList rows in our build (tools/gen_dispatch.py: one "any fighter" row), so: every fighter
    the account owns, no strikers (OURS; the real limits per mission are unknown)."""
    with G._lock:
        state = G.load_state()
        if state is None:
            return error(1, "no account")
        return G.ok(CharacterIndexList=sorted(c["index"] for c in G.owned_characters(state)), StrikerIndexList=[])
