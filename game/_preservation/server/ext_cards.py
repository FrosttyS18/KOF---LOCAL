"""Battle-card growth, the card2/* family (tools/gen_cardgrowth.py has the tables and the REAL / OURS split).

card2/cardLevelUp   BaseCard + MaterialCardList {battleCardNo, battleCardIndex, qty}, UsedGold: the materials' food exp
                    (the client's FoodExp formula) goes to the base card, capped at its max level (growth maxLv + 5 a
                    transcend); materials are used up (stacks by qty), gold is taken. -> levelUpSuccess, accountMoney,
                    battleCard.
card2/cardSkillUp   same request: the skill materials' sLvUpRate x qty is skill EXP (BattleSkillUpTable gauges per level,
                    BattleCard.SkillExp = EXP into the level) -> a special card's SkillLevel (tops out at 5), every
                    option / set passive, or - once transcended - the transcend skill (tops out at transcends +
                    ConfigTable 4036); gold is taken. The materials are cardType 7 rows of subType 2 / 3 / 4 (800011+).
card2/cardAwaken    Transcend: needs the card under its start grade, ConfigTable 4037, the BattleCardAwakeTable step
                    (50,000 gold + materialCount other cards); awaken +1; a random BattleCardAwakeBuffTable effect (by
                    awakeBuffGroupRate; AwakeBuffIndexList + UseTicket restrict it to the picked ones when the step's
                    ticket item is owned). The first effect is kept at once; later ones wait in save "awakePending"
                    (CardAwakenSkill list, also in player/profile) until card2/cardAwakenSkill (changeSkill 1 = take it,
                    0 = keep the old); transcending again re-rolls the pending one.
card2/cardCombine   combineGrade + materialCardList: slotValue cards of that grade -> win (upgradeRate + the grade's
                    bonus weight) a random card of the next grade (weights by type) else a consolation material and
                    +upgradeFailBonus on the weight; more than slotValue cards = "simple combination": no roll, every
                    slotValue cards give enhancement materials. Cards: save "cards"; the stacks have "stack": 1, "qty".
card2/cardSell      sells cards for BattleCardTable cardSellPrice.   card2/cardLock   the like button (Lock).
card2/cardInvenSizeUp  +10 slots a step for 50 rubies (ours).
Cards of "allSpecialCards" (no == index) get a save entry the first time they are grown.
The account gets a one-time grant of enhancement materials (OURS, save grant "cardmats1").
"""
import random

import apidefaults
import gameapi as G

GRANT = "cardmats1"
LUCKY_SPINNER = 7_400_001           # gen_cardgrowth: the transcend pick-up ticket; the TRANSCEND page needs an inventory
G.ONCE_ITEMS.setdefault(str(LUCKY_SPINNER), 10)   # entry for it (even 0), so every account gets one grant (10: ours)
MATERIAL_BASE, MATERIAL_END = 800_000, 800_100
MATERIAL_NO = 60_000_000            # a material stack's BattleCardNo = this + its index (below gacha cards' 70,000,000)
MATERIAL_GRANT = {800_001: 20, 800_002: 10, 800_003: 5, 800_004: 2, 800_005: 1}     # ours
SKILL_GRANT = {800_000 + 10 * k + n: q for k in (1, 2, 3) for n, q in enumerate((20, 10, 5, 2, 1), 1)}   # skill materials (ours)
SKILL_GRANT_KEY = "cardmats2"
SPECIAL_SKILL_MAX = 5               # the client's ActiveSkill.MaxLevel of a special card ("Lv 1 / 5")
CARD_GOODS = 12
SKILL_MAX = 10                      # real: SLV 10 (gen_builds.SKILL_MAX)
INVEN_STEP, INVEN_COST = 10, 50     # ours
SPECIAL, OPTION, SET = 3, 2, 4
SIMPLE_REWARD = {1: 800_001, 2: 800_001, 3: 800_002, 4: 800_003}     # combine grade -> material (ours), two a batch
FAIL_REWARD = 800_002


def pick(d, *names, default=0):
    for n in names:
        for k in (n, n[:1].upper() + n[1:], n[:1].lower() + n[1:]):
            if isinstance(d, dict) and k in d and d[k] is not None:
                return d[k]
    return default


