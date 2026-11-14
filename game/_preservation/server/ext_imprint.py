"""Imprint stone enhancing (tools/gen_imprint.py has the tables and the REAL / OURS split).

imprint/enchant   one hammer (MaterialItem {ItemIndex, Qty}) and the level's gold: one roll on the hammer's ratio group row of the
                  stone's current level (ImprintEnchantRatioGroupTable via ItemTable.applyTargetIndex -> ImprintEnchantScrollTable):
                  success +1 (succWeightLv1-3: bigger jumps), nothing, or a drop (failWeightLv1-3). The fail bonus (stone "bonus",
                  BonusWeight) adds to the success weight, grows by the row's bonusSuccWeightWhenFailed per failure up to
                  ConfigTable 23208 / 100, and resets on a success. "Consecutive enhance" is the client repeating this request.
imprint/like      lock / unlock stones (save "stones" "like").
imprint/sell      stones -> gold.   imprint/disassemble   stones -> hammers (ours).   imprint/vestedReset   frees the bound fighter.
imprint/upgrade, imprint/polishing   the build has no grade-upgrade / polishing table rows (all upgradeAble 0, no polishing
                  group): refused.
save.json "stones": {"no", "index", "enchant", "created", "like", "bonus"}. Equipped stones (fighter "stones") and liked ones
are never sold / salvaged. A one-time stock of 5 plain stones (EX circle .. moon, +0) and of hammers (ONCE_ITEMS) goes to the
account (ours).
"""
import random

import gameapi as G

HAMMERS = {"41001": 60, "41002": 40, "41003": 20, "41004": 10}      # one-time stock (ours)
STOCK_STONES = (80001, 80002, 80003, 80004, 80005)                  # circle, square, hexagon, star, moon (EX)
MAX_BONUS_CONFIG = 23208
GOLD = 1
FAIL = {"ResultCode": 1, "ResultMessage": "imprint stone action refused"}

for _k, _n in HAMMERS.items():
    G.ONCE_ITEMS.setdefault(_k, _n)


def rows(table):
    return G.table_rows(table)


def stone_row(index):
    return next((r for r in rows("ImprintStoneTable") if r["imprintStoneIndex"] == index), {})


def levels(group):
    return {r["enchantLevel"]: r for r in rows("ImprintEnchantLevelGroupTable") if r["imprintEnchantLevelGroup"] == group}


def equipped(state):
    return {no for c in state.get("characters", []) for no in c.get("stones", []) if no}


def stock(state):
    """the one-time plain stones (the hammers come through ONCE_ITEMS)"""
    granted = state.setdefault("grants", [])
    if "imprint_stones_v1" not in granted:
        owned = state.setdefault("stones", [])
        top = max([e["no"] for e in owned] + [199_999])
        for i, index in enumerate(STOCK_STONES, 1):
            owned.append({"no": top + i, "index": index, "enchant": 0, "created": G.now_ms()})
        granted.append("imprint_stones_v1")


def web(e):
    return G.apidefaults.default("ImprintStoneWEBData", ImprintStoneNo=e["no"], ImprintStoneIndex=e["index"],
                                 Enchant=e.get("enchant", 0), CreateTime=e.get("created", 0), LikeFlag=e.get("like", 0),
                                 BonusWeight=e.get("bonus", 0))


def imprint_stones(state):
    stock(state)
    return [web(e) for e in state.get("stones", [])]


G.imprint_stones = imprint_stones       # the login's ImprintStoneList: + the stock, the like flag, the fail bonus


def find(state, no):
    return next((e for e in state.get("stones", []) if e["no"] == int(no or 0)), None)


def max_bonus():
    for r in rows("ConfigTable"):
        if r["configIndex"] == MAX_BONUS_CONFIG:
            return int(r.get("value1") or 0)          # 1/100 % like the weights (3000 = 30 points)
    return 0


def ratio_row(item_index, level):
    item = next((r for r in rows("ItemTable") if r["itemIndex"] == item_index), None)
    if not item or item.get("itemType") != 41:
        return None, None
    scroll = next((r for r in rows("ImprintEnchantScrollTable")
                   if r["imprintEnchantScrollIndex"] == item.get("applyTargetIndex")), None)
    if not scroll:
        return None, None
    row = next((r for r in rows("ImprintEnchantRatioGroupTable")
                if r["imprintEnchantRatioGroup"] == scroll["imprintEnchantRatioGroup"] and r["enchantLevel"] == level), None)
    return scroll, row


def roll(row, bonus):
    """-> level change. weights: +1..+4 (enchantSuccWeight, succWeightLv1-3), 0 / -1..-3 (failWeightLv0-3); the fail bonus
    moves weight from 'nothing' to +1."""
    succ = [row.get("enchantSuccWeight", 0) + bonus] + [row.get(f"succWeightLv{i}", 0) for i in (1, 2, 3)]
    fail = [max(0, row.get("failWeightLv0", 0) - bonus)] + [row.get(f"failWeightLv{i}", 0) for i in (1, 2, 3)]
    outcomes = [(i + 1, w) for i, w in enumerate(succ)] + [(-i, w) for i, w in enumerate(fail)]
    r = random.uniform(0, sum(w for _, w in outcomes) or 1)
    for delta, w in outcomes:
        r -= w
        if r <= 0 and w > 0:
            return delta
    return 0


