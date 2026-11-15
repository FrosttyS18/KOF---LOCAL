"""Adapt the Prove dungeon card visibility for the PC event-dungeon selector (v1024+).

Scope: ModeTable.json only, row modeIndex 109 / modeType 109 (Mode_Prove), field
displayContentsCondition. Native behaviour (native-analysis/prove-entry-route.md rev3):
Scene_EventDungeonSelector -> Controller_EventDungeonSelector.CollectModeData feeds
ModeTable.GetOpenedModeData the fixed template array [108, 109, 110] (blob 0x958425 in
global-metadata.dat, unique in the binary), and GetOpenedModeData keeps a mode card only
when ModeProto._displayContentsCondition@0x50 > 0. Both the reconstructed PC master and
the mobile reference source carry 0 for row 109, so the native Prove card never reaches
the selector UI. This helper flips that single field from 0 (original) to 1 (adapted;
the value every already-visible card of that selector uses: 108/110), which is the
minimal reversible data-level change that lets the native card render. Everything else
is preserved: the file is rewritten only when the value actually changes, with its
original CRLF/LF style and trailing-newline shape, so all other rows and fields stay
byte-identical and a second run is a byte-level no-op. A displayContentsCondition value
other than 0/1, a missing row 109, a missing field, more than one matching row, or a
modeIndex/modeType divergence aborts before a single byte is written.

Card click navigation (modeType 109 -> SceneType 88) is explicitly UNPROVEN: this helper
only restores visibility, it does not touch scenes, triggers, schedules or the binary.

preflight(rows) validates the table shape; adapt_current_master(data) mutates the loaded
ModeTable document in place and is the reusable entry point for the import pipeline. CLI:
--data DIR (tables data dir), --check (validate and report, write nothing).
"""
import argparse
import json
import os
import sys

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "server", "tables", "data")
TABLE = "ModeTable.json"
PROVE_MODE_INDEX = 109
PROVE_MODE_TYPE = 109
FIELD = "displayContentsCondition"
ORIGINAL_VALUE = 0
ADAPTED_VALUE = 1
ACCEPTED_VALUES = (ORIGINAL_VALUE, ADAPTED_VALUE)


class AdaptationError(RuntimeError):
    """Raised when ModeTable diverges from the known real table shape."""


def preflight(rows):
    """Validate the Prove row and return {'index', 'value', 'state'}.

    Exactly one row must have modeIndex 109 and modeType 109 (the same row), with an
    integer displayContentsCondition of 0 (original) or 1 (adapted). Anything else --
    missing row, missing field, unknown value such as 2/3, duplicates, index/type
    divergence -- raises AdaptationError.
    """
    if not isinstance(rows, list):
        raise AdaptationError("ModeTable rows is not a list")
    by_index = [i for i, r in enumerate(rows)
                if isinstance(r, dict) and r.get("modeIndex") == PROVE_MODE_INDEX]
    by_type = [i for i, r in enumerate(rows)
               if isinstance(r, dict) and r.get("modeType") == PROVE_MODE_TYPE]
    if not by_index and not by_type:
        raise AdaptationError("no ModeTable row with modeIndex/modeType %d (Mode_Prove missing)"
                              % PROVE_MODE_INDEX)
    if by_index != by_type:
        raise AdaptationError("modeIndex %d and modeType %d rows diverge: %s vs %s"
                              % (PROVE_MODE_INDEX, PROVE_MODE_TYPE, by_index, by_type))
    if len(by_index) != 1:
        raise AdaptationError("expected exactly one Mode_Prove row, found %d at %s"
                              % (len(by_index), by_index))
    i = by_index[0]
    row = rows[i]
    if FIELD not in row:
        raise AdaptationError("Mode_Prove row has no %s field" % FIELD)
    value = row[FIELD]
    if not isinstance(value, int) or isinstance(value, bool):
        raise AdaptationError("Mode_Prove %s is not an integer: %r" % (FIELD, value))
    if value not in ACCEPTED_VALUES:
        raise AdaptationError("Mode_Prove %s is %r; only %d (original) or %d (adapted) are "
                              "accepted" % (FIELD, value, ORIGINAL_VALUE, ADAPTED_VALUE))
    return {"index": i, "value": value,
            "state": "original" if value == ORIGINAL_VALUE else "adapted"}


def adapt_current_master(data):
    """Flip the Prove card displayContentsCondition 0 -> 1 in a loaded ModeTable document.

    Mutates data in place; returns 'adapted' when the field changed and 'noop' when it was
    already the adapted value. Raises AdaptationError through preflight on any divergence.
    Never writes files.
    """
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise AdaptationError("ModeTable document has no rows list")
    info = preflight(data["rows"])
    if info["state"] == "adapted":
        return "noop"
    data["rows"][info["index"]][FIELD] = ADAPTED_VALUE
    return "adapted"


def _dump_like(raw, data):
    """Serialize data with the byte shape of raw (indent 1, original line ending and
    trailing-newline presence)."""
    text = json.dumps(data, ensure_ascii=False, indent=1)
    eol = "\r\n" if raw.count(b"\r\n") * 2 > raw.count(b"\n") else "\n"
    text = text.replace("\n", eol)
    if raw.endswith(b"\n") and not text.endswith(eol):
        text += eol
    return text.encode("utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="flip Mode_Prove displayContentsCondition 0->1 (visibility only)")
    parser.add_argument("--data", default=DATA, help="tables data dir (default: project master)")
    parser.add_argument("--check", action="store_true", help="preflight only; write nothing")
    args = parser.parse_args()
    path = os.path.join(args.data, TABLE)
    if not os.path.exists(path):
        print("missing table file: %s" % path, file=sys.stderr)
        return 1
    raw = open(path, "rb").read()
    try:
        data = json.loads(raw.decode("utf-8"))
        info = preflight(data["rows"])
    except (ValueError, KeyError, AdaptationError) as exc:
        print("preflight failed: %s" % exc, file=sys.stderr)
        return 1
    print("Mode_Prove row %d: %s=%d (%s)" % (info["index"], FIELD, info["value"], info["state"]))
    if args.check:
        print("check only; nothing written")
        return 0
    try:
        status = adapt_current_master(data)
    except AdaptationError as exc:
        print("adapt failed: %s" % exc, file=sys.stderr)
        return 1
    if status == "noop":
        print("already adapted; nothing written")
        return 0
    out = _dump_like(raw, data)
    with open(path, "wb") as fh:
        fh.write(out)
    print("adapted: %s %s %d->%d (%d bytes)" % (TABLE, FIELD, ORIGINAL_VALUE, ADAPTED_VALUE,
                                                len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
