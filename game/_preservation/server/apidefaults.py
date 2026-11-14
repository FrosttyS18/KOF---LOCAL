"""Build fully-populated default JSON objects for the game's API classes (Newtonsoft field names).

Responses with missing object fields deserialize as null, and the client's Parse_* code dereferences them
without checks (e.g. Parse_PlayerProfile). default(cls) gives every field a safe value:
numbers 0, bool false, string "", lists/RepeatedField/arrays [], maps {}, enums 0, nested classes filled
recursively (depth-limited), unknown types null. Built from api_types.json (tools/api_types.py).
"""
import json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
_T = json.load(open(os.path.join(HERE, "api_types.json"), encoding="utf-8"))
CLASSES = _T["classes"]
ENUMS = set(_T["enums"])

NUM = {"int", "long", "short", "byte", "sbyte", "uint", "ulong", "ushort", "float", "double", "decimal",
       "Int32", "Int64", "Single", "Double"}
NULLABLE_SKIP = {"ByteString", "object", "Object", "JSONNode", "JObject", "Type", "Action"}


def value_for(t, depth):
    t = t.strip()
    if t in NUM:
        return 0
    if t in ("bool", "Boolean"):
        return False
    if t in ("string", "String"):
        return ""
    if t.endswith("[]") or re.match(r"(RepeatedField|List|IList|IEnumerable|HashSet|Queue|Stack)<", t):
        return []
    if re.match(r"(MapField|Dictionary|IDictionary|SortedDictionary)<", t):
        return {}
    if t == "DateTime":
        return "2000-01-01T00:00:00"
    if t in ENUMS or t.split(".")[-1] in ENUMS:
        return 0
    if t in NULLABLE_SKIP or "<" in t:
        return None
    name = t.split(".")[-1]
    if name in CLASSES and depth > 0:
        return default(name, depth - 1)
    return None


def default(cls, depth=3, **overrides):
    out = {}
    for f, t in CLASSES.get(cls, []):
        out[f] = value_for(t, depth)
    out.update(overrides)
    return out
