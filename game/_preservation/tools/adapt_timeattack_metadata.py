"""Adapt Time Attack master metadata for the PC client (v1024+).

Three adaptations, all derived from data already in the target dir (no new prizes,
ids or time rules are invented):

1. ChallengeScoreTable.needTime seconds -> milliseconds. The PC client formats
   needTime as milliseconds (NEO.Table.Protocol.ChallengeScoreProto.get_NeedTimeDescTag2
   computes needTime * 10000 ticks, i.e. ms, and formats min/sec/ms; see
   native-analysis/ta-ui-rewards-contract.md rev3). The imported mobile source stores
   seconds: 300/180/120 for challengeGrade 1/2/3, meaning 5/3/2 minutes per the source
   strings ("Clear within 3 minutes"). Each row becomes 300000/180000/120000; only the
   needTime field changes.

2. RewardDisplayTable rows for the Challenge reward groups. The challenge UI resolves
   reward icons through challengeRewardDisplayGroup/scoreRewardDisplayGroup, but no
   source table ships RewardDisplay rows for groups 9461xxxx/9462xxxx. One display row
   is derived per real RewardGroup row of every group referenced by the challenge
   schedule/score tables: same rewardType, same goods/item index, same fixed amount.
   Row identity uses rewardGroupIndex (1800000001..), which does not collide with
   existing display ids. Every original display row is preserved untouched, and rows
   already derived by a previous run are kept as-is.

3. strings_en.json timer format for System.Challenge.Text.34.Name. The native time
   formatters (six consumers per native-analysis/ta-text34-timer-format.md) feed
   StringFormatter three arguments (minutes, seconds, milliseconds); both shipped
   string tables carry the label 'Rewards' there, which is not a time format. This is
   an explicit adaptation, not a recovered translation: the value becomes
   '{0:00}:{1:00}.{2:000}', matching the three native arguments exactly. Only the
   known value 'Rewards', an absent/empty placeholder, or the target format itself are
   accepted; any other value aborts the whole run before a single file is written.

Ranking data and useChallengeRanking are untouched. Validation is complete before any
write, files are rewritten with their original CRLF/LF line endings, and a run with
nothing to change writes nothing. adapt_timeattack_metadata() is the reusable entry
point for the import pipeline; the CLI wraps it for staging runs (--check validates
only).
"""
import argparse
import json
import os
import sys

SECONDS_BY_GRADE = {1: 300, 2: 180, 3: 120}
MILLIS_BY_GRADE = {1: 300000, 2: 180000, 3: 120000}
SCORE_GROUPS = set(range(1, 10))
REWARD_TYPES = (1, 2, 13)
GOODS_BY_TYPE = {1: 1, 2: 0}
TIMER_FORMAT_TAG = "System.Challenge.Text.34.Name"
TIMER_FORMAT = "{0:00}:{1:00}.{2:000}"
TIMER_FORMAT_KNOWN_VALUES = ("Rewards", "", None)


class AdaptationError(RuntimeError):
    """Raised when the data diverges from the known real table shapes."""


def _read(path, name):
    if not os.path.exists(path):
        raise AdaptationError("missing table file: %s" % path)
    raw = open(path, "rb").read()
    doc = json.loads(raw.decode("utf-8"))
    return doc, b"\r\n" in raw


def _load(path, name):
    doc, crlf = _read(path, name)
    rows = doc.get("rows") if isinstance(doc, dict) else doc
    if rows is None or not isinstance(rows, list):
        raise AdaptationError("%s: no rows list" % name)
    return doc, rows, crlf


def _dump(path, doc, crlf):
    with open(path, "w", encoding="utf-8", newline=("\r\n" if crlf else "\n")) as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


