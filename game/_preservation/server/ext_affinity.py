"""Fighter Affinity gifts (tools/gen_affinity.py has the tables and the REAL / OURS split).

affection/giveGift   Character {CharacterIndex, ...}, ItemList [{ItemIndex, Qty}] (Qty = how many are given): every food
                     (ItemGroupType 5 with an AffectionPresentTable row) is taken from the inventory and adds its points to
                     the fighter's save "affection" (the same formula as the client's GetAffectionExpByCharacterGroup: the
                     base value, + the extra for a favourite, the dislike value for a disliked food), capped at the total of
                     level 15. Every level reached for the first time pays its Reward rows (AffectionBonusGroupTable
                     type 2 -> RewardGroupTable: rubies, soul dust); fighter["affectionPaid"] is the highest level paid, so
                     levels earned from story wins are paid by the next gift. The first gift of a day also pays that day's
                     friendship points (AffectionDailyRewardTable: the highest tier <= the sum of all fighters' levels).
                     Stat rows (type 1) need no server part: the client adds them from the table.
save.json fighter "affection" = total points (story wins add +2 / +1 / +1 there too; saves from before the real level table
read as Lv 0 with that many points), "affectionPaid" = highest level paid. A one-time stock of 10 of every food goes to the
account (ours).
"""
import gameapi as G

GROUP_PRESENT = 5
GOODS_RUBY, GOODS_FRIEND, GOODS_SOUL_DUST = 2, 5, 33
FAIL = {"ResultCode": 1, "ResultMessage": "affinity gift refused"}
STOCK = 10                  # of every food, once (ours)
FRIEND_CAP = 10_000         # the guides: friendship points stop at 10,000


def rows(table):
    return G.table_rows(table)


def foods():
    return {r["itemIndex"]: r for r in rows("AffectionPresentTable")
            if any(i["itemIndex"] == r["itemIndex"] and i.get("itemGroupType") == GROUP_PRESENT
                   for i in rows("ItemTable"))}


for _r in rows("AffectionPresentTable"):
    G.ONCE_ITEMS.setdefault(str(_r["itemIndex"]), STOCK)


def levels():
    """-> [(level, expAccumulate)] rows in order (the client's GetAffectionLevel walks them the same way)"""
    return [(r["affectionLevel"], r["expAccumulate"]) for r in sorted(rows("AffectionLevelTable"), key=lambda r: r["affectionLevelIndex"])]


def level_of(total):
    table = levels()
    for level, accumulate in table:
        if total < accumulate:
            return level
    return len(table)                       # MaxLevel = the row count


def max_total():
    table = levels()
    return table[-1][1] if table else 0


def ids(text):
    return {int(x) for x in str(text or "").split(",") if x.strip().lstrip("-").isdigit()}


def group_of(index):
    return next((r.get("characterGroupIndex", 0) for r in rows("CharacterTable") if r["characterIndex"] == index), 0)


def points(row, group):
    """AffectionPresentTable.GetAffectionExpByCharacterGroup"""
    extra = ids(row.get("extraTargetFighter"))
    if -1 in extra or group in extra:
        return row["addAffectionValue"] + row["extraAffectionValueMax"]
    if group in ids(row.get("dislikeFighter")):
        return row["dislikeAffectionValueMax"]
    return row["addAffectionValue"]


def pay_level(state, level):
    """pay the Reward rows of one level -> [RewardContents]"""
    wallet = G.regen_ap(state)
    out = []
    for b in rows("AffectionBonusGroupTable"):
        if b["needAffectionLevel"] != level or b["affectionBonusType"] != 2:
            continue
        for r in rows("RewardGroupTable"):
            if r["rewardGroup"] != b["rewardGroup"]:
                continue
            key = {GOODS_RUBY: "Cash", GOODS_SOUL_DUST: "SoulDust", G.GOLD_GOODS: "Gold"}.get(r["rewardType"])
            if key:
                wallet[key] = int(wallet.get(key, 0)) + r["contentsCountMin"]
                out.append(G.reward(r["rewardType"], r["contentsCountMin"]))
    return out


def daily_points(state):
    """the first gift of a day: friendship points by the sum of all fighters' levels (ours) -> points paid"""
    day = G.daily(state)
    if day.get("affinityPaid"):
        return 0
    total = sum(level_of(c.get("affection", 0)) for c in state.get("characters", []))
    tiers = [r for r in rows("AffectionDailyRewardTable") if r["needSumAffectionLevel"] <= total]
    day["affinityPaid"] = True
    if not tiers:
        return 0
    value = max(tiers, key=lambda r: r["needSumAffectionLevel"])["rewardGoodsValue"]
    wallet = G.regen_ap(state)
    wallet["FriendPoint"] = min(FRIEND_CAP, int(wallet.get("FriendPoint", 0)) + value)
    return value


@G.api("affection/giveGift")
def give_gift(req):
    index = int((req.get("Character") or {}).get("CharacterIndex") or 0)
    asked = [(int(i.get("ItemIndex") or 0), int(i.get("Qty") or 0)) for i in req.get("ItemList") or []]
    with G._lock:
        state = G.load_state()
        if state is None or not index:
            return FAIL
        food, inv = foods(), G.items(state)
        fighter = G.character_state(state, index)
        group = group_of(index)
        total, used = fighter.get("affection", 0), []
        cap = max_total()
        for item, qty in asked:
            row = food.get(item)
            have = int(inv.get(str(item), 0))
            if row is None or qty <= 0 or have <= 0 or total >= cap:
                continue
            qty = min(qty, have)
            inv[str(item)] = have - qty
            total = min(cap, total + qty * points(row, group))
            used.append(item)
        if not used:
            return FAIL
        fighter["affection"] = total
        new_level = level_of(total)
        contents = []
        for level in range(fighter.get("affectionPaid", 0) + 1, new_level + 1):
            contents += pay_level(state, level)
        fighter["affectionPaid"] = max(fighter.get("affectionPaid", 0), new_level)
        daily_points(state)
        G.save_state(state)
        return G.ok(Character=G.simple(fighter, "CharacterSimple", G.start_grades()), ItemList=G.item_list(state, used),
                    AccountMoney=G.money(state), RewardBattleCardList=[], RewardCharacterList=[], RewardItemList=[],
                    PostSendFlag=False)