@G.api("imprint/enchant")
def enchant(req):
    item = int((req.get("MaterialItem") or {}).get("ItemIndex") or 0)
    with G._lock:
        state = G.load_state()
        stock(state); G.items(state)   # the login shows the one-time stock unsaved: apply it before the lookup
        e = find(state, req.get("ImprintStoneNo")) if state else None
        if e is None:
            return FAIL
        srow = stone_row(e["index"])
        group = levels(srow.get("enchantLevelGroup"))
        top, level = max(group, default=0), e.get("enchant", 0)
        cost = group.get(level, {})
        scroll, row = ratio_row(item, level)
        inv = G.items(state)
        gold = int(cost.get("enchantCostValue", 0)) if cost.get("enchantCostType", GOLD) == GOLD else 0
        if level >= top or row is None or int(inv.get(str(item), 0)) < 1 or G.money(state)["Gold"] < gold:
            return FAIL
        if scroll["scrollCategory"] not in (-1, srow.get("imprintStoneCategory")):
            return FAIL
        inv[str(item)] = int(inv[str(item)]) - 1
        G.spend_gold(state, gold)
        delta = roll(row, min(e.get("bonus", 0), max_bonus()))
        e["enchant"] = max(0, min(top, level + delta))
        e["bonus"] = 0 if delta > 0 else min(max_bonus(), e.get("bonus", 0) + row.get("bonusSuccWeightWhenFailed", 0))
        G.save_state(state)
        return G.ok(EnchantResult=1 if delta > 0 else 0, AccountMoney=G.money(state), ImprintStone=web(e),
                    RemainItemList=G.item_list(state, [item]))


@G.api("imprint/like")
def like(req):
    kind = int(req.get("LikeType") or 0)
    with G._lock:
        state = G.load_state()
        stock(state); G.items(state)   # the login shows the one-time stock unsaved: apply it before the lookup
        if state is None:
            return FAIL
        for no in req.get("ImprintStoneNoList") or []:
            if (e := find(state, no)):
                e["like"] = kind
        for no in req.get("ReleaseIndexList") or []:
            if (e := find(state, no)):
                e["like"] = 0
        G.save_state(state)
    return G.ok(ImprintStoneNoList=req.get("ImprintStoneNoList") or [], ReleaseIndexList=req.get("ReleaseIndexList") or [],
                LikeType=kind)


def picked(state, nos):
    free = equipped(state)
    return [e for no in dict.fromkeys(int(n) for n in nos if n)
            if (e := find(state, no)) and no not in free and not e.get("like")]


def spent(e):
    group = levels(stone_row(e["index"]).get("enchantLevelGroup"))
    return sum(group.get(lv, {}).get("enchantCostValue", 0) for lv in range(e.get("enchant", 0)))


def drop(state, stones):
    gone = {e["no"] for e in stones}
    state["stones"] = [e for e in state.get("stones", []) if e["no"] not in gone]


@G.api("imprint/sell")
def sell(req):
    nos = list(req.get("imprintStoneNoList") or req.get("ImprintStoneNoList") or []) + [req.get("ImprintStoneNo")]
    with G._lock:
        state = G.load_state()
        stock(state); G.items(state)   # the login shows the one-time stock unsaved: apply it before the lookup
        if state is None:
            return FAIL
        stones = picked(state, nos)
        wallet = state.setdefault("money", dict(G.START_MONEY))
        wallet["Gold"] = G.money(state)["Gold"] + sum(3000 + spent(e) // 5 for e in stones)      # ours
        drop(state, stones)
        G.save_state(state)
        return G.ok(AccountMoney=G.money(state))


@G.api("imprint/disassemble")
def disassemble(req):
    listed = req.get("imprintList") or req.get("ImprintList") or []
    with G._lock:
        state = G.load_state()
        stock(state); G.items(state)   # the login shows the one-time stock unsaved: apply it before the lookup
        if state is None:
            return FAIL
        stones = picked(state, [x.get("ImprintStoneNo") for x in listed])
        inv, gained = G.items(state), {}
        for e in stones:      # ours: Common hammers 1 + level, an Uncommon one per 3 levels
            gained["41001"] = gained.get("41001", 0) + 1 + e.get("enchant", 0)
            if e.get("enchant", 0) >= 3:
                gained["41002"] = gained.get("41002", 0) + e["enchant"] // 3
        for k, n in gained.items():
            inv[k] = int(inv.get(k, 0)) + n
        drop(state, stones)
        G.save_state(state)
        return G.ok(AccountMoney=G.money(state), ItemList=G.item_list(state, list(gained)),
                    RewardContentsList=[G.reward(G.ITEM_GOODS, n, int(k)) for k, n in gained.items()],
                    RewardItemList=[{"ItemIndex": int(k), "Qty": n, "Lock": 0, "UpdateTime": G.now_ms()}
                                    for k, n in gained.items()],
                    RewardImprintStoneList=[], PostSendFlag=False)


@G.api("imprint/vestedReset")
def vested_reset(req):
    with G._lock:
        state = G.load_state()
        stock(state); G.items(state)   # the login shows the one-time stock unsaved: apply it before the lookup
        e = find(state, req.get("ImprintStoneNo")) if state else None
        if e is None:
            return FAIL
        paid = None
        if int(req.get("PriceType") or 0) == G.ITEM_GOODS and req.get("PriceIndex"):
            paid = int(req["PriceIndex"])
            G.use_items(state, [{"ItemIndex": paid, "Qty": int(req.get("PriceValue") or 0)}])
        elif int(req.get("PriceType") or 0) == GOLD:
            G.spend_gold(state, int(req.get("PriceValue") or 0))
        G.save_state(state)
        return G.ok(AccountMoney=G.money(state), ImprintStone=web(e),
                    RemainItem=G.item_list(state, [paid])[0] if paid else None)


@G.api("imprint/upgrade")
def upgrade(req):
    return FAIL


@G.api("imprint/polishing")
def polishing(req):
    return FAIL
