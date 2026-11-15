"""Candidate importer for the Sura UI row of ResourcePrefabTable (read-only by default).

Behaviour contract, checked against the PC client's native ActionUnitUILoad.OnExecute
(RVA 0x12FA340) and ResourcePrefabTable.FindResourcePrefab (RVA 0xD4BA30):
- Sura trigger prefabs (SuraDungeon_02/04/06/08/10/12) carry ActionUnitUILoad with
  m_resourcesIndexString = "UI.Sura.UIUnit.LimitSliderBar" (string only, no numeric id),
  so the client must resolve that string against resourcePrefabIndexString rows.
- The reference server table has the row at index 1, which collides with the master
  Break row; the importer therefore re-indexes to max(existing)+1 and never touches
  existing rows (append-only, byte-preserving round-trip format guard).

Paths: master/cache default from this script's repo location (game/_preservation/tools);
the mobile reference table is outside the repo and must always be passed with --ref.
When the repo layout is not detected every path must be given explicitly.

Guards (all run before any write; any failure exits 2 without touching the master):
master parse/shape/round-trip, per-row id validation (int, not bool, unique), reference
row selection and shape, cache manifest+file presence, and a deep cache read of the
target bundle via tools/read_unity_serialized (no silent skips: a missing reader or
bundle is a failure). Exit codes: 0 = ok (added / already adapted / dry-run clean).
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import sys

TARGET_STRING = "UI.Sura.UIUnit.LimitSliderBar"
EXPECTED_PREFAB = "Prefabs/UI_Data/UI_Unit/UIUnit_LimitSliderBar"
BUNDLE = "prefabs_ui_data_ui_unit_uiunit_limitsliderbar"
ATLAS = "prefabs_ui_data_ui_atlassheet_atlassheet_eventstagefever"


def repo_root():
    """The repo root when this script sits in game/_preservation/tools; else None."""
    here = pathlib.Path(__file__).resolve().parent
    for base in (here, *here.parents):
        if (base / "game" / "_preservation" / "tools").is_dir():
            return base
    return None


def default_paths():
    root = repo_root()
    if root is None:
        return None
    return {
        "master": root / "game" / "_preservation" / "server" / "tables" / "data" / "ResourcePrefabTable.json",
        "cache": root / "game" / "storage" / "cache",
    }


def load_json(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return json.load(fh)


def roundtrip_ok(parsed, raw):
    text = json.dumps(parsed, indent=1, ensure_ascii=False)
    text = text.replace("\n", "\r\n")
    return text.encode("utf-8") == raw


def id_problems(rows, label):
    """Hard validation of the table's ids: every index an int (bool rejected), unique."""
    problems = []
    seen = {}
    for pos, row in enumerate(rows):
        if not isinstance(row, dict):
            problems.append(f"{label} row {pos}: not an object")
            continue
        idx = row.get("resourcePrefabIndex")
        if isinstance(idx, bool) or not isinstance(idx, int):
            problems.append(f"{label} row {pos}: resourcePrefabIndex {idx!r} is not an int")
            continue
        if idx in seen:
            problems.append(f"{label} index {idx} duplicated (rows {seen[idx]} and {pos})")
        seen[idx] = pos
        for field in ("resourcePrefabIndexString", "resourcePrefab"):
            if not isinstance(row.get(field), str) or not row.get(field):
                problems.append(f"{label} row {pos}: {field} is not a non-empty string")
    return problems


def cache_report(cache_root):
    root = pathlib.Path(cache_root)
    info = root / "assetbundles.info"
    problems = []
    names = set()
    if not info.is_file():
        problems.append(f"missing {info}")
    else:
        for chunk in re.findall(rb"[\x20-\x7e]{4,}", info.read_bytes()):
            names.add(chunk.decode().rstrip())
    files = {}
    for bundle in (BUNDLE, ATLAS):
        present = bundle in names
        digest = hashlib.md5(bundle.encode()).hexdigest()
        disk = (root / "assetbundles" / digest).is_file()
        files[bundle] = {"inManifest": present, "onDisk": disk}
        if not (present and disk):
            problems.append(f"cache bundle {bundle} present={present} onDisk={disk}")
    return files, problems


def deep_cache_check(cache_root, problems):
    """Read the target bundle with the project's own UnityFS reader. There is no skip
    path: a missing reader or bundle, or a bundle that does not actually carry the
    UIUnit_LimitSliderBar prefab, is a guard failure."""
    path = pathlib.Path(cache_root) / "assetbundles" / hashlib.md5(BUNDLE.encode()).hexdigest()
    if not path.is_file():
        problems.append(f"bundle file not present under given cache root: {path}")
        return {"bundle": str(path)}
    here = pathlib.Path(__file__).resolve().parent
    candidates = [here / "read_unity_serialized.py"]
    root = repo_root()
    if root:
        candidates.append(root / "game" / "_preservation" / "tools" / "read_unity_serialized.py")
    cache_repo = pathlib.Path(cache_root).resolve().parents[2] if len(pathlib.Path(cache_root).resolve().parents) > 2 else None
    if cache_repo and (cache_repo / "game" / "_preservation" / "tools").is_dir():
        candidates.append(cache_repo / "game" / "_preservation" / "tools" / "read_unity_serialized.py")
    loader = next((c for c in candidates if c.is_file()), None)
    if loader is None:
        problems.append("read_unity_serialized.py not found next to this script or in the repo tools")
        return {"bundle": str(path), "reader": None}
    import importlib.util

    spec = importlib.util.spec_from_file_location("rufs_sura_ui", loader)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        data, gos, mbs, _trs, info = mod.index_bundle(str(path))
    except Exception as exc:
        problems.append(f"index_bundle failed on {BUNDLE}: {exc}")
        return {"reader": str(loader)}
    roots = sorted(g["name"] for g in gos.values() if g["name"] == "UIUnit_LimitSliderBar")
    if not roots:
        problems.append(f"bundle {BUNDLE} has no UIUnit_LimitSliderBar GameObject root")
    return {
        "reader": str(loader),
        "bundleObjects": info.get("gos"),
        "bundleMonoBehaviours": info.get("mbs"),
        "limitSliderBarRoots": len(roots),
        "byteHits": data.count(b"UIUnit_LimitSliderBar"),
    }