def cfg(index, default=0.0):
    for r in G.table_rows("ConfigTable"):
        if r.get("configIndex") == index:
            try:
                return float(r.get("value1"))
            except (TypeError, ValueError):
                return default
    return default


def card_rows():
    return {r["battleCardIndex"]: r for r in G.table_rows("BattleCardTable")}


def growth_row(card_row, grade):
    gt = card_row.get("growthType", 0)
    for r in G.table_rows("BattleCardGrowthTable"):
        if r["growthType"] == gt and r["grade"] == grade:
            return r
    return {}


def exp_to_level(ltype, level):
    """exp to be at `level` (BattleCardLevelingTable, cumulative; LevelToExp(type, level - 1))"""
    if level <= 1:
        return 0
    rows = {r["battleCardLevel"]: r for r in G.table_rows("BattleCardLevelingTable")}
    r = rows.get(level - 1) or rows[max(rows)]
    return int(r.get(f"exp{ltype}", r.get("exp1", 0)))


def level_of(ltype, exp):
    level = 1
    while exp >= exp_to_level(ltype, level + 1) and level < 200 and exp_to_level(ltype, level + 1) > exp_to_level(ltype, level):
        level += 1
    return level


def max_level(grow, awaken):
    return int(grow.get("maxLv", 30)) + int(cfg(4035, 5)) * awaken


# ---------------------------------------------------------------- the save
def entry_of(state, no, rows=None):
    """the save entry of a card; a special card of "allSpecialCards" gets one the first time it is grown"""
    for e in state.setdefault("cards", []):
        if e["no"] == no:
            return e
    rows = rows or card_rows()
    r = rows.get(no)
    if state.get("allSpecialCards") and r and r.get("cardType") == SPECIAL:
        e = {"no": no, "index": no, "grade": r.get("cardEndGrade", 6), "exp": 0, "skillLevel": 1}
        state["cards"].append(e)
        return e
    return None


def unequip(state, no):
    for c in state.get("characters", []):
        if no in c.get("battleCards", []):
            c["battleCards"] = [0 if x == no else x for x in c["battleCards"]]


def take(state, mat, rows, forbid=()):
    """use up a MaterialCard {battleCardNo, battleCardIndex, qty}: the whole card, or qty of a stack. -> its entry"""
    no, qty = int(pick(mat, "battleCardNo")), max(1, int(pick(mat, "qty", default=1)))
    e = entry_of(state, no, rows)
    if e is None or no in forbid:
        return None
    used = dict(e, used=qty)
    if e.get("stack"):
        used["used"] = min(qty, int(e.get("qty", 1)))
        e["qty"] = int(e.get("qty", 1)) - used["used"]
        if e["qty"] <= 0:
            state["cards"].remove(e)
    else:
        used["used"] = 1
        state["cards"].remove(e)
        unequip(state, no)
    return used


def add_material(state, index, qty):
    no = MATERIAL_NO + index
    for e in state.setdefault("cards", []):
        if e["no"] == no:
            e["qty"] = int(e.get("qty", 0)) + qty
            return e
    e = {"no": no, "index": index, "grade": (index - MATERIAL_BASE) % 10, "exp": 0, "skillLevel": 1, "created": G.now_ms(),
         "stack": 1, "qty": qty}
    state["cards"].append(e)
    return e


def grant_materials(state):
    grant_skill_materials(state)
    granted = state.setdefault("grants", [])
    if GRANT in granted or not any(r["battleCardIndex"] in MATERIAL_GRANT for r in G.table_rows("BattleCardTable")):
        return
    for index, n in MATERIAL_GRANT.items():
        add_material(state, index, n)
    granted.append(GRANT)


def grant_skill_materials(state):
    granted = state.setdefault("grants", [])
    if SKILL_GRANT_KEY in granted or not any(r["battleCardIndex"] in SKILL_GRANT for r in G.table_rows("BattleCardTable")):
        return
    for index, n in SKILL_GRANT.items():
        add_material(state, index, n)
    granted.append(SKILL_GRANT_KEY)


