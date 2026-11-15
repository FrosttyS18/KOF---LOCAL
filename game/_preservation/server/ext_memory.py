"""character/memoryCombine (UIPage_MemoryCombine; tools/gen_memory.py has the REAL / OURS notes).
Request: memoryCombineList [{baseGrade, baseSynastry, combineQty, ItemList [{ItemIndex, Qty}]}] (the materials picked,
ConfigTable 70001 x combineQty of them). Response: AccountMoney, RewardItemList (what was made, added to the bag by
the client), ItemList (the items' new totals, set by the client). Grade 3 -> 4, 4 -> 5, 5 -> 9 (purple generic)."""
import random

import gameapi as G

NEXT_GRADE = {3: 4, 4: 5, 5: 9}
PER_COMBINE = 5
BONUS_CHANCE = 0.01          # gold -> purple: chance of a fighter memory as well (real: "very low"; the number is ours)


def pick(d, *names, default=0):
    for n in names:
        if n in d:
            return d[n]
    return default


def generic_item(grade, element):
    for r in G.table_rows("ItemTable"):
        if r.get("itemType") == 50 and not r.get("characterIndex") and r.get("frameGrade") == grade \
                and r.get("itemSubType") == element:
            return r["itemIndex"]
    return None


def bonus_memory(element):
    """a purple (frame 90) player fighter's own memory of the element (Prove NPC bosses excluded)"""
    ids = {r["characterIndex"] for r in G.player_character_rows()
           if r.get("frameGrade") == 90 and r.get("synastryType") == element}
    rows = [r["itemIndex"] for r in G.table_rows("ItemTable")
            if r.get("itemType") == 50 and r.get("characterIndex") in ids and not r.get("itemSubType")]
    return random.choice(rows) if rows else None


@G.api("character/memoryCombine")
def memory_combine(req):
    with G._lock:
        state = G.load_state()
        inv = G.items(state)
        made, touched = {}, set()
        for e in pick(req, "memoryCombineList", "MemoryCombineList", default=[]) or []:
            grade, element = int(pick(e, "baseGrade", "BaseGrade")), int(pick(e, "baseSynastry", "BaseSynastry"))
            qty = int(pick(e, "combineQty", "CombineQty", default=1))
            mats = [(str(int(pick(m, "ItemIndex", "itemIndex"))), int(pick(m, "Qty", "qty"))) for m in
                    pick(e, "ItemList", "itemList", default=[]) or []]
            target = generic_item(NEXT_GRADE.get(grade), element) if grade in NEXT_GRADE else None
            if not target or qty < 1 or sum(n for _, n in mats) != PER_COMBINE * qty \
                    or any(n < 1 or int(inv.get(k, 0)) < n for k, n in mats):
                return {"ResultCode": 1, "ResultMessage": "memoryCombine: bad request"}
            for k, n in mats:
                inv[k] = int(inv.get(k, 0)) - n
                touched.add(k)
            made[str(target)] = made.get(str(target), 0) + qty
            if grade == 5:
                for _ in range(qty):
                    b = bonus_memory(element) if random.random() < BONUS_CHANCE else None
                    if b:
                        made[str(b)] = made.get(str(b), 0) + 1
        for k, n in made.items():
            inv[k] = int(inv.get(k, 0)) + n
            touched.add(k)
        G.save_state(state)
        return G.ok(AccountMoney=G.money(state), ItemList=G.item_list(state, sorted(touched)),
                    RewardItemList=[{"ItemIndex": int(k), "Qty": n, "Lock": 0, "UpdateTime": G.now_ms()}
                                    for k, n in made.items()])
