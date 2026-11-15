"""Project the REAL fighter skills of the 8 BuffSelect NPC Character bosses (Goenitz 582013,
Krizalid 582020, Mukai 582028, Ash 582033, Nakoruru 582048, Chang 582056, ZeroOriginal 582061,
MrBIG 582074) into PC MonsterSkillTable rows -- staging/TEMP only. Rock Howard (582042) and
ZeroClone (582068) are BLOCKED: no type-5 combos and cooldown non-constant steps in every
same-prefab fighter -- explicitly out of scope.

Schema-driven projection: target fields are the INTERSECTION of SkillProto (97) and
MonsterSkillProto (51) field names from schema.json (renaming skillIndex/skillIndexString/
skillNameTag to monsterSkill*), and each row copies every target field IT carries -- rows with
extra fields (linked/buffs/priority) are never flattened by another row's column set. Fields
the Monster proto owns but the source row lacks stay OMITTED (several under parallel review
219); no defaults are invented and the gap is reported.

Damage curve: CLOSED against the proven Monster consumer (npc-skill-value-contract.md 228:
Skill.InitializeData 0x1811FAC50 computes m_skillDamageRatio = skillDamageRBase +
skillDamageRPerLv*(level-1) when ISkillData is MonsterSkillProto, whose SkillDamageRLv1..10
getters are stub 0 -- the Monster never reads the Lv slots). The projection therefore derives
skillDamageRPerLv from the source row's own series: every existing skillDamageRLvN point
(N in 1..10, holes preserved, real level indices) is validated against Base + step*(N-1);
Lv1 must equal Base, a non-linear series aborts, a constant series keeps step 0, and the
source's two step conventions (PerLv for actives, Base*PerLv for combos/ults) collapse into
the REAL step the Monster consumer needs. Levels above the highest proven source level (Lv5
here) are a declared LINEAR NPC EXTENSION of the Monster channel, not recovered originals --
the player path reads the explicit Lv1..5 curves instead. COOLDOWN stays source-exact: the
real cooldown consumer is still unproven (m_skillCooltime@0xB8; the 480/484 reads were PG),
so the cooltime guard keeps Lv1==Base + constant-step (or the awaken pattern lv1=Base then
0s) and only REPORTS a step != PerLv.

Bundle proof (typed): the Skill assets of each fighter's own character bundle are decoded with
read_unity_typed_fields (consumed == size required on every object that has m_tableIndexString);
a canonical skill name only counts as present when a real decoded Skill object carries it -- no
raw-string regex.

Canonical sources: fighters 1106 (Goenitz_96) and 1184 (Krizalid_takeoff_99), the exact
characterPrefab each monster row names. Their NPC aliases 20122/20451 duplicate a SUBSET of the
same Skill.* names under different ids; the canonical superset is always used and no stat of
another fighter is copied. Versions come from the rows' own "#version" suffixes (Goenitz #3,
Krizalid #6).

skillVariationNumber and the 16-slot layer: the two boss rows gain skillVariationNumber (3/6),
baseAttack1..4 (their fighter's own Combo01..04) and skill1..N root actives (types 1/2/3,
ordered (activeSkillType, skillIndex) -- a DOCUMENTED ADAPTATION; the mobile reference rows
530015/530018 order alphabetically instead) as full-row patches; every other column stays
identical. Slot patching compares each proposal field with the row: absent/zero adds, equal
is a no-op, a different non-zero value aborts. NOTE (npc-fallback-review.md 225): SetBattle's
fallback initializes ONE Skill (Array.Find); the multi-skill path is the 16-slot table loop --
sufficiency is an OPEN question, no fix claimed.

PG ADAPTATION: the NPC boss Goenitz's graph reserves finisher/ultimate by BBParameter name;
the CharacterBattleController checkPG delegate (b__73_1 @ 0x18115E500, chain skill+0x278 ->
invoke(usePG@+0x180)) checks the skill's cost. NPC PG = 40 (CBC+0x128 -> NmssSvFloat+0x18), F01Start=300, U01Start=500
-> both unreachable (resource deadlock). The PROJECTION rewrites usePGBase to 0.0 on exactly
MonsterSkillTable rows 110609 (F01Start.IbukiNagayo) and 110626 (U01Start.SinYaotomeZissokoku)
-- a declared NPC ADAPTATION to avoid the boss-graph deadlock, NOT a recovered original.
Player-side SkillTable stays untouched (player Goenitz still pays 300/500).

Idempotency: running against already-adapted data is a no-op when the existing rows match the
projection value-by-value (skill rows), every slot field (boss rows), and PG-adapted rows
already carry usePGBase 0.0; a genuine conflict aborts before any write.

Outputs (only with --apply, only to --output TEMP): MonsterSkillTable.additions.json (rows not
already present), MonsterTable.row-patches.json (boss rows lacking the variation), report.json.
Default --check validates everything read-only. No importer hook, no cache/master writes.

usage: adapt_buffselect_pc_npc_skills.py --cache DIR --data DIR [--output DIR] [--apply]
"""
import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # the embedded python's _pth never adds the script's own folder
import read_unity_typed_fields as T

