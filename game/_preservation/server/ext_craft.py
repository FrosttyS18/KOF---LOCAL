"""CRAFT page handlers (tools/gen_craft.py has the table rows and the REAL/OURS split).

craft/list  -> CraftList: one CraftInfo per craft made at least once (CraftCount = the account's count; the client reads
               a craft it is not told about as 0). Saved in save.json "craft" {craftIndex: count}.
craft/make  -> take the CraftTable row's materials (items) and gold, add productCount x CraftCount of the product
               (an item for productType 3), count the craft. RemainItemList = the materials left (the client sets
               them); RewardItemList = the amounts gained (the client adds them).
Unlimited test accounts (save.json "unlimited", every item topped up to 999) need no materials: 999 < 1,000 shards.
player/poll + session/poll add an OperateSchedule (category 11, SubGroup [craftIndex]) per craft: REA CraftController.IsOpenCraft.
"""
import gameapi as G

ITEM_MATERIAL, TYPE_ITEM, GOLD = 3, 3, 1


def craft_row(index):
    for r in G.table_rows("CraftTable"):
        if r.get("craftIndex") == index:
            return r
    return None


def materials(row):
    out = []
    for n in range(1, 7):
        if row.get(f"material{n:02d}Type") == ITEM_MATERIAL and row.get(f"material{n:02d}Count"):
            out.append((str(row[f"material{n:02d}Index"]), int(row[f"material{n:02d}Count"])))
    return out


def craft_info(row, count):
    return {"CraftIndex": row["craftIndex"], "ProductType": row.get("productType", 0),
            "ProductIndex": row.get("productIndex", 0), "CraftCount": count, "CraftAbleResetTime": 0}


@G.api("craft/list")
def craft_list(req):
    with G._lock:
        state = G.load_state()
        if state is None:
            return G.ok(CraftList=[])
        out = []
        for k, n in state.get("craft", {}).items():
            row = craft_row(int(k))
            if row and int(n) > 0:
                out.append(craft_info(row, int(n)))
    return G.ok(CraftList=out)


@G.api("craft/make")
def craft_make(req):
    index, times = int(req.get("CraftIndex") or 0), max(1, int(req.get("CraftCount") or 1))
    row = craft_row(index)
    if row is None:
        return {"ResultCode": 1, "ResultMessage": "no such craft"}
    with G._lock:
        state = G.load_state()
        if state is None:
            return {"ResultCode": 1, "ResultMessage": "no account"}
        inv, done = G.items(state), state.setdefault("craft", {})
        free = bool(state.get("unlimited"))
        have = int(done.get(str(index), 0))
        if row.get("isLimitCraftCount") == 1 and not row.get("craftAbleCountAccountResetType") \
                and have + times > int(row.get("maxCraftCount", 0)):
            return {"ResultCode": 1, "ResultMessage": "craft limit reached"}
        mats = materials(row)
        cost = int(row.get("productCostValue", 0)) * times if row.get("productCostType") == GOLD else 0
        if not free:
            if any(int(inv.get(k, 0)) < n * times for k, n in mats):
                return {"ResultCode": 1, "ResultMessage": "not enough materials"}
            if cost and G.money(state)["Gold"] < cost:
                return {"ResultCode": 1, "ResultMessage": "not enough gold"}
            for k, n in mats:
                inv[k] = int(inv.get(k, 0)) - n * times
            if cost:
                G.spend_gold(state, cost)
        gained = []
        if row.get("productType") == TYPE_ITEM:
            k, n = str(row["productIndex"]), int(row.get("productCount", 1)) * times
            inv[k] = int(inv.get(k, 0)) + n
            gained.append({"ItemIndex": int(k), "Qty": n, "Lock": 0, "UpdateTime": G.now_ms()})
        done[str(index)] = have + times
        G.save_state(state)
        remain = G.item_list(state, [k for k, _ in mats])
        money = G.money(state)
    return G.ok(AccountMoney=money, RemainItemList=remain, RewardItemList=gained, RewardBattleCardList=[],
                RewardCharacterList=[])


# ---- schedule: the client lists a craft (CraftTable.GetCraftTypeList / GetCraftCategoryTypeList -> CraftController.
# IsOpenCraft) only when its row has isEventCategory 1 OR an OperateSchedule of category 11 (EOperateCategory Craft)
# whose SubGroup holds the craftIndex is open. Without it both panels stay empty (no tabs, no fighters).
CRAFT_OPS_CATEGORY = 11


def schedules():
    return [G.apidefaults.default("OperateSchedule", Version=1, Category=CRAFT_OPS_CATEGORY, SubCategory=0,
                                  Index=r["craftIndex"],
                                  Detail=G.apidefaults.default("OperateScheduleData", SubGroup=[r["craftIndex"]],
                                                               StartTs=0, EndTs=G.NO_END, OffOnSched=G.ALWAYS_OPEN))
            for r in G.table_rows("CraftTable")]


def _with_schedules(handler):
    def wrapped(req):
        out = handler(req)
        if isinstance(out, dict):
            out["DownloadScheduleList"] = list(out.get("DownloadScheduleList") or []) + schedules()
        return out
    return wrapped


for _name in ("player/poll", "session/poll"):
    G.APIS[_name] = _with_schedules(G.APIS[_name])