def food_exp(food, target_row, rows):
    """CharacterData.BattleCard.FoodExp for one unit of `food` (a save entry) fed to a card of target_row"""
    r = rows.get(food["index"], {})
    grow = growth_row(r, food.get("grade", r.get("cardStartGrade", 1)))
    bonus = 1.0
    ct = r.get("cardType", 0)
    if ct in (2, 3, 4):
        same = ct == target_row.get("cardType")
    else:
        same = r.get("cardSubType", 0) in (99, target_row.get("cardType"))
    if same:
        bonus = cfg(3002, 100.0) * 0.01
    own = 0
    level = level_of(grow.get("levelingType", 1), int(food.get("exp", 0)))
    if level > 1:
        own = exp_to_level(grow.get("levelingType", 1), level)
    gain = round(float(grow.get("gradeExp", 0)) * 100) * int(r.get("gainExp", 0)) * bonus
    return int(round((gain + own * round(cfg(4022, 0.0) * 100)) * 0.01))


def load():
    """the save with the one-time material grant applied (it is saved by the handler's own save_state)"""
    state = G.load_state()
    if state is not None:
        grant_materials(state)
    return state


def charge(state, gold):
    gold = max(0, int(gold or 0))
    if G.money(state)["Gold"] < gold:
        return False
    G.spend_gold(state, gold)
    return True


def card_dict(state, no):
    for c in G.battle_cards(state):
        if c["BattleCardNo"] == no:
            return c
    return apidefaults.default("BattleCard", BattleCardNo=no)


def fail(msg):
    return {"ResultCode": 1, "ResultMessage": msg}


def no_account():
    return fail("no account")


# ---------------------------------------------------------------- level up / skill up
@G.api("card2/cardLevelUp")
def card_level_up(req):
    with G._lock:
        state = load()
        if state is None:
            return no_account()
        rows = card_rows()
        base = int(pick(pick(req, "BaseCard", default={}), "battleCardNo"))
        e = entry_of(state, base, rows)
        if e is None:
            return fail("no such card")
        r = rows[e["index"]]
        grow = growth_row(r, e.get("grade", r.get("cardStartGrade", 5)))
        ltype = grow.get("levelingType", 1)
        gold = int(pick(req, "UsedGold"))
        if G.money(state)["Gold"] < gold:
            return fail("not enough gold")
        gained = 0
        for m in pick(req, "MaterialCardList", default=[]):
            used = take(state, m, rows, forbid=(base,))
            if used:
                gained += food_exp(used, r, rows) * used["used"]
        top = exp_to_level(ltype, max_level(grow, int(e.get("awaken", 0))))
        e["exp"] = min(int(e.get("exp", 0)) + gained, max(top, int(e.get("exp", 0))))
        G.spend_gold(state, gold)
        G.save_state(state)
        card = card_dict(state, base)
        money = G.money(state)
    # CardLevelUpResponse: the reply starts defaulted with these exact names (gameapi.handle) and the client takes the
    # first match, so lowercase twins were ignored (Lv 1 -> 1 on the result screen, 2026-11-09)
    return G.ok(LevelUpSuccess=1, AccountMoney=money, BattleCard=card)


def skill_gauge(r, e, level):
    """the skill EXP one level takes (BattleSkillUpTable row of the card's start grade; the column of its type, or the
    transcend column once transcended); 0 = no row (the top)"""
    row = next((u for u in G.table_rows("BattleSkillUpTable")
                if u["skillLevel"] == level and u["cardGrade"] == r.get("cardStartGrade", 1)), None)
    if row is None:
        return 0
    if e.get("awakeBuff"):
        return int(row.get("awakenSLvUpGauge", 0))
    col = {SPECIAL: "specialSLvUpGauge", SET: "setSLvUpGauge"}.get(r.get("cardType"), "sLvUpGauge")
    return int(row.get(col, 0))


def add_skill_exp(r, e, level, top, gained):
    """CharacterData.BattleCard.UpdateSkillLevel: -> (new level, EXP left in it); at the top the EXP is dropped"""
    exp = int(e.get("skillExp", 0)) + gained
    while level < top:
        gauge = skill_gauge(r, e, level)
        if gauge <= 0 or exp < gauge:
            break
        exp -= gauge
        level += 1
    return level, (0 if level >= top else exp)


