"""Core board material costs (tools/gen_corecost.py has the REAL / OURS split): spots cost the cores named by
CoreSpotTable.unlockItem1..5Index/Count (plus gold). core/coreAcquire and core/coreAcquireAll run the original
handlers, but the spots they would unlock are priced from the table first: too few cores -> an error and nothing is
spent; otherwise the server's own ItemList replaces the client's (the client sends the same). Accounts with
save.json "unlimited" skip the stock check. Test accounts get a one-time core stock (ours, "grants" key coreStock1):
40 of each of the 15 cores 1380-1394.
"""
import gameapi as G

STOCK_KEY, STOCK_ITEMS, STOCK_EACH = "coreStock1", range(1380, 1395), 40
_orig_items, _orig_acquire = G.items, G.acquire_cores


def items(state):
    inv = _orig_items(state)
    granted = state.setdefault("grants", [])
    if STOCK_KEY not in granted:
        for k in STOCK_ITEMS:
            inv[str(k)] = int(inv.get(str(k), 0)) + STOCK_EACH
        granted.append(STOCK_KEY)
    return inv


class _Short(Exception):
    pass


def spot_cost(spot):
    return [(str(spot[f"unlockItem{n}Index"]), int(spot.get(f"unlockItem{n}Count", 0)))
            for n in range(1, 6) if spot.get(f"unlockItem{n}Index")]


def acquire_cores(req, pick):
    spots = {r["coreSpotIndex"]: r for r in G.table_rows("CoreSpotTable")}

    def priced(c, trees, have):
        out = list(pick(c, trees, have))
        need = {}
        for i in out:
            for k, n in spot_cost(spots.get(trees[i]["coreSpotIndex"], {})):
                need[k] = need.get(k, 0) + n
        state = G.load_state()
        inv = G.items(state) if state else {}
        if not (state or {}).get("unlimited") and any(int(inv.get(k, 0)) < n for k, n in need.items()):
            raise _Short
        req["ItemList"] = [{"ItemIndex": int(k), "Qty": n} for k, n in need.items()]
        return out
    try:
        return _orig_acquire(req, priced)
    except _Short:
        return {"ResultCode": 1, "ResultMessage": "not enough cores"}


G.items, G.acquire_cores = items, acquire_cores
