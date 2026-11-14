"""Plugins - the client's equipment/* system (tools/gen_plugins.py has the tables and the REAL / OURS split).

save.json "plugins": [{"no", "index" (EquipmentTable), "grade", "level", "opt" (16 ints: 7 x (optionIndex, value) extras +
the unique pair), "like", "count" (option changes), "chosen" (the one changed option, 0 = none yet), "pending" (an option
change awaiting equipment/changeOptionFixed), "created"}]; fighter "parts": [5 plugin numbers]. OptionInfo on the wire is
the 16 numbers joined by "|" (EquipmentUtils.ParseEquipmentOption).

equipment/list, openBox, sell, disassemble, like, changeOption + changeOptionFixed (the client asks for a new line, shows
it next to the old one, then confirms or keeps), inventorySizeUp, move / delete of temp plugins (no temp storage offline);
character/equipmentEquipUpdate (equip, unequip, move from another fighter). The login (player/profile) carries the list.
A one-time stock of plugins goes to the account (ours); equipmentDungeon/* (Plugin Plant) is not handled.
"""
import random

import gameapi as G

GOLD = 1
FAIL = {"ResultCode": 1, "ResultMessage": "plugin action refused"}
FIRST_NO = 300000
MAX_SIZE = 300
STOCK_GRADES = ((5, 90), (4, 70), (3, 50))          # per colour and part (ours)


def rows(table):
    return G.table_rows(table)


def equipment_row(index):
    return next((r for r in rows("EquipmentTable") if r["equipmentIndex"] == index), None)


def grade_row(grade):
    return next((r for r in rows("EquipmentGradeTable") if r["grade"] == grade), {})


def preset(grade, part, level):
    best = None
    for r in rows("EquipmentPresetTable"):
        if r["grade"] == grade and r["partsType"] == part and r["equipmentLv"] <= level \
                and (best is None or r["equipmentLv"] > best["equipmentLv"]):
            best = r
    return best


def pick(options):
    total = sum(o.get("prob", 0) for o in options)
    r = random.uniform(0, total or 1)
    for o in options:
        r -= o.get("prob", 0)
        if r <= 0:
            return o
    return options[-1] if options else None


def roll_value(o):
    return random.randint(o["optionLvMin"], max(o["optionLvMin"], o["optionLvMax"]))


def roll_options(grade, part, level):
    pre = preset(grade, part, level)
    opt = [0] * 16
    if not pre:
        return opt
    used = set()
    for slot in range(random.randint(pre["extraOptionCountMin"], pre["extraOptionCountMax"])):
        group = pre.get(f"extraOptionGroup0{slot + 1}")
        pool = [o for o in rows("EquipmentOptionTable") if o["equipmentOptionGroup"] == group
                and o["equipmentOptionIndex"] not in used and o.get("prob")]
        o = pick(pool)
        if o:
            used.add(o["equipmentOptionIndex"])
            opt[slot * 2], opt[slot * 2 + 1] = o["equipmentOptionIndex"], roll_value(o)
    return opt


def new_plugin(state, index, grade, level):
    row = equipment_row(index)
    plugins = state.setdefault("plugins", [])
    no = max([p["no"] for p in plugins] + [FIRST_NO - 1]) + 1
    p = {"no": no, "index": index, "grade": grade, "level": level, "opt": roll_options(grade, row["partsType"], level),
         "like": 0, "count": 0, "chosen": 0, "created": G.now_ms()}
    plugins.append(p)
    return p


# a one-time stock of plugin modules for option change (ours; the account had none, 2026-11-09)
for _k, _n in (("7300001", 60), ("7300002", 30), ("7300003", 10)):
    G.ONCE_ITEMS.setdefault(_k, _n)


def stock(state):
    granted = state.setdefault("grants", [])
    if "plugins_v1" not in granted:
        for row in rows("EquipmentTable"):
            for grade, level in STOCK_GRADES:
                new_plugin(state, row["equipmentIndex"], grade, level)
        granted.append("plugins_v1")