BOSSES = {582013: ("1106", "prefabs_character_goenitz", 3),
          582020: ("1184", "prefabs_character_99_krizalid", 6),
          582028: ("1249", "prefabs_character_03_mukai", 10),
          582033: ("1021", "prefabs_character_03_ash", 10),
          582048: ("1252", "prefabs_character_14_nakoruru", 14),
          582056: ("1059", "prefabs_character_tf_chang", 20),
          582061: ("1369", "prefabs_character_tf_zerooriginal", 20),
          582074: ("1247", "prefabs_character_tf_mrbig", 20)}
BLOCKED = {582042, 582068}  # Rock Howard + ZeroClone: no type-5 combos, cooldown non-constant
LEGACY = {582013, 582020}   # Goenitz/Krizalid: preserve the curve derivation of the existing 51 rows
ALIASES = {"1106": "20122", "1184": "20451"}
RENAMES = {"skillIndex": "monsterSkillIndex", "skillIndexString": "monsterSkillIndexString",
           "skillNameTag": "monsterSkillNameTag"}
REVIEW_219 = ("characterTarget", "phantomSkillDamageRBase", "setBuffIndexString1", "setBuffIndexString2",
              "setBuffIndexString3", "setBuffIndexString4", "setBuffIndexString5")
ROOT_TYPES = (1, 2, 3)          # active specials the 16-slot Character loop should initialize
BASE_ATTACK_TYPE = 5            # Combo01..04 of the fighter's own prefab
MAX_ROOT_SLOTS = 12
EPS = 1e-6
PG_ZERO = {110609: "Skill.Goenitz.F01Start.IbukiNagayo#3",
           110626: "Skill.Goenitz.U01Start.SinYaotomeZissokoku#3"}


def float32_ulp(x):
    """True float32 ULP via exponent extraction (math.ulp returns the DOUBLE ULP)."""
    import math, struct
    f = struct.unpack("f", struct.pack("f", x))[0]
    if math.isnan(f) or math.isinf(f):
        fail("float32_ulp: non-finite input %r" % x)
    if f == 0.0:
        return struct.unpack("f", struct.pack("I", 1))[0]
    bits = struct.unpack("I", struct.pack("f", f))[0]
    exp = (bits >> 23) & 0xFF
    if exp == 0:
        return struct.unpack("f", struct.pack("I", 1))[0]
    return 2.0 ** (exp - 127 - 23)


def damage_curve_legacy(row):
    """Legacy curve derivation (round to 6dp) — used ONLY for LEGACY bosses whose existing
    MonsterSkillTable rows were created with this algorithm; produces byte-exact matches."""
    lvs = {n: row.get("skillDamageRLv%d" % n) for n in range(1, 11)
           if row.get("skillDamageRLv%d" % n) is not None}
    if not lvs:
        return None, {}
    b = row.get("skillDamageRBase")
    if b is None:
        fail("legacy damage curve: skill %s carries Lv series but no skillDamageRBase"
             % row.get("skillIndex"))
    if 1 in lvs and abs(float(lvs[1]) - float(b)) > EPS:
        fail("legacy damage curve: skillDamageRLv1=%r != skillDamageRBase=%r for skill %s"
             % (lvs[1], b, row.get("skillIndex")))
    order = sorted(lvs)
    if len(order) < 2:
        return None, lvs
    step = round((float(lvs[order[-1]]) - float(lvs[order[0]])) / (order[-1] - order[0]), 6)
    for n in order:
        expect = float(b) + step * (n - 1)
        if abs(float(lvs[n]) - expect) > EPS:
            fail("legacy damage curve: skill %s Lv%d=%r != Base+step*(N-1)=%.6f"
                 % (row.get("skillIndex"), n, lvs[n], expect))
    return step, lvs


