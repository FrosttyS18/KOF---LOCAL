"""Striker link bonus payout (tools/gen_links.py has the tables; recon/striker_links.md the client side).
The client only shows the link buffs (SupporterRelationTable -> BuffTable: sub type 7 = gold, 8 = EXP). OURS: the server pays
them on a clear. Each end / mop-up handler is wrapped: the original runs, then the gold and EXP it just paid (diff of the
saved wallet, account exp and the team's fighter exp) are raised by the summed % of the active links of the team (the end
request's CharacterList[i].SupportCharacterIndex = the striker of fighter i, else PlayDeckInfo.PlayFighterArray/PlayStrikerArray;
a link = row of the main fighter's supporterRelationGroup whose supporterCharacter1Index is the striker, condition met).
The reply (AccountMoney.Gold, PlayerAccount.Exp, gold entries of ClearRewardList / RewardContentsList) is raised to match. The
client adds nothing itself (its tooltip only reads the table), so there is no double count.
"""
import gameapi as G

SUB_GOLD, SUB_EXP = "7", "8"


def _team(req):
    pairs = [(int(c.get("CharacterIndex") or 0), int(c.get("SupportCharacterIndex") or 0))
             for c in req.get("CharacterList") or [] if isinstance(c, dict)]
    deck = req.get("PlayDeckInfo") or {}
    if not any(s for _, s in pairs):
        pairs = list(zip(deck.get("PlayFighterArray") or [], deck.get("PlayStrikerArray") or []))
    return [(int(m), int(s)) for m, s in pairs if m and s]


def link_percent(state, req):
    """-> (gold fraction, exp fraction, fighters in the team)"""
    chars = {r["characterIndex"]: r for r in G.table_rows("CharacterTable")}
    buffs = {b["buffIndex"]: b for b in G.table_rows("BuffTable")}
    links = {}
    for r in G.table_rows("SupporterRelationTable"):
        links.setdefault((r["supporterRelationGroup"], r["supporterCharacter1Index"]), r)
    gold = exp = 0.0
    for main, striker in _team(req):
        row = links.get((chars.get(main, {}).get("supporterRelationGroup", 0), striker))
        if not row or not _active(state, row, main, striker):
            continue
        for n in (1, 2, 3):
            b = buffs.get(row.get(f"supporterRelationBuff{n}") or 0)
            if not b or b.get("buffInfoMainType") != 11:
                continue
            power = float(b.get("buffPowerBase") or 0)
            power = power / 100 if power > 1 else power
            if str(b.get("buffInfoSubType")) == SUB_GOLD:
                gold += power
            elif str(b.get("buffInfoSubType")) == SUB_EXP:
                exp += power
    return gold, exp, [m for m, _ in _team(req)]


def _active(state, row, main, striker):
    kind, value = int(row.get("activeConditionType") or 0), int(row.get("activeConditionValue") or 0)
    if kind not in (1, 2, 3, 4):
        return True
    who = main if kind in (1, 3) else striker
    c = next((c for c in state.get("characters", []) if c["index"] == who), None)
    if c is None:
        return False
    return (G.fighter_level(who, c.get("exp", 0)) if kind in (1, 2) else c.get("grade", 0)) >= value


def _snapshot(state, team):
    return (state.get("money", {}).get("Gold", 0), state.get("exp", 0),
            {m: next((c.get("exp", 0) for c in state.get("characters", []) if c["index"] == m), 0) for m in team})


def _wrap(name):
    original = G.APIS[name]

    def handler(req):
        team = _team(req)
        with G._lock:
            before = G.load_state()
        resp = original(req)
        if not team or before is None or resp.get("ResultCode", 0) != 0 or int(resp.get("BattleResult", G.WIN)) != G.WIN:
            return resp
        with G._lock:
            state = G.load_state()
            gold_pct, exp_pct, fighters = link_percent(state, req)
            if not (gold_pct or exp_pct):
                return resp
            g0, e0, f0 = _snapshot(before, fighters)
            g1, e1, f1 = _snapshot(state, fighters)
            gold, exp = int(max(0, g1 - g0) * gold_pct), int(max(0, e1 - e0) * exp_pct)
            wallet = state.setdefault("money", dict(G.START_MONEY))
            wallet["Gold"] = wallet.get("Gold", 0) + gold
            state["exp"] = state.get("exp", 0) + exp
            for m in fighters:
                bonus = int(max(0, f1[m] - f0[m]) * exp_pct)
                if bonus:
                    G.character_state(state, m)["exp"] += bonus
            G.save_state(state)
            money, player = G.money(state), None
        if gold and isinstance(resp.get("AccountMoney"), dict):
            resp["AccountMoney"] = money
        if exp and isinstance(resp.get("PlayerAccount"), dict):
            resp["PlayerAccount"]["Exp"] = state["exp"]
        for key in ("ClearRewardList", "RewardContentsList"):       # show the bonus on the result's gold entries
            for e in resp.get(key) or []:
                if isinstance(e, dict) and e.get("GoodsType") == G.GOLD_GOODS:
                    e["ContentsCount"] = int(e["ContentsCount"] * (1 + gold_pct))
        return resp

    G.APIS[name] = handler


for _name in ("adventure/stageEnd", "questEvent/questEventEnd", "questEvent/crucibleTowerEnd",
              "adventure/stageMopUp", "questEvent/questEventMopUp", "questEvent/crucibleTowerMopUp"):
    if _name in G.APIS:
        _wrap(_name)