def run(master, ref, cache_root, write):
    report = {"master": str(master), "write": write, "status": None, "problems": []}
    mpath = pathlib.Path(master)
    if not mpath.is_file():
        report["problems"].append(f"missing master {mpath}")
        return report, 2
    raw = mpath.read_bytes()
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        report["problems"].append(f"master unparseable: {exc}")
        return report, 2
    rows = parsed.get("rows") if isinstance(parsed, dict) else None
    if not isinstance(rows, list):
        report["problems"].append("master has no rows list")
        return report, 2
    report["problems"].extend(id_problems(rows, "master"))
    if report["problems"]:
        return report, 2

    rpath = pathlib.Path(ref)
    if not rpath.is_file():
        report["problems"].append(f"missing reference {rpath}")
        return report, 2
    try:
        ref_parsed = load_json(rpath)
    except Exception as exc:
        report["problems"].append(f"reference unparseable: {exc}")
        return report, 2
    ref_rows = ref_parsed.get("baris") if isinstance(ref_parsed, dict) else None
    if not isinstance(ref_rows, list):
        report["problems"].append("reference has no baris list")
        return report, 2
    ref_hits = [r for r in ref_rows if isinstance(r, dict) and r.get("resourcePrefabIndexString") == TARGET_STRING]
    if len(ref_hits) != 1:
        report["problems"].append(f"reference rows for {TARGET_STRING}: {len(ref_hits)} (want 1)")
        return report, 2
    ref_row = ref_hits[0]
    report["referenceRow"] = ref_row
    report["problems"].extend(id_problems([ref_row], "reference"))
    if ref_row.get("resourcePrefab") != EXPECTED_PREFAB:
        report["problems"].append("reference prefab path diverges from expectation")

    existing = [r for r in rows if r.get("resourcePrefabIndexString") == TARGET_STRING]
    report["cache"], cache_problems = cache_report(cache_root)
    report["problems"].extend(cache_problems)
    report["deepCache"] = deep_cache_check(cache_root, report["problems"])

    if existing:
        report["status"] = "already-adapted"
        report["existingRow"] = existing[0]
        if len(existing) > 1:
            report["problems"].append("target string appears more than once")
        if existing[0].get("resourcePrefab") != EXPECTED_PREFAB:
            report["problems"].append("existing target row prefab path diverges")
        return report, 2 if report["problems"] else 0

    if not roundtrip_ok(parsed, raw):
        report["problems"].append(
            "master does not round-trip as json.dumps(indent=1, CRLF, no trailing newline); "
            "refusing to touch unexpected format"
        )
    if report["problems"]:
        return report, 2

    indexes = [r["resourcePrefabIndex"] for r in rows]
    new_index = (max(indexes) + 1) if indexes else 1
    if new_index in indexes:
        report["problems"].append(f"computed index {new_index} already used")

    new_row = {
        "resourcePrefabIndex": new_index,
        "resourcePrefabIndexString": TARGET_STRING,
        "resourcePrefab": EXPECTED_PREFAB,
    }
    report["plannedRow"] = new_row
    report["reindexNote"] = (
        f"reference index {ref_row.get('resourcePrefabIndex')} collides with master Break row; "
        f"re-indexed to next free {new_index}; resolution is by indexString, index value only needs uniqueness"
    )
    if report["problems"]:
        return report, 2
    if not write:
        report["status"] = "dry-run-clean"
        return report, 0

    parsed["rows"] = rows + [new_row]
    text = json.dumps(parsed, indent=1, ensure_ascii=False).replace("\n", "\r\n")
    tmp = mpath.with_suffix(".json.tmp-sura-ui")
    tmp.write_bytes(text.encode("utf-8"))
    os.replace(tmp, mpath)

    recheck = json.loads(mpath.read_bytes().decode("utf-8"))
    got = [r for r in recheck["rows"] if r.get("resourcePrefabIndexString") == TARGET_STRING]
    preserved = recheck["rows"][:-1] == rows
    if len(recheck["rows"]) != len(rows) + 1 or len(got) != 1 or not preserved:
        report["problems"].append("post-write verification failed; master left in written state")
        return report, 2
    report["status"] = "written"
    return report, 0


def main(argv=None):
    defaults = default_paths()
    here = pathlib.Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--master", default=str(defaults["master"]) if defaults else None,
                    help="master ResourcePrefabTable.json (default: repo layout)")
    ap.add_argument("--ref", default=None,
                    help="mobile reference ResourcePrefabTable.json (required; outside the repo)")
    ap.add_argument("--cache", default=str(defaults["cache"]) if defaults else None,
                    help="client assetbundles cache root (default: repo layout)")
    ap.add_argument("--write", action="store_true", help="append the row (default is read-only)")
    args = ap.parse_args(argv)
    missing = [name for name in ("master", "ref", "cache") if not getattr(args, name)]
    if missing:
        ap.error("missing required arguments (no repo layout detected): " +
                 ", ".join("--" + m for m in missing))
    report, code = run(args.master, args.ref, args.cache, args.write)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return code


if __name__ == "__main__":
    sys.exit(main())