def fail(msg):
    sys.exit("adapt_buffselect_pc_npc_skills: %s" % msg)


def rows_of(data, table):
    path = os.path.join(data, table + ".json")
    if not os.path.isfile(path):
        fail("staging data lacks %s.json" % table)
    return json.load(open(path, encoding="utf-8"))["rows"]


def bundle_skill_names(cache, bundle):
    """Skill names proven by typed decode: every object carrying m_tableIndexString decodes with
    consumed == size; only decoded Skill.* values count."""
    path = os.path.join(cache, "assetbundles", hashlib.md5(bundle.encode()).hexdigest())
    if not os.path.isfile(path):
        fail("cache lacks bundle %s" % bundle)
    tb = T.load_typed_bundle(path)
    slots = [t for t in tb["types"] if any(n["name"] == "m_tableIndexString" for n in t["nodes"])]
    if not slots:
        fail("bundle %s carries no typed object with m_tableIndexString" % bundle)
    names = set()
    for t in slots:
        for pid in sorted(tb["rows"]):
            row = tb["rows"][pid]
            if row["typeSlot"] != t["slot"]:
                continue
            body = tb["stream"][row["offset"]:row["offset"] + row["size"]]
            try:
                records, consumed = T.decode_object(body, t["nodes"])
            except Exception:
                fail("bundle %s object %d fails typed decode" % (bundle, pid))
            if consumed != row["size"]:
                fail("bundle %s object %d consumed %d of %d" % (bundle, pid, consumed, row["size"]))
            for r in records:
                if r["path"].endswith("m_tableIndexString") and isinstance(r["value"], str) \
                        and r["value"].startswith("Skill."):
                    names.add(r["value"])
    return names


def curve_guard(row):
    """COOLDOWN-only guard (the damage series moved to damage_curve): Lv1 must equal Base and
    the series must be constant-step (LvN = Base + (N-1)*step) or the awaken pattern lv1=Base
    with 0 from lv2 on. The cooldown consumer is unproven (m_skillCooltime@0xB8), so a step
    != PerLv is REPORTED, not fatal, and the source's exact values are kept."""
    findings = []
    for base, per, prefix in (("coolTimeBase", "coolTimePerLv", "coolTimeLv"),):
        lvs = [row.get(prefix + str(n)) for n in range(1, 9)
               if row.get(prefix + str(n)) is not None]
        if not lvs:
            continue
        b = row.get(base)
        if b is None or abs(float(lvs[0]) - float(b)) > EPS:
            fail("curve guard: %s1=%r != %s=%r for skill %s"
                 % (prefix, lvs[0], base, b, row.get("skillIndex")))
        if len(lvs) > 1 and not (all(float(v) == 0.0 for v in lvs[1:])):
            steps = {round(float(lvs[i + 1]) - float(lvs[i]), 6) for i in range(len(lvs) - 1)}
            if len(steps) != 1:
                fail("curve guard: %s series of skill %s is not constant-step (steps %s)"
                     % (prefix, row.get("skillIndex"), sorted(steps)))
            step = steps.pop()
            p = row.get(per)
            if p is None or abs(step - float(p)) > EPS:
                findings.append({"skill": row.get("skillIndex"), "series": prefix,
                                 "base": b, "perLv": p, "actualStep": step})
    return findings