def _adapt_scores(doc, rows, name):
    converted = already = 0
    seen = {}
    pks = set()
    for row in rows:
        idx = int(row.get("challengeScoreIndex") or 0)
        group = int(row.get("challengeScoreGroup") or 0)
        grade = int(row.get("challengeGrade") or 0)
        if not idx or idx in pks:
            raise AdaptationError("%s: challengeScoreIndex %r null or duplicated" % (name, idx))
        pks.add(idx)
        if group not in SCORE_GROUPS or grade not in SECONDS_BY_GRADE:
            raise AdaptationError("%s: unexpected group/grade in row %s" % (name, idx))
        if idx != group * 10 + grade:
            raise AdaptationError("%s: row pk %d != group %d * 10 + grade %d" % (name, idx, group, grade))
        seen.setdefault(group, set()).add(grade)
        need = int(row.get("needTime") or 0)
        if need == MILLIS_BY_GRADE[grade]:
            already += 1
            continue
        if need != SECONDS_BY_GRADE[grade]:
            raise AdaptationError(
                "%s: row %s grade %d has needTime %d (expected %d s or %d ms)"
                % (name, idx, grade, need, SECONDS_BY_GRADE[grade], MILLIS_BY_GRADE[grade]))
        row["needTime"] = MILLIS_BY_GRADE[grade]
        converted += 1
    if len(rows) != 27 or any(seen.get(g) != {1, 2, 3} for g in SCORE_GROUPS):
        raise AdaptationError("%s: expected 27 rows covering grades 1-3 for groups 1-9" % name)
    return converted, already


def _referenced_groups(schedule_rows, score_rows):
    groups = set()
    for row in score_rows:
        groups.add(int(row.get("scoreRewardGroup") or 0))
        groups.add(int(row.get("scoreRewardDisplayGroup") or 0))
    for row in schedule_rows:
        groups.add(int(row.get("challengeRewardGroup") or 0))
        groups.add(int(row.get("challengeRewardDisplayGroup") or 0))
    groups.discard(0)
    return groups


def _derive_display_rows(reward_rows, display_rows, groups, goods_rows, item_rows):
    goods = {int(r.get("goodsIndex") or 0) for r in goods_rows}
    items = {int(r.get("itemIndex") or 0) for r in item_rows}
    existing = {}
    for row in display_rows:
        existing.setdefault(int(row.get("rewardDisplayIndex") or 0), []).append(row)
    derived = []
    for row in reward_rows:
        group = int(row.get("rewardGroup") or 0)
        if group not in groups:
            continue
        rtype = int(row.get("rewardType") or 0)
        if rtype not in REWARD_TYPES:
            raise AdaptationError("RewardGroupTable: group %d row has rewardType %d" % (group, rtype))
        for key, want in (("randomRewardProbability", 10000), ("rewardSubGroupRate", 10000),
                          ("showReward", 1), ("showRewardCount", 1)):
            if int(row.get(key) or 0) != want:
                raise AdaptationError(
                    "RewardGroupTable: group %d row %s=%s (deterministic rows only)"
                    % (group, key, row.get(key)))
        if int(row.get("rewardSubGroup") or 0) not in (1, 2):
            raise AdaptationError("RewardGroupTable: group %d has rewardSubGroup %s"
                                  % (group, row.get("rewardSubGroup")))
        count = int(row.get("contentsCountMin") or 0)
        count_max = int(row.get("contentsCountMax") or 0)
        if count_max and count_max != count:
            raise AdaptationError("RewardGroupTable: group %d has contentsCountMin %d != contentsCountMax %d"
                                  % (group, count, count_max))
        if count <= 0:
            raise AdaptationError("RewardGroupTable: group %d has contentsCountMin %s"
                                  % (group, row.get("contentsCountMin")))
        if rtype == 13:
            goods_index = int(row.get("contentsIndex") or 0)
            if goods_index not in items:
                raise AdaptationError("RewardGroupTable: group %d item %d missing from ItemTable"
                                      % (group, goods_index))
        else:
            goods_index = GOODS_BY_TYPE[rtype]
            if rtype == 1 and goods_index not in goods:
                raise AdaptationError("RewardGroupTable: group %d goods %d missing from GoodsTable"
                                      % (group, goods_index))
        derived.append({"rewardDisplayIndex": int(row.get("rewardGroupIndex") or 0),
                        "rewardDisplayGroup": group,
                        "rewardDisplayType": rtype,
                        "rewardDisplayGrade": 0,
                        "rewardDisplayCount": count,
                        "rewardDisplayGoodsIndex": goods_index})
    added = present = 0
    for new in derived:
        clash = existing.get(new["rewardDisplayIndex"], [])
        for old in clash:
            if old == new:
                present += 1
                break
        else:
            if clash:
                raise AdaptationError("RewardDisplayTable: index %d already used by a different row"
                                      % new["rewardDisplayIndex"])
            display_rows.append(new)
            existing.setdefault(new["rewardDisplayIndex"], []).append(new)
            added += 1
    return derived, added, present


