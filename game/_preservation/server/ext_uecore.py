"""UE (Ultimate) core board handlers (tools/gen_uecore.py has the table rows and the REAL/OURS split).

A UE fighter (CharacterTable.frameGrade 110) with an AwakenCoreBoardTable row has the core page's UE tab; its levels
are saved in the fighter's "ueCores" {coreIndex: level}. The client sends the same requests as for the EX board
(core/awakenCoreLevelUp, core/awakenCoreReset), so this module wraps gameapi's EX functions: a UE fighter takes the
UE path, any other fighter the EX one, unchanged:
  G.ex_core_points  -> UE points = sum of AwakenCorePointTable.getPoint for awakened levels passed - levels spent
  G.ex_core_lists   -> the profile's characterAwakenCoreList carries the UE fighters' ueCores
  core/awakenCoreLevelUp -> checks the core's maxLevel, the step's max (AwakenCoreBoardTable), the step's open level
                     (ConfigTable 195008-195010), a sub-level core's unlocked sub-levels (AwakenCoreGroupTable
                     subUnlockLv) and the points
  core/awakenCoreReset   -> every core to 0 for ConfigTable 195011 x 195012 (item 210101 x 1), unlimited accounts free
The reset ticket is given once (5, ours) like the EX one.
"""
import os

import gameapi as G

UE_FRAME = 110
STEP_CONFIG = {2: 195008, 3: 195009, 4: 195010}
STEP_DEFAULT = {1: 1, 2: 30, 3: 50, 4: 60}
RESET_ITEM_KEY, RESET_COUNT_KEY = 195011, 195012
G.ONCE_ITEMS.setdefault("210101", 5)

_cache = {}


def ue_tables():
    """(UE board fighters {fighter: board}, {board: {coreIndex: row}}, {board: row}, {group: [sub-level rows]},
    {board: [(awakenLevel, getPoint)]}), read again when a table file changes"""
    names = ("CharacterTable", "AwakenCoreTable", "AwakenCoreBoardTable", "AwakenCoreGroupTable", "AwakenCorePointTable")
    files = [os.path.join(G.TABLES, t + ".json") for t in names]
    key = tuple(os.path.getmtime(f) if os.path.exists(f) else 0 for f in files)
    if _cache.get("key") != key:
        fighters = {r["characterIndex"]: r["awakenCoreBoardIndex"] for r in G.table_rows("CharacterTable")
                    if r.get("frameGrade") == UE_FRAME and r.get("awakenCoreBoardIndex")}
        cores = {}
        for r in G.table_rows("AwakenCoreTable"):
            if r["awakenCoreBoardIndex"] in fighters.values():
                cores.setdefault(r["awakenCoreBoardIndex"], {})[r["awakenCoreIndex"]] = r
        boards = {r["awakenCoreBoardIndex"]: r for r in G.table_rows("AwakenCoreBoardTable")}
        groups = {}
        for r in G.table_rows("AwakenCoreGroupTable"):
            groups.setdefault(r["awakenCoreGroup"], []).append(r)
        points = {}
        for r in G.table_rows("AwakenCorePointTable"):
            points.setdefault(r["awakenCoreBoardIndex"], []).append((r["awakenLevel"], r["getPoint"]))
        _cache.update(key=key, data=(fighters, cores, boards, groups, points))
    return _cache["data"]


def ue_levels(c):
    return {int(k): int(v) for k, v in (c.get("ueCores") or {}).items()}


def is_ue(index):
    return index in ue_tables()[0]


def ue_points(c):
    fighters, _, _, _, points = ue_tables()
    board = fighters.get(c["index"])
    if board is None:
        return 0
    level = G.awakened_level(c)
    total = sum(p for lv, p in points.get(board, ()) if lv <= level)
    return max(0, total - sum(ue_levels(c).values()))


def step_open(step):
    return int(G.config_number(STEP_CONFIG[step], STEP_DEFAULT[step])) if step > 1 else 1


_ex_points, _ex_lists, _ex_level_up, _ex_reset = (G.ex_core_points, G.ex_core_lists,
                                                  G.APIS["core/awakenCoreLevelUp"], G.APIS["core/awakenCoreReset"])


def core_points(c):
    return ue_points(c) if is_ue(c["index"]) else _ex_points(c)


def core_lists(state):
    out = _ex_lists(state)
    saved = {c["index"]: c for c in state["characters"]}
    for entry in out:
        if is_ue(entry["characterIndex"]):
            levels = ue_levels(saved.get(entry["characterIndex"], {}))
            entry["coreList"] = [{"coreIndex": k, "coreLevel": v} for k, v in sorted(levels.items())]
    return out


G.ex_core_points, G.ex_core_lists = core_points, core_lists


@G.api("core/awakenCoreLevelUp")
def level_up(req):
    index = int(req.get("characterIndex") or 0)
    if not is_ue(index):
        return _ex_level_up(req)
    with G._lock:
        state = G.load_state()
        if state is None:
            return {"ResultCode": 1, "ResultMessage": "no account"}
        fighters, cores, boards, groups, _ = ue_tables()
        board = fighters[index]
        core, add = int(req.get("coreIndex") or 0), int(req.get("addLevel") or 0)
        row = cores.get(board, {}).get(core)
        c = G.character_state(state, index)
        levels = ue_levels(c)
        awakened = G.awakened_level(c)
        ok_ = row is not None and add > 0
        if ok_:
            step = row["step"]
            in_step = sum(v for k, v in levels.items() if cores[board].get(k, {}).get("step") == step)
            cap = row["maxLevel"]
            if row.get("awakenCoreGroup"):         # sub-level cores: only the sub-levels opened by the awakened level
                cap = min(cap, sum(1 for g in groups.get(row["awakenCoreGroup"], ()) if g["subUnlockLv"] <= awakened))
            ok_ = (awakened >= step_open(step) and levels.get(core, 0) + add <= cap and
                   in_step + add <= boards[board].get(f"step{step}MaxLevel", 0) and ue_points(c) >= add)
        if not ok_:
            return {"ResultCode": 1, "ResultMessage": "UE core level up not possible"}
        levels[core] = levels.get(core, 0) + add
        c["ueCores"] = {str(k): v for k, v in sorted(levels.items())}
        G.save_state(state)
    return G.ok(awakenCore={"coreIndex": core, "coreLevel": levels[core]},
                corePoint={"characterIndex": index, "corePoint": ue_points(c)})


@G.api("core/awakenCoreReset")
def reset(req):
    index = int(req.get("characterIndex") or 0)
    if not is_ue(index):
        return _ex_reset(req)
    with G._lock:
        state = G.load_state()
        if state is None:
            return {"ResultCode": 1, "ResultMessage": "no account"}
        c = G.character_state(state, index)
        item, cost = str(int(G.config_number(RESET_ITEM_KEY, 210101))), int(G.config_number(RESET_COUNT_KEY, 1))
        inv = G.items(state)
        if c.get("ueCores"):
            if not state.get("unlimited"):
                if int(inv.get(item, 0)) < cost:
                    return {"ResultCode": 1, "ResultMessage": "no UE core reset item"}
                inv[item] = int(inv[item]) - cost
            c["ueCores"] = {}
            G.save_state(state)
    return G.ok(accountMoney=G.money(state), corePoint={"characterIndex": index, "corePoint": ue_points(c)},
                remainItem=G.item_list(state, [item])[0])