def damage_curve(row):
    """Derive the Monster-channel skillDamageRPerLv from the source row's own explicit series.

    Consumer formula (Skill.InitializeData 0x1811FAC50): Base + PerLv*(level-1). The step is
    OLS-anchored at skillDamageRBase, then quantized to float32 (the real protobuf format).
    Every point is validated against the QUANTIZED PerLv with tolerance = 4dp rounding
    (±0.00005) + true float32 ULP at that magnitude. A non-linear series beyond this bound
    aborts. Returns (perLv, {level: value}, max_residual); (None, {}, 0) when no series."""
    import struct
    lvs = {n: row.get("skillDamageRLv%d" % n) for n in range(1, 11)
           if row.get("skillDamageRLv%d" % n) is not None}
    if not lvs:
        return None, {}, 0.0
    b = row.get("skillDamageRBase")
    if b is None:
        fail("damage curve: skill %s carries a Lv series but no skillDamageRBase"
             % row.get("skillIndex"))
    b = float(b)
    if len(lvs) < 2:
        return None, lvs, 0.0
    if 1 in lvs and abs(float(lvs[1]) - b) > 0.00005 + float32_ulp(abs(float(lvs[1]))):
        fail("damage curve: skill %s Lv1=%r != Base=%r beyond 4dp+ULP tolerance"
             % (row.get("skillIndex"), lvs[1], b))
    num = sum((n - 1) * (float(v) - b) for n, v in lvs.items())
    den = sum((n - 1) ** 2 for n in lvs)
    per_raw = num / den if den else 0.0
    per = struct.unpack("f", struct.pack("f", per_raw))[0]
    max_res = 0.0
    for n, v in sorted(lvs.items()):
        expect = b + per * (n - 1)
        res = abs(float(v) - expect)
        tol = 0.00005 + float32_ulp(abs(float(v)))
        max_res = max(max_res, res)
        if res > tol:
            fail("damage curve: skill %s Lv%d=%r residual %.8f > tol %.8f "
                 "(4dp±0.00005 + ULP32 at %.4f) -- non-linear for consumer Base+Per*(N-1)"
                 % (row.get("skillIndex"), n, v, res, tol, abs(float(v))))
    return per, lvs, max_res