def _adapt_timer_format(strings_doc, name):
    value = strings_doc.get(TIMER_FORMAT_TAG)
    if value == TIMER_FORMAT:
        return False
    if value not in TIMER_FORMAT_KNOWN_VALUES:
        raise AdaptationError("%s: %s holds unexpected value %r (only %r, empty/absent or the target format are accepted)"
                              % (name, TIMER_FORMAT_TAG, value, "Rewards"))
    strings_doc[TIMER_FORMAT_TAG] = TIMER_FORMAT
    return True


def adapt_timeattack_metadata(data_dir, write=True):
    """Adapt the Time Attack tables in data_dir; returns a report dict.

    data_dir must hold ChallengeScheduleTable/ChallengeScoreTable/RewardGroupTable/
    RewardDisplayTable/GoodsTable/ItemTable .json plus strings_en.json. Validation is
    complete before any file is touched; with write=False nothing is modified, and a
    run with nothing to change rewrites no file.
    """
    data_dir = os.path.abspath(data_dir)
    score_doc, score_rows, score_crlf = _load(
        os.path.join(data_dir, "ChallengeScoreTable.json"), "ChallengeScoreTable")
    sched_doc, sched_rows, _ = _load(
        os.path.join(data_dir, "ChallengeScheduleTable.json"), "ChallengeScheduleTable")
    group_doc, group_rows, _ = _load(
        os.path.join(data_dir, "RewardGroupTable.json"), "RewardGroupTable")
    disp_doc, disp_rows, disp_crlf = _load(
        os.path.join(data_dir, "RewardDisplayTable.json"), "RewardDisplayTable")
    _, goods_rows, _ = _load(os.path.join(data_dir, "GoodsTable.json"), "GoodsTable")
    _, item_rows, _ = _load(os.path.join(data_dir, "ItemTable.json"), "ItemTable")
    strings_doc, strings_crlf = _read(
        os.path.join(data_dir, "strings_en.json"), "strings_en")

    converted, already = _adapt_scores(score_doc, score_rows, "ChallengeScoreTable")
    timer_changed = _adapt_timer_format(strings_doc, "strings_en")
    groups = _referenced_groups(sched_rows, score_rows)
    missing = sorted(g for g in groups
                     if not any(int(r.get("rewardGroup") or 0) == g for r in group_rows))
    if missing:
        raise AdaptationError("reward groups referenced by the challenge tables but absent from RewardGroupTable: %s"
                              % missing)
    group_total = [r for r in group_rows if int(r.get("rewardGroup") or 0) in groups]
    derived, added, present = _derive_display_rows(group_rows, disp_rows, groups, goods_rows, item_rows)

    wrote = False
    if write and (converted or added or timer_changed):
        if converted:
            _dump(os.path.join(data_dir, "ChallengeScoreTable.json"), score_doc, score_crlf)
        if added:
            _dump(os.path.join(data_dir, "RewardDisplayTable.json"), disp_doc, disp_crlf)
        if timer_changed:
            _dump(os.path.join(data_dir, "strings_en.json"), strings_doc, strings_crlf)
        wrote = True
    return {"data_dir": data_dir, "wrote": wrote,
            "score_rows": len(score_rows), "score_converted": converted, "score_already_ms": already,
            "reward_groups": len(groups), "reward_rows": len(group_total),
            "display_derived": len(derived), "display_added": added, "display_present": present,
            "timer_format_changed": timer_changed}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", required=True, help="data dir with the table .json files")
    parser.add_argument("--check", action="store_true", help="validate only; write nothing")
    args = parser.parse_args(argv)
    try:
        report = adapt_timeattack_metadata(args.data, write=not args.check)
    except AdaptationError as exc:
        print("ABORT: %s" % exc)
        return 2
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