def find(state, no):
    return next((p for p in state.get("plugins", []) if p["no"] == int(no or 0)), None)


def equipped_by(state):
    return {no: c["index"] for c in state.get("characters", []) for no in c.get("parts", []) if no}


def web(state, p, worn=None):
    worn = equipped_by(state) if worn is None else worn
    part = (equipment_row(p["index"]) or {}).get("partsType", 0)
    return G.apidefaults.default(
        "EquipmentWEBData", EquipmentNo=p["no"], EquipmentIndex=p["index"], BeforeGrade=p["grade"], AfterGrade=p["grade"],
        BeforeLevel=p["level"], AfterLevel=p["level"], PartsType=part, Status=1 if p["no"] in worn else 0,
        OptionInfo="|".join(str(v) for v in p["opt"]), AspectFlag=0, ChangeOptionValue=p.get("chosen", 0),
        ChangeOptionCount=p.get("count", 0), LikeFlag=p.get("like", 0), ExpireTime=0)


def listing(state):
    stock(state)
    worn = equipped_by(state)
    return [web(state, p, worn) for p in state.get("plugins", [])]


def size_info(state):
    return G.apidefaults.default("EquipmentInvenSize", maxSize=max(MAX_SIZE, len(state.get("plugins", [])) + 50))


# the login: the plugin list, the size, and each fighter's five plugin numbers
_profile = G.APIS["player/profile"]


def profile(req):
    out = _profile(req)
    with G._lock:
        state = G.load_state()
        if state is not None and out.get("ResultCode") == 0:
            had = "plugins_v1" in state.get("grants", [])
            out["EquipmentList"] = listing(state)
            out["TempEquipmentList"] = []
            out["EquipmentInvenSize"] = size_info(state)
            if not had:
                G.save_state(state)
    return out


G.APIS["player/profile"] = profile
_character = G.character


def character(c, start=None):
    out = _character(c, start)
    parts = list(c.get("parts", [])) + [0] * 5
    for i in range(5):
        out[f"parts{i + 1}no"] = int(parts[i])
        out[f"Parts{i + 1}No"] = int(parts[i])
    return out


G.character = character


def locked_ids(state):
    return set(equipped_by(state))


def with_state(fn):
    with G._lock:
        state = G.load_state()
        if state is None:
            return FAIL
        stock(state)
        G.items(state)
        return fn(state)


@G.api("equipment/list")
def list_(req):
    def run(state):
        G.save_state(state)
        return G.ok(EquipmentList=listing(state), TempEquipmentList=[])
    return with_state(run)


@G.api("equipment/inventorySizeUp")
def size_up(req):
    return with_state(lambda state: G.ok(CurMaxSize=size_info(state)["maxSize"], AccountMoney=G.money(state)))


@G.api("equipment/moveTempInventory")
def move_temp(req):
    return FAIL


@G.api("equipment/bulkMoveTempInventory")
def bulk_move(req):
    return G.ok(equipmentList=[])


@G.api("equipment/deleteTempEquipment")
def delete_temp(req):
    return G.ok()


@G.api("equipment/bulkDeleteTempEquipment")
def bulk_delete(req):
    return G.ok(equipmentList=[])


@G.api("equipment/like")
def like(req):
    kind = int(req.get("LikeType") or 0)

    def run(state):
        for no in req.get("EquipmentNoList") or []:
            if (p := find(state, no)):
                p["like"] = kind
        for no in req.get("ReleaseIndexList") or []:
            if (p := find(state, no)):
                p["like"] = 0
        G.save_state(state)
        return G.ok(EquipmentNoList=req.get("EquipmentNoList") or [], ReleaseIndexList=req.get("ReleaseIndexList") or [],
                    LikeType=kind)
    return with_state(run)


@G.api("equipment/sell")
def sell(req):
    def run(state):
        p = find(state, req.get("EquipmentNo"))
        if p is None or p["no"] in locked_ids(state) or p.get("like"):
            return FAIL
        wallet = state.setdefault("money", dict(G.START_MONEY))
        wallet["Gold"] = G.money(state)["Gold"] + int(grade_row(p["grade"]).get("sellEarnGoodsValue", 0))
        state["plugins"].remove(p)
        G.save_state(state)
        return G.ok(AccountMoney=G.money(state))
    return with_state(run)


