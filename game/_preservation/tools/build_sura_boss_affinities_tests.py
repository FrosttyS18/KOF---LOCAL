"""Fixture tests (planning + guarded-apply simulation on TEMP copies; no game, no tasklist,
no port, no real table) for build_sura_boss_affinities.py.

Run:  python -I build_sura_boss_affinities_tests.py
"""
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_PY = os.path.join(HERE, "build_sura_boss_affinities.py")
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + ((" :: " + str(detail)) if detail and not cond else ""))


def load_tool():
    spec = importlib.util.spec_from_file_location("build_sura_boss_affinities", TOOL_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_table(tool, tmp, values=None, tier1_only=False):
    values = values or {3800101: 2, 3800102: 3, 3800103: 2, 3800104: 4,
                        3800105: 2, 3800106: 5}
    rows = []
    for rid in sorted(values):
        rows.append({"questEventStageIndex": rid, "questEventIndex": 3800100,
                     "setSynastryBossMonsterValue": values[rid],
                     "setNormalMonsterValue": 0, "setEliteMonsterValue": 0,
                     "dungeonType": 1, "monsterLevel": 40 + rid - 3800101})
    if not tier1_only:
        rows.append({"questEventStageIndex": 3800107, "questEventIndex": 3800100,
                     "setSynastryBossMonsterValue": 7, "dungeonType": 2})
        rows.append({"questEventStageIndex": 810101, "questEventIndex": 810100,
                     "setSynastryBossMonsterValue": 0, "dungeonType": 9})
    path = os.path.join(tmp, "QuestEventStageTable.json")
    with open(path, "wb") as f:
        f.write(tool.canonical_bytes({"_comment": "fixture", "rows": rows}))
    return path


def main():
    tool = load_tool()

    # 1) canonical formatting contract itself
    sample = tool.canonical_bytes({"a": 1, "b": [1, 2]})
    check("canonical_crlf_no_final_nl",
          b"\r\n" in sample and b"\n" not in sample.replace(b"\r\n", b"")
          and not sample.endswith(b"\r\n"))

    # 2) baseline dry-run: exactly the 4 planned fields, nothing else
    with tempfile.TemporaryDirectory() as tmp:
        path = make_table(tool, tmp)
        rc = tool.main(["--table", path])
        check("dryrun_baseline_ready", rc == 0)
        with open(path, "rb") as f:
            after = f.read()
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
        check("dryrun_no_write", state["rows"][2]["setSynastryBossMonsterValue"] == 2)

    # 3) guarded apply: both guards closed -> write, backup, idempotent recheck,
    #    line-diff exactly 4 setSynastryBossMonsterValue lines, other rows byte-preserved
    with tempfile.TemporaryDirectory() as tmp:
        path = make_table(tool, tmp)
        with open(path, "rb") as f:
            before = f.read()
        tool.game_running = lambda: None
        tool.server_port_open = lambda: False
        rc = tool.main(["--table", path, "--apply"])
        check("apply_rc0", rc == 0)
        with open(path, "rb") as f:
            after = f.read()
        old_lines = before.split(b"\r\n")
        new_lines = after.split(b"\r\n")
        changed = [(i, o, n) for i, (o, n) in enumerate(zip(old_lines, new_lines)) if o != n]
        check("apply_line_diff_exactly_4",
              len(changed) == 4 and len(old_lines) == len(new_lines)
              and all(b"setSynastryBossMonsterValue" in n for _, _, n in changed), changed)
        values = {r["questEventStageIndex"]: r["setSynastryBossMonsterValue"]
                  for r in json.loads(after.decode("utf-8"))["rows"]
                  if r["questEventStageIndex"] in tool.TIER1_IDS}
        check("apply_values", values == {3800101: 2, 3800102: 3, 3800103: 4,
                                         3800104: 5, 3800105: 1, 3800106: 6}, values)
        other = [r for r in json.loads(after.decode("utf-8"))["rows"]
                 if r["questEventStageIndex"] in (3800107, 810101)]
        check("apply_other_rows_untouched",
              [r["setSynastryBossMonsterValue"] for r in other] == [7, 0], other)
        backups = [d for d in os.listdir(os.path.dirname(path))]
        # backup lives in system temp, not beside the table
        check("apply_no_side_files", backups == ["QuestEventStageTable.json"], backups)

    # 4) idempotent: re-run on applied state reports applied, exits 0, no write
    with tempfile.TemporaryDirectory() as tmp:
        path = make_table(tool, tmp, values={**tool.BASELINE, **tool.PLAN})
        before = open(path, "rb").read()
        tool.game_running = lambda: None
        tool.server_port_open = lambda: False
        rc = tool.main(["--table", path, "--apply"])
        check("idempotent_rc0", rc == 0)
        check("idempotent_no_rewrite", open(path, "rb").read() == before)

    # 5) refusals: unexpected value, partial application, baseline precondition broken
    for label, values in (
            ("unexpected", {3800101: 2, 3800102: 3, 3800103: 9, 3800104: 4,
                            3800105: 2, 3800106: 5}),
            ("partial", {3800101: 2, 3800102: 3, 3800103: 4, 3800104: 5,
                         3800105: 2, 3800106: 5}),
            ("precondition_101", {3800101: 1, 3800102: 3, 3800103: 2, 3800104: 4,
                                  3800105: 2, 3800106: 5})):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_table(tool, tmp, values=values)
            before = open(path, "rb").read()
            rc = tool.main(["--table", path, "--apply"])
            check("refuse_%s" % label, rc == 2 and open(path, "rb").read() == before)

    # 6) guard refusals: game running / port open -> no write, no backup
    for label, game, port in (("game_open", "ALLSTAR.exe", False),
                              ("port_open", None, True)):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_table(tool, tmp)
            before = open(path, "rb").read()
            tool.game_running = (lambda g: (lambda: g))(game)
            tool.server_port_open = (lambda p: (lambda: p))(port)
            rc = tool.main(["--table", path, "--apply"])
            check("guard_%s_blocks" % label,
                  rc == 2 and open(path, "rb").read() == before)

    # 7) formatting contract enforcement: LF file (wrong endings) refuses at load
    with tempfile.TemporaryDirectory() as tmp:
        path = make_table(tool, tmp)
        raw = open(path, "rb").read().replace(b"\r\n", b"\n")
        with open(path, "wb") as f:
            f.write(raw)
        try:
            tool.main(["--table", path])
            check("roundtrip_refuses_lf", False, "no SystemExit")
        except SystemExit as exc:
            check("roundtrip_refuses_lf", "reproduz byte a byte" in str(exc), exc)

    # 8) duplicated tier-1 row refuses
    with tempfile.TemporaryDirectory() as tmp:
        path = make_table(tool, tmp, tier1_only=True)
        data = json.loads(open(path, "r", encoding="utf-8").read())
        data["rows"].append(dict(data["rows"][0]))
        with open(path, "wb") as f:
            f.write(tool.canonical_bytes(data))
        rc = tool.main(["--table", path])
        check("dup_row_refused", rc == 2)

    # 9) plan is exactly the four root-approved values
    check("plan_exact", tool.PLAN == {3800103: 4, 3800104: 5, 3800105: 1, 3800106: 6})
    check("field_pinned", tool.FIELD == "setSynastryBossMonsterValue")
    check("root_derived_no_user_path", "adcka" not in open(TOOL_PY, "r", encoding="utf-8")
          .read() and 'os.path.dirname(HERE)' in open(TOOL_PY, encoding="utf-8").read())

    # 10) REAL socket guard against an ephemeral local listener: open -> True, closed -> False
    import socket as _socket
    tool2 = load_tool()
    listener = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    live_port = listener.getsockname()[1]
    check("port_open_detected", tool2.server_port_open(live_port) is True)
    listener.close()
    check("port_closed_detected", tool2.server_port_open(live_port) is False)

    # 11) game_running fails CLOSED when enumeration errors or tasklist exits non-zero
    tool3 = load_tool()
    real_run = tool3.subprocess.run

    def failing_run(*a, **k):
        raise OSError("boom")

    tool3.subprocess.run = failing_run
    try:
        tool3.game_running()
        check("enum_error_refuses", False, "no SystemExit")
    except SystemExit as exc:
        check("enum_error_refuses", "enumerar" in str(exc), exc)

    def bad_rc_run(*a, **k):
        import types as _types
        return _types.SimpleNamespace(returncode=1, stdout=b"")

    tool3.subprocess.run = bad_rc_run
    try:
        tool3.game_running()
        check("tasklist_bad_rc_refuses", False, "no SystemExit")
    except SystemExit as exc:
        check("tasklist_bad_rc_refuses", "tasklist falhou" in str(exc), exc)
    finally:
        tool3.subprocess.run = real_run

    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