@G.api("card2/cardSkillUp")
def card_skill_up(req):
    with G._lock:
        state = load()
        if state is None:
            return no_account()
        rows = card_rows()
        base = int(pick(pick(req, "BaseCard", default={}), "battleCardNo"))
        e = entry_of(state, base, rows)
        if e is None:
            return fail("no such card")
        r = rows[e["index"]]
        gold = int(pick(req, "UsedGold"))
        if G.money(state)["Gold"] < gold:
            return fail("not enough gold")
        gained = 0
        for m in pick(req, "MaterialCardList", default=[]):
            used = take(state, m, rows, forbid=(base,))
            if used:       # the material's proto sLvUpRate (skill EXP) per unit
                gained += int(rows.get(used["index"], {}).get("sLvUpRate", 0)) * used["used"]
        if e.get("awakeBuff"):                      # a transcended card trains its transcend skill
            top = int(e.get("awaken", 0)) + int(cfg(4036, 1))
            e["awakeBuffLevel"], e["skillExp"] = add_skill_exp(r, e, int(e.get("awakeBuffLevel", 1)), top, gained)
        elif r.get("cardType") == SPECIAL:
            e["skillLevel"], e["skillExp"] = add_skill_exp(r, e, int(e.get("skillLevel", 1)), SPECIAL_SKILL_MAX, gained)
        else:
            tops = {b["buffIndex"]: b.get("buffMaxLevel", SKILL_MAX) for b in G.table_rows("BuffTable")}
            passives = e.get("passives") or G.card_passives(r)
            top = max([int(tops.get(b, SKILL_MAX)) for b, _ in passives] or [SKILL_MAX])
            level, e["skillExp"] = add_skill_exp(r, e, min(lv for _, lv in passives) if passives else 1, top, gained)
            e["passives"] = [[b, min(level, int(tops.get(b, SKILL_MAX)))] for b, _ in passives]
        G.spend_gold(state, gold)
        G.save_state(state)
        card = card_dict(state, base)
        money = G.money(state)
    return G.ok(levelUpSuccess=1, accountMoney=money, battleCard=card)


# ---------------------------------------------------------------- transcend
def pending_list(state):
    rows = {e["no"]: e for e in state.get("cards", [])}
    return [apidefaults.default("CardAwakenSkill", battleCardNo=int(no), battleCardIndex=rows[int(no)]["index"],
                                awakeBuffIndex=b)
            for no, b in state.get("awakePending", {}).items() if int(no) in rows]


def roll_buff(row, wanted, ticket):
    pool = [b for b in G.table_rows("BattleCardAwakeBuffTable") if b.get("awakeBuffGroup") == row.get("awakeBuffGroup1")]
    if ticket and wanted:
        picked = [b for b in pool if b["awakeBuffIndex"] in wanted]
        pool = picked or pool
    weights = [max(1, b.get("awakeBuffGroupRate", 1)) for b in pool]
    return random.choices(pool, weights)[0]["awakeBuffIndex"] if pool else 0


@G.api("card2/cardAwaken")
def card_awaken(req):
    with G._lock:
        state = load()
        if state is None:
            return no_account()
        rows = card_rows()
        base = int(pick(pick(req, "BaseCard", default={}), "battleCardNo"))
        e = entry_of(state, base, rows)
        if e is None:
            return fail("no such card")
        r = rows[e["index"]]
        awaken = int(e.get("awaken", 0))
        if int(cfg(4037, 1)) != 1 or not r.get("awakenAble", 1) or awaken >= r.get("cardStartGrade", 5):
            return fail("cannot transcend")
        row = next((a for a in G.table_rows("BattleCardAwakeTable")
                    if a["battleCardStartGrade"] == r.get("cardStartGrade") and a["battleCardType"] == r.get("cardType")
                    and a["awakeStep"] == awaken + 1), None)
        if row is None:
            return fail("no transcend step")
        mats = [m for m in pick(req, "MaterialCardList", default=[]) if int(pick(m, "battleCardNo")) != base]
        if sum(max(1, int(pick(m, "qty", default=1))) for m in mats) < row.get("materialCount", 1):
            return fail("not enough materials")
        if not charge(state, row.get("goodsValue", 0) if row.get("goodsType", 1) == 1 else 0):
            return fail("not enough gold")
        for m in mats:
            take(state, m, rows, forbid=(base,))
        ticket_item = row.get("pickUpTicketItemIndex", 0)
        inv, remain = G.items(state), None
        use_ticket = bool(pick(req, "UseTicket", default=False)) and ticket_item and int(inv.get(str(ticket_item), 0)) > 0
        if use_ticket:
            inv[str(ticket_item)] = int(inv[str(ticket_item)]) - 1
            remain = G.item_list(state, [ticket_item])[0]
        buff = roll_buff(row, set(int(x) for x in pick(req, "AwakeBuffIndexList", default=[])), use_ticket)
        e["awaken"] = awaken + 1
        if e.get("awakeBuff"):
            state.setdefault("awakePending", {})[str(base)] = buff
        else:
            e["awakeBuff"], e["awakeBuffLevel"] = buff, 1
        G.save_state(state)
        out = dict(accountMoney=G.money(state), battleCard=card_dict(state, base), awakenSkillList=pending_list(state))
        if remain:
            out["remainItem"] = remain
    return G.ok(**out)