@G.api("equipment/disassemble")
def disassemble(req):
    def run(state):
        free = locked_ids(state)
        picked = []
        for e in req.get("equipmentInfoList") or []:
            p = find(state, e.get("EquipmentNo"))
            if p and p["no"] not in free and not p.get("like") and p not in picked:
                picked.append(p)
        gold = sum(int(grade_row(p["grade"]).get("disassembleCostValue", 0)) for p in picked)
        if G.money(state)["Gold"] < gold:
            return FAIL
        G.spend_gold(state, gold)
        gained, contents = {}, []
        for p in picked:
            c, ids, _ = G.give_rewards(state, grade_row(p["grade"]).get("disassembleRewardGroup"))
            for r in c:
                gained[r["ContentsIndex"]] = gained.get(r["ContentsIndex"], 0) + r["ContentsCount"]
            state["plugins"].remove(p)
        contents = [G.reward(G.ITEM_GOODS, n, k) for k, n in gained.items()]
        G.save_state(state)
        return G.ok(AccountMoney=G.money(state), ItemList=G.item_list(state, list(gained)),
                    RewardContentsList=contents,
                    RewardItemList=[{"ItemIndex": k, "Qty": n, "Lock": 0, "UpdateTime": G.now_ms()}
                                    for k, n in gained.items()],
                    RewardImprintStoneList=[], PostSendFlag=False)
    return with_state(run)


@G.api("equipment/openBox")
def open_box(req):
    item, qty = int(req.get("itemIndex") or 0), max(1, int(req.get("itemQty") or 1))

    def run(state):
        inv = G.items(state)
        row = next((r for r in rows("ItemTable") if r["itemIndex"] == item and r.get("itemType") == 300), None)
        if not row or int(inv.get(str(item), 0)) < qty:
            return FAIL
        boxes = [b for b in rows("EquipmentBoxRewardTable") if b["equipmentBoxRewardGroup"] == row.get("applyTargetIndex")]
        got = []
        inv[str(item)] = int(inv[str(item)]) - qty
        for _ in range(qty):
            b = pick([dict(x, prob=x["rate"]) for x in boxes])
            rw = next((r for r in rows("EquipmentRewardTable") if b and r["equipmentRewardIndex"] == b["equipmentRewardIndex"]), None)
            if not rw:
                continue
            grade = pick([{"g": g, "prob": rw[f"grade0{g}Prob"]} for g in range(1, 6)])["g"]
            eq = pick([dict(x) for x in rows("EquipmentRewardGroupTable")
                       if x["equipmentRewardGroup"] == rw["equipmentRewardGroup"]])
            level = max(1, random.randint(rw["equipmentLvMin"], rw["equipmentLvMax"]))
            got.append(new_plugin(state, eq["equipmentIndex"], grade, level))
        G.save_state(state)
        worn = equipped_by(state)
        return G.ok(Item=G.item_list(state, [item])[0], EquipmentList=[web(state, p, worn) for p in got], TempEquipmentList=[])
    return with_state(run)


def synastry(index):
    return next((r.get("synastryType") for r in rows("CharacterTable") if r["characterIndex"] == index), 0)


