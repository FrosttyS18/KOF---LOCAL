"""The fighter CODEX event (tools/gen_eventbook.py has the tables and the REAL / OURS split).

- player/poll + session/poll: the codex pages' OperateSchedule (Category 4 Event, SubCategory 7 EventBook, Index = the
  EventBookMainTable row), always open - this is what makes the lobby icon (EventDataTable type 19) appear.
- quest/list QuestType 6000 needs no code (gameapi.quest_list lists QuestTable rows of the type); the progress of the
  codex missions (completeTermsType 9101: value1 fighter, value2 awakening phase, 0 = owned) is added to
  gameapi.quest_progress, their claims are kept in save.json "eventBook" {"claims": {quest: time}} and
  quest/reward / quest/rewardAll pay them (RewardGroupTable). Imprint stones (GoodsType 14) are put into the save's
  "stones" and returned in RewardImprintStoneList.
- book/bookReward, book/bookRewardAll: the Collection Room's book, not this event; answered with no reward.
"""
import calendar
import time

import gameapi as G

EVENTBOOK_QUEST, AWAKEN_RULE = 6000, 9101
EVENT_CATEGORY, EVENTBOOK_SUB = 4, 7           # EOperateCategory.Event, ECommonEventType.EventBook
STONE_GOODS = 14                               # GoodsType.ImprintStone
FIRST_STONE_NO = 300_000                       # tools/max_build.py's stones are 100000+
_granted = []                                  # ImprintStoneWEBData of the claim in progress


def awaken_phase(state, fighter):
    """-1 = not owned, else the fighter's awakening phase"""
    if not G.owns(state, fighter):
        return -1
    c = next((c for c in state.get("characters", []) if c["index"] == fighter), None)
    return int((c or {}).get("awaken", 0) or 0)


_quest_progress = G.quest_progress


def quest_progress(state, row):
    if row.get("completeTermsType") != AWAKEN_RULE:
        return _quest_progress(state, row)
    phase = awaken_phase(state, row.get("completeTermsTypeValue1", 0))
    need = row.get("completeTermsTypeValue2", 0)
    return (1 if phase >= need >= 0 and phase >= 0 else 0), 1


_claims = G.claims


def claims(state, row):
    if row.get("questType") == EVENTBOOK_QUEST:
        return state.setdefault("eventBook", {}).setdefault("claims", {})
    return _claims(state, row)


_give_rewards = G.give_rewards


def give_rewards(state, group):
    contents, item_ids, fighters = _give_rewards(state, group)
    for r in G.table_rows("RewardGroupTable"):
        if r.get("rewardGroup") == group and r.get("rewardType") == STONE_GOODS:
            stones = state.setdefault("stones", [])
            for _ in range(max(1, r.get("contentsCountMin", 1))):
                no = max([FIRST_STONE_NO - 1] + [e["no"] for e in stones]) + 1
                stones.append({"no": no, "index": r["contentsIndex"], "enchant": 0, "created": G.now_ms()})
                _granted.append(G.apidefaults.default("ImprintStoneWEBData", ImprintStoneNo=no,
                                                      ImprintStoneIndex=r["contentsIndex"], Enchant=0,
                                                      CreateTime=G.now_ms()))
            contents.append(G.reward(STONE_GOODS, max(1, r.get("contentsCountMin", 1)), r["contentsIndex"]))
    return contents, item_ids, fighters


G.quest_progress, G.claims, G.give_rewards = quest_progress, claims, give_rewards


def with_stones(handler):
    def wrapped(req):
        _granted.clear()
        out = handler(req)
        if _granted and isinstance(out, dict):
            out["RewardImprintStoneList"] = list(_granted)
        _granted.clear()
        return out
    return wrapped


for _name in ("quest/reward", "quest/rewardAll"):
    G.APIS[_name] = with_stones(G.APIS[_name])


CYCLE_EPOCH = calendar.timegm((2020, 1, 1, 0, 0, 0))   # rolling 4-week cycles count from here (unix s, UTC)
CYCLE_DAYS = 28


def cycle_window():
    """(start, end) of the current 4-week cycle in unix seconds; end = start + 28 days."""
    period = CYCLE_DAYS * 86400
    start = CYCLE_EPOCH + (int(time.time()) - CYCLE_EPOCH) // period * period
    return start, start + period


def schedules():
    start, end = cycle_window()
    return [G.apidefaults.default("OperateSchedule", Version=1, Category=EVENT_CATEGORY, SubCategory=EVENTBOOK_SUB,
                                  Index=r["eventBookMainIndex"],
                                  Detail=G.apidefaults.default("OperateScheduleData", SubGroup=[r["eventBookMainIndex"]],
                                                               StartTs=start, EndTs=end, OffOnSched=G.ALWAYS_OPEN))
            for r in G.table_rows("EventBookMainTable")]


def with_schedules(handler):
    def wrapped(req):
        out = handler(req)
        if isinstance(out, dict):
            out["DownloadScheduleList"] = list(out.get("DownloadScheduleList") or []) + schedules()
        return out
    return wrapped


for _name in ("player/poll", "session/poll"):
    G.APIS[_name] = with_schedules(G.APIS[_name])


@G.api("book/bookReward")
def book_reward(req):
    """Collection Room book reward: no collection tables offline yet, so nothing is paid."""
    return G.ok(CollectionType=int(req.get("CollectionType") or 0),
                CollectionRewardIndex=int(req.get("CollectionRewardIndex") or 0), RewardType=0, RewardList=[],
                TeamCollectionIndex=0)


@G.api("book/bookRewardAll")
def book_reward_all(req):
    return G.ok(ListBookReward=[
        G.apidefaults.default("BookRewardResponseVO", CollectionType=int(v.get("CollectionType") or 0),
                              CollectionRewardIndex=int(v.get("CollectionRewardIndex") or 0), RewardList=[])
        for v in req.get("ListBookReward") or []])