@G.api("card2/cardAwakenSkill")
def card_awaken_skill(req):
    with G._lock:
        state = load()
        if state is None:
            return no_account()
        base = int(pick(pick(req, "BaseCard", default={}), "battleCardNo"))
        e = entry_of(state, base)
        if e is None:
            return fail("no such card")
        new = state.get("awakePending", {}).pop(str(base), 0)
        if new and int(pick(req, "changeSkill")) == 1:
            e["awakeBuff"] = new
            e["awakeBuffLevel"] = min(max(1, int(e.get("awakeBuffLevel", 1))),
                                      int(e.get("awaken", 0)) + int(cfg(4036, 1)))
        G.save_state(state)
        out = dict(battleCard=card_dict(state, base), awakenSkillList=pending_list(state))
    return G.ok(**out)


# ---------------------------------------------------------------- combine
def combine_row(grade):
    return next((r for r in G.table_rows("BattleCardCombineTable") if r["cardGrade"] == grade), None)


def combine_bonus(state):
    return state.setdefault("combineBonus", {})


def combine_result(state, row, rows):
    """a random card of the next grade by the row's type weights (falls back to any card of that grade)"""
    grade = row["cardGrade"] + 1
    pool = {}
    for r in rows.values():
        if r.get("cardStartGrade") == grade and r.get("cardType") in (SPECIAL, OPTION, SET):
            pool.setdefault(r["cardType"], []).append(r)
    weights = {OPTION: row.get("cardTypeOption", 0), SPECIAL: row.get("cardTypeSpecial", 0), SET: row.get("cardTypeSet", 0)}
    types = [t for t in pool if weights[t] > 0] or list(pool)
    if not types:
        return None
    t = random.choices(types, [max(1, weights[t]) for t in types])[0]
    return random.choice(pool[t])


@G.api("card2/cardCombine")
def card_combine(req):
    with G._lock:
        state = load()
        if state is None:
            return no_account()
        rows = card_rows()
        grade = int(pick(req, "combineGrade"))
        row = combine_row(grade)
        mats = pick(req, "materialCardList", default=[])
        count = sum(max(1, int(pick(m, "qty", default=1))) for m in mats)
        if row is None or count < row["slotValue"]:
            return fail("not enough cards")
        batches = count // row["slotValue"]
        simple = count > row["slotValue"]
        if not charge(state, row["useGold"] * batches):
            return fail("not enough gold")
        for m in mats:
            take(state, m, rows)
        bonus = combine_bonus(state)
        won, reward_cards, rewards = 0, [], {}
        if simple:
            index = SIMPLE_REWARD.get(grade, 800_001)
            rewards[index] = 2 * batches
        else:
            chance = min(10_000, row["upgradeRate"] + int(bonus.get(str(grade), 0)))
            card = combine_result(state, row, rows) if random.randrange(10_000) < chance else None
            if card is not None:
                won = 1
                bonus[str(grade)] = row.get("upgradeSuccessBonus", 0)
                made = G.gacha_card(state, card["battleCardIndex"])
                reward_cards.append(made)
                rewards[card["battleCardIndex"]] = 1
            else:
                bonus[str(grade)] = int(bonus.get(str(grade), 0)) + row.get("upgradeFailBonus", 0)
                rewards[FAIL_REWARD] = 1
        stacks = []
        for index, n in rewards.items():
            if MATERIAL_BASE <= index < MATERIAL_END:
                stacks.append(add_material(state, index, n)["no"])
        G.save_state(state)
        all_cards = {c["BattleCardNo"]: c for c in G.battle_cards(state)}
        reward_cards += [all_cards[n] for n in stacks if n in all_cards]
        combine_rewards = [G.reward(CARD_GOODS, n, index) for index, n in rewards.items()]
        info = apidefaults.default("BattleCardCombineInfo", grade=grade, bonusWeight=int(bonus.get(str(grade), 0)))
        money = G.money(state)
    return G.ok(levelUpSuccess=won, accountMoney=money, rewardBattleCardList=reward_cards,
                combineRewardList=combine_rewards, battleCardCombineInfo=info, postSendFlag=False)