@G.api("character/equipmentEquipUpdate")
def equip_update(req):
    index, part = int(req.get("characterIndex") or 0), int(req.get("partsType") or 0)
    no = int(req.get("equipmentNo") or 0)

    def run(state):
        if not 1 <= part <= 5:
            return FAIL
        p = find(state, no) if no else None
        if no and (p is None or (equipment_row(p["index"]) or {}).get("partsType") != part
                   or equipment_row(p["index"]).get("usableSynastryType") not in (0, synastry(index))):
            return FAIL
        c = G.character_state(state, index)
        touched, chars = set(), {index: c}
        slots = list(c.get("parts", [])) + [0] * 5
        if slots[part - 1]:
            touched.add(slots[part - 1])
        if no:
            for o in state["characters"]:           # a plugin moved from another fighter leaves its slot
                if o is not c and no in o.get("parts", []):
                    o["parts"] = [0 if n == no else n for n in o["parts"]]
                    chars[o["index"]] = o
            touched.add(no)
        slots[part - 1] = no
        c["parts"] = slots[:5]
        G.save_state(state)
        worn = equipped_by(state)
        return G.ok(EquipmentList=[web(state, q, worn) for n in touched if (q := find(state, n))],
                    characterEquipmentList=[G.apidefaults.default(
                        "CharacterEquipmentWEBData", characterIndex=i,
                        **{f"parts{k}No": int((ch.get("parts", []) + [0] * 5)[k - 1]) for k in range(1, 6)},
                        power=int(req.get("characterPower") or 0)) for i, ch in chars.items()])
    return with_state(run)


# ---- option change: the cost is the table's gold of (rarity, changes so far) x level + the rarity's modules
def change_cost(p):
    count = p.get("count", 0)
    rows_ = rows("EquipmentOptionCostTable")
    row = next((r for r in rows_ if r["equipmentChangeOptionCount"] == count),
               max(rows_, key=lambda r: r["equipmentChangeOptionCount"], default={}))
    gold = int(row.get(f"equipmentChangeOptionGold{p['grade']}", 0)) * p["level"]
    mats = next((r for r in rows("EquipmentCostTable") if r["equipmentCostIndex"] == grade_row(p["grade"]).get(
        "optionChangeCostIndex")), {})
    return gold, [(mats.get(f"materialItem0{k}Index"), mats.get(f"materialItem0{k}Count", 0)) for k in (1, 2, 3)
                  if mats.get(f"materialItem0{k}Count")]


@G.api("equipment/changeOption")
def change_option(req):
    chosen = int(req.get("OptionIndex") or 0)

    def run(state):
        p = find(state, req.get("EquipmentNo"))
        if p is None or chosen not in p["opt"][0:14:2] or chosen == 0:
            return FAIL
        if p.get("chosen") and p["chosen"] != chosen:
            return FAIL                                     # only one line of a plugin can be changed
        slot = p["opt"][0:14:2].index(chosen)
        group = next(o["equipmentOptionGroup"] for o in rows("EquipmentOptionTable") if o["equipmentOptionIndex"] == chosen)
        taken = set(p["opt"][0:14:2])
        pool = [o for o in rows("EquipmentOptionTable") if o["equipmentOptionGroup"] == group and o.get("prob")
                and o["equipmentOptionIndex"] not in taken]
        new = pick(pool)
        gold, mats = change_cost(p)
        inv = G.items(state)
        if new is None or G.money(state)["Gold"] < gold or any(int(inv.get(str(i), 0)) < n for i, n in mats):
            return FAIL
        G.spend_gold(state, gold)
        G.use_items(state, [{"ItemIndex": i, "Qty": n} for i, n in mats])
        opt = list(p["opt"])
        opt[slot * 2], opt[slot * 2 + 1] = new["equipmentOptionIndex"], roll_value(new)
        p["pending"], p["pendingSlot"] = opt, slot
        p["count"] = p.get("count", 0) + 1
        G.save_state(state)
        return G.ok(EquipmentNo=p["no"], OptionIndex=chosen, ChangeOptionCount=p["count"],
                    OptionInfo="|".join(str(v) for v in opt), AccountMoney=G.money(state),
                    ItemList=G.item_list(state, [i for i, _ in mats]))
    return with_state(run)


@G.api("equipment/changeOptionFixed")
def change_option_fixed(req):
    def run(state):
        p = find(state, req.get("EquipmentNo"))
        if p is None:
            return FAIL
        pending, slot = p.pop("pending", None), p.pop("pendingSlot", 0)
        if pending and int(req.get("ChangeFlag") or 0):
            p["opt"], p["chosen"] = pending, pending[slot * 2]
        G.save_state(state)
        return G.ok(EquipmentInfo=web(state, p))
    return with_state(run)