def main():
    ap = argparse.ArgumentParser(description="project eight BuffSelect bosses' fighter skills into "
                                             "MonsterSkillTable staging rows (readonly unless --apply)")
    ap.add_argument("--cache", required=True, help="client storage/cache dir (read-only)")
    ap.add_argument("--data", required=True, help="staging tables data dir to read (never master)")
    ap.add_argument("--output", help="TEMP staging output dir (required with --apply)")
    ap.add_argument("--apply", action="store_true", help="write staging outputs (default: check only)")
    args = ap.parse_args()
    if args.apply and not args.output:
        fail("--apply requires --output")
    cache = os.path.abspath(args.cache)
    data = os.path.abspath(args.data)
    if args.output:
        out_dir = os.path.abspath(args.output)
        real_server = os.path.abspath(os.path.join(HERE, "..", "server"))
        for forbidden, label in ((cache, "--cache"), (data, "--data"), (real_server, "the server tree")):
            if os.path.commonpath([forbidden, out_dir]) == forbidden:
                fail("--output must not live inside %s" % label)

    monsters = {int(r["monsterIndex"]): r for r in rows_of(data, "MonsterTable")}
    chars = {int(r["characterIndex"]): r for r in rows_of(data, "CharacterTable")}
    skills = rows_of(data, "SkillTable")
    monster_skills = rows_of(data, "MonsterSkillTable")
    existing = {int(r.get("monsterSkillIndex") or 0): r for r in monster_skills}

    schema = json.load(open(os.path.join(HERE, "..", "server", "tables", "schema.json"),
                            encoding="utf-8"))
    skill_fields = {f["name"].lstrip("_") for f in schema["protos"]["SkillProto"]["fields"]}
    monster_fields = {f["name"].lstrip("_") for f in schema["protos"]["MonsterSkillProto"]["fields"]}
    target = {RENAMES[k]: k for k in RENAMES}
    for f in monster_fields:
        src = next((k for k, v in RENAMES.items() if v == f), None) or f
        if src in skill_fields and src not in RENAMES:
            target[f] = src
    gaps = sorted(f for f in monster_fields if f not in target)

    # canonical fighter per boss + prefab identity + variation state
    for mid, (fighter, _bundle, version) in BOSSES.items():
        m, c = monsters.get(mid), chars.get(int(fighter))
        if not m or not c:
            fail("monster %d or character %s missing in staging data" % (mid, fighter))
        if str(m.get("monsterPrefab", "")).lower() != str(c.get("characterPrefab", "")).lower():
            fail("monster %d prefab %r does not match character %s prefab %r"
                 % (mid, m.get("monsterPrefab"), fighter, c.get("characterPrefab")))
        have = m.get("skillVariationNumber")
        if have not in (None, 0, version):
            fail("monster %d carries skillVariationNumber %r, expected %s -- conflict, abort"
                 % (mid, have, version))

    projected = []       # new rows to add
    already = 0          # rows already present with identical content (idempotent no-op)
    curve_notes = []     # COOLDOWN step != PerLv findings (consumer unproven; reported only)
    damage_derived = []  # rows whose skillDamageRPerLv was rewritten to the real series step
    damage_checked = 0   # damage series validated point-by-point (Monster consumer is linear)
    for mid, (fighter, bundle, version) in BOSSES.items():
        if mid in BLOCKED:
            continue
        canon = [r for r in skills if str(r.get("useFighterIndex")) == fighter]
        if not canon:
            fail("SkillTable carries no rows for fighter %s" % fighter)
        all_versions = {str(r.get("skillIndexString", "")).rsplit("#", 1)[-1] for r in canon}
        if len(all_versions) > 1:
            canon = [r for r in canon
                     if str(r.get("skillIndexString", "")).rsplit("#", 1)[-1] == str(version)]
        elif all_versions != {str(version)}:
            fail("fighter %s carries versions %s, expected only #%d" % (fighter, sorted(all_versions), version))
        alias = ALIASES.get(fighter)
        if alias:
            alias_names = {r.get("skillIndexString")
                           for r in skills if str(r.get("useFighterIndex")) == alias}
            if not alias_names <= {r.get("skillIndexString") for r in canon}:
                fail("alias %s carries names outside canonical %s" % (alias, fighter))
        proven = bundle_skill_names(cache, bundle)
        is_legacy = mid in LEGACY
        for r in sorted(canon, key=lambda x: int(x["skillIndex"])):
            curve_notes += curve_guard(r)
            if is_legacy:
                per, proven_lvs = damage_curve_legacy(r)
            else:
                per, proven_lvs, _mr = damage_curve(r)
            row = {out: r[src] for out, src in target.items() if r.get(src) is not None}
            sid = int(r["skillIndex"])
            base_name = str(r["skillIndexString"]).rsplit("#", 1)[0]
            if base_name not in proven:
                fail("skill %s not proven by typed decode in bundle %s -- abort" % (base_name, bundle))
            if per is not None:
                damage_checked += 1
                per_before = row.get("skillDamageRPerLv")
                if per_before is not None and abs(float(per_before) - per) > EPS:
                    row["skillDamageRPerLv"] = per
                    damage_derived.append(
                        {"monsterSkillIndex": sid, "skillIndexString": r.get("skillIndexString"),
                         "base": r.get("skillDamageRBase"), "perBefore": per_before,
                         "perAfter": per,
                         "provenLevels": {str(n): proven_lvs[n] for n in sorted(proven_lvs)}})
            if sid in PG_ZERO:
                if row.get("monsterSkillIndexString") != PG_ZERO[sid]:
                    fail("PG adaptation skill identity mismatch for %d" % sid)
                row["usePGBase"] = 0.0
            if sid in existing:
                if existing[sid] != row:
                    diff = {k for k in set(existing[sid]) | set(row)
                            if existing[sid].get(k) != row.get(k)}
                    fail("monsterSkillIndex %d exists with DIFFERENT content (keys: %s) -- conflict, abort"
                         % (sid, sorted(diff)))
                already += 1
                continue
            projected.append({"boss": mid, "fighter": fighter, "row": row})

    patches = []
    slot_proposals = {}
    for mid, (fighter, _bundle, version) in BOSSES.items():
        if mid in BLOCKED:
            continue
        base = monsters[mid]
        canon = [r for r in skills if str(r.get("useFighterIndex")) == fighter
                 and str(r.get("skillIndexString", "")).rsplit("#", 1)[-1] == str(version)]
        combos = sorted((r for r in canon if int(r.get("activeSkillType") or 0) == BASE_ATTACK_TYPE),
                        key=lambda r: int(r["skillIndex"]))
        roots = sorted((r for r in canon if int(r.get("activeSkillType") or 0) in ROOT_TYPES),
                       key=lambda r: (int(r.get("activeSkillType") or 0), int(r["skillIndex"])))
        if len(combos) != 4:
            fail("fighter %s carries %d type-%d combos, expected 4" % (fighter, len(combos), BASE_ATTACK_TYPE))
        if len(roots) > MAX_ROOT_SLOTS:
            fail("fighter %s carries %d root skills, cap is %d" % (fighter, len(roots), MAX_ROOT_SLOTS))
        proposal = {"monsterIndex": mid, "skillVariationNumber": version}
        for i, r in enumerate(combos, 1):
            proposal["baseAttack%dIndex" % i] = int(r["skillIndex"])
            proposal["baseAttack%dIndexString" % i] = r["skillIndexString"]
        for i, r in enumerate(roots, 1):
            proposal["skill%dIndex" % i] = int(r["skillIndex"])
            proposal["skill%dIndexString" % i] = r["skillIndexString"]
        slot_proposals[str(mid)] = {"fighter": fighter, "rootCount": len(roots),
                                    "comboCount": len(combos),
                                    "ordering": "(activeSkillType, skillIndex) -- DOCUMENTED ADAPTATION, "
                                                "not recovered; mobile reference rows 530015/530018 fill "
                                                "skill1..12 alphabetically by name instead",
                                    "slots": proposal,
                                    "excluded": "type 6 children, type 9 supports/Tag, type 100 awaken, "
                                                "type 7 counter, type 8 floatbounce -- not auto-included"}
        m = dict(base)
        changed = False
        for k, v in proposal.items():
            if k == "monsterIndex":
                continue
            have = m.get(k)
            if have in (None, 0):
                m[k] = v
                changed = True
            elif have != v:
                fail("monster %d slot %s carries %r, proposal is %r -- conflict, abort"
                     % (mid, k, have, v))
        if changed:
            patches.append(m)

    print("bosses: %d scoped (%d legacy + %d new), %d blocked out of scope: %s" %
          (len(BOSSES), len(LEGACY), len(BOSSES) - len(LEGACY), len(BLOCKED), sorted(BLOCKED)))
    print("new rows: %d | already identical (no-op): %d | row patches: %d"
          % (len(projected), already, len(patches)))
    print("target fields (%d of %d monster proto): %s" % (len(target), len(monster_fields),
                                                          ",".join(sorted(target))))
    print("omitted (%d): %s" % (len(gaps), ",".join(gaps)))
    print("under review 219 (omitted): %s" % ",".join(f for f in REVIEW_219 if f in gaps))
    print("OPEN (npc-fallback-review 225): fallback inits ONE skill (Array.Find); multi-skill is "
          "the 16-slot table loop -- variation alone may be insufficient; no fix claimed")
    if curve_notes:
        print("cooldown curve notes (%d series, step != PerLv -- consumer unproven, source kept): %s"
              % (len(curve_notes), json.dumps(curve_notes[:3])))
    print("damage curve: %d series validated point-by-point; skillDamageRPerLv rewritten to the "
          "real step on %d rows (Monster consumer 0x1811FAC50: Base+Per*(level-1)); levels above "
          "the proven source levels are a declared linear NPC extension"
          % (damage_checked, len(damage_derived)))

    if not args.apply:
        print("check mode: no writes")
        return

    os.makedirs(out_dir, exist_ok=True)
    doc = {"_comment": "rows to append to the project's MonsterSkillTable "
                       "(tools/adapt_buffselect_pc_npc_skills.py)", "rows": [p["row"] for p in projected]}
    patch_doc = {"_comment": "full-row patches for the NPC boss rows (baseAttack/skill slots + "
                             "variation only -- PROPOSAL, apply is coordinator's call)",
                 "rows": patches}
    report = {"inputs": {t: hashlib.md5(open(os.path.join(data, t + ".json"), "rb").read()).hexdigest()
                         for t in ("MonsterTable", "SkillTable", "MonsterSkillTable", "CharacterTable")},
              "sourceIds": {str(mid): {"fighter": f,
                                       "skillIndexes": sorted(int(p["row"]["monsterSkillIndex"])
                                                              for p in projected if p["boss"] == mid),
                                       "skillVariationNumber": v}
                            for mid, (f, _b, v) in BOSSES.items()},
              "aliases": {"20122": "subset of 1106 names, different ids -- canonical 1106 used",
                          "20451": "subset of 1184 names, different ids -- canonical 1184 used"},
              "targetFields": sorted(target), "omittedFields": gaps,
              "review219Omitted": [f for f in REVIEW_219 if f in gaps],
              "idempotentNoops": already,
              "curveNotes": curve_notes,
              "damageChannel": {
                  "consumer": "Skill.InitializeData 0x1811FAC50 (Monster path, npc-skill-value-"
                              "contract.md 228): m_skillDamageRatio = skillDamageRBase + "
                              "skillDamageRPerLv*(level-1); MonsterSkillProto SkillDamageRLv1..10 "
                              "getters are stub 0 -- the Monster never reads the Lv slots",
                  "validatedSeries": damage_checked,
                  "derivedRows": damage_derived,
                  "extension": "levels above the highest proven source level (Lv5 here) are a "
                               "declared LINEAR NPC EXTENSION of the Monster channel, not "
                               "recovered original values; the player path reads the explicit "
                               "Lv1..5 curves instead"},
              "slotProposals": slot_proposals,
              "openSkill7": "the Goenitz AI graph reserves Skill7 by name; slot 7 under the proposed "
                            "ordering maps to a specific skill but the RESOLUTION contract is not "
                            "proven -- no mapping invented, flagged for a future adaptation decision",
              "openQuestion": "SetBattle fallback initializes one Skill (Array.Find); the 16-slot "
                              "table loop is the multi-skill path -- sufficiency of variation alone "
                              "is undecided; staging claims no fix",
              "pgAdaptation": {
                  "reason": "NPC boss graph reserves finisher/ultimate by BBParameter name; "
                            "CharacterBattleController checkPG (b__73_1 @ 0x18115E500) enforces "
                            "PG >= usePG; NPC PG=40, F01Start=300, U01Start=500 -> deadlock",
                  "rows": {str(k): {"name": v, "usePGBase_original": (300.0 if k == 110609 else 500.0),
                                    "usePGBase_adapted": 0.0}
                           for k, v in PG_ZERO.items()},
                  "declared": "NPC ADAPTATION to avoid resource deadlock, NOT a recovered original",
                  "playerSkillTable": "unchanged (player Goenitz still pays 300/500)"},
              "preserved": "all original rows untouched; patched boss rows differ only in the slot "
                           "fields (baseAttack*/skill*) and skillVariationNumber; every projected "
                           "field stays the source's exact value EXCEPT skillDamageRPerLv of the "
                           "damageChannel.derivedRows (rewritten to the series' real step for the "
                           "proven Monster consumer) and usePGBase in pgAdaptation.rows; "
                           "cooldown Base/Per stay source-exact (cooldown "
                           "consumer unproven, m_skillCooltime@0xB8)"}
    for name, d in (("MonsterSkillTable.additions.json", doc), ("MonsterTable.row-patches.json", patch_doc),
                    ("slot-proposals.json", {"_comment": "16-slot layer proposal (root actives 1/2/3 + "
                                                        "baseAttack combos; adaptation ordering)",
                                             "bosses": slot_proposals}),
                    ("report.json", report)):
        open(os.path.join(out_dir, name), "w", encoding="utf-8").write(
            json.dumps(d, ensure_ascii=False, indent=1))
    print("staged %d skill rows + %d row patches (slots+variation) + slot proposals + report in %s"
          % (len(projected), len(patches), out_dir))


if __name__ == "__main__":
    main()