# ---------------------------------------------------------------- sell, lock, slots
@G.api("card2/cardSell")
def card_sell(req):
    with G._lock:
        state = load()
        if state is None:
            return no_account()
        rows = card_rows()
        total = 0
        for m in pick(req, "BattleCardList", default=[]):
            used = take(state, m, rows)
            if used:
                total += int(rows.get(used["index"], {}).get("cardSellPrice", 0)) * used["used"]
        state.setdefault("money", {})["Gold"] = G.money(state)["Gold"] + total
        G.save_state(state)
        money = G.money(state)
    return G.ok(AccountMoney=money)


@G.api("card2/cardLock")
def card_lock(req):
    like = int(pick(req, "likeType"))
    lock = [int(x) for x in pick(req, "battleCardNoList", default=[])]
    free = [int(x) for x in pick(req, "releaseIndexList", default=[])]
    with G._lock:
        state = load()
        if state is None:
            return no_account()
        rows = card_rows()
        for no in lock:
            e = entry_of(state, no, rows)
            if e is not None:
                e["lock"] = like
        for no in free:
            e = entry_of(state, no, rows)
            if e is not None:
                e["lock"] = 0
        G.save_state(state)
    return G.ok(releaseIndexList=free, battleCardNoList=lock, likeType=like)


@G.api("card2/cardInvenSizeUp")
def card_inven_size_up(req):
    steps = max(1, int(pick(req, "SizeUpCount", default=1)))
    with G._lock:
        state = load()
        if state is None:
            return no_account()
        wallet = G.money(state)
        cost = steps * INVEN_COST
        if wallet.get("Cash", 0) < cost:
            return fail("not enough rubies")
        state.setdefault("money", {})["Cash"] = wallet["Cash"] - cost
        state["cardSlotsBonus"] = int(state.get("cardSlotsBonus", 0)) + steps * INVEN_STEP
        G.save_state(state)
        size = G.card_inventory(G.battle_cards(state))
        money = G.money(state)
    return G.ok(CurMaxSize=size["MaxSize"], AccountMoney=money)


# ---------------------------------------------------------------- wiring into the shared builders
_battle_cards, _card_inventory = G.battle_cards, G.card_inventory


def battle_cards(state):
    """gameapi.battle_cards + the enhancement material stacks (StackFlag / Qty), the like lock"""
    grant_materials(state)
    out = _battle_cards(state)
    saved = {e["no"]: e for e in state.get("cards", [])}
    for c in out:
        e = saved.get(c["BattleCardNo"])
        if e is None:
            continue
        if e.get("stack"):
            c["StackFlag"], c["Qty"] = 1, int(e.get("qty", 1))
        c["SkillExp"] = int(e.get("skillExp", 0))
        c["Lock"] = int(e.get("lock", 0))
        c["LikeFlag"] = bool(e.get("lock"))
    return out


def card_inventory(cards):
    size = _card_inventory(cards)
    state = G.load_state()
    if state and state.get("cardSlotsBonus"):
        size["MaxSize"] = size["MaxSize"] + int(state["cardSlotsBonus"])
    return size


G.battle_cards, G.card_inventory = battle_cards, card_inventory

_profile = G.APIS["player/profile"]


def player_profile(req):
    """player/profile + the pending transcend effects and the combine bonus weights"""
    out = _profile(req)
    if isinstance(out, dict) and out.get("ResultCode") == 0:
        state = G.load_state()
        if state:
            out["awakenSkillList"] = pending_list(state)
            out["BattleCardCombineInfoList"] = [
                apidefaults.default("BattleCardCombineInfo", grade=int(g), bonusWeight=int(w))
                for g, w in combine_bonus(state).items()]
    return out


G.APIS["player/profile"] = player_profile
