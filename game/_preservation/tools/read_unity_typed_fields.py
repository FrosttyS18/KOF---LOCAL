"""Read-only canonical SerializedFile v22 TYPE-TREE decoder for inspecting local client assets
(UI tooltip work), layered on tools/read_unityfs.py and tools/read_unity_serialized.py (imported
untouched; the metadata walk below mirrors read_unity_serialized._serialized_type field by field
but KEEPS the type trees that module discards). Nothing here feeds gameapi; it is an analysis
tool for asset bundles in game/storage/cache (always opened read-only).

Format contract (client bundles: SerializedFile v22, Unity 2021.3.12f1, platform 19). Each
SerializedType: classID i32, isStripped u8, scriptTypeIndex i16, scriptID 16B (classID 114 only),
oldTypeHash 16B, then with enableTypeTree the blob [nodeCount i32][stringBufferSize i32]
[nodeCount x 32B nodes][stringBuffer] followed by typeDependencies i32[count]. A v22 node is
EXACTLY 32 bytes: version u16, level u8, typeFlags u8, typeStrOffset u32, nameStrOffset u32,
byteSize i32, index i32, metaFlag u32, refTypeHash u64. String offsets with the high bit
(0x80000000) index the build-time COMMON string table; every other offset is a strz position in
the type's own stringBuffer.

Decoding semantics (matching AssetStudio's TypeTreeHelper/SerializedFile readers, which are the
primary format reference: https://raw.githubusercontent.com/Perfare/AssetStudio/master/AssetStudio/SerializedFile.cs
TypeTreeBlobRead, .../TypeTreeHelper.cs ReadValue, .../CommonString.cs):
- alignment is ONLY "after a node whose metaFlag has 0x4000", always to 4; arrays and maps also
  honor their Array child's flag; there is NEVER 8-byte alignment (an i64 inside a PPtr sits at
  +4 of a 4-aligned base, so a PPtr occupies exactly 12 bytes);
- "string" = i32 length + UTF-8 bytes + align 4, and ALL of its tree children (the
  Array/size/char template) are skipped;
- any node whose next node is type "Array" is an array: i32 count, then the count-fold repeat of
  the element template starting right after the size node's subtree (template bounds are
  depth-derived from node levels);
- "map" = i32 count + pair structs; "TypelessData" = i32 size + raw bytes, children skipped;
  "PPtr<...>"/"PPtr<$...>" = 12 raw bytes emitted as m_FileID/m_PathID records;
- every other node with children is a struct; a leaf with an unknown type raises.

decode_object(body, nodes) returns flat records [{"path", "value", "offset", "size", "type"}]
plus the consumed byte count, or raises. Paths drop the ROOT node's own name (the "Base" node)
but keep nesting ("m_LocalPosition.x"); array elements are ".Array.data[i]"; a record's offset is
body-relative and its size excludes trailing alignment padding. The caller validates consumed
against the object table's byteSize. The COMMON table below is embedded verbatim as public
format data so the tool runs offline; it is not copyrighted expression but a build-time constant
table (offset -> string) reproduced from the referenced CommonString.cs.

usage: read_unity_typed_fields.py --bundle PATH --inspect-target FIELD_NAME
"""
import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import read_unityfs
import read_unity_serialized as U

ALIGN_FLAG = 0x4000

COMMON_STRINGS = {
    0: "AABB", 5: "AnimationClip", 19: "AnimationCurve", 34: "AnimationState", 49: "Array",
    55: "Base", 60: "BitField", 69: "bitset", 76: "bool", 81: "char", 86: "ColorRGBA",
    96: "Component", 106: "data", 111: "deque", 117: "double", 124: "dynamic_array",
    138: "FastPropertyName", 155: "first", 161: "float", 167: "Font", 172: "GameObject",
    183: "Generic Mono", 196: "GradientNEW", 208: "GUID", 213: "GUIStyle", 222: "int",
    226: "list", 231: "long long", 241: "map", 245: "Matrix4x4f", 256: "MdFour",
    263: "MonoBehaviour", 277: "MonoScript", 288: "m_ByteSize", 299: "m_Curve",
    307: "m_EditorClassIdentifier", 331: "m_EditorHideFlags", 349: "m_Enabled",
    359: "m_ExtensionPtr", 374: "m_GameObject", 387: "m_Index", 395: "m_IsArray",
    405: "m_IsStatic", 416: "m_MetaFlag", 427: "m_Name", 434: "m_ObjectHideFlags",
    452: "m_PrefabInternal", 469: "m_PrefabParentObject", 490: "m_Script",
    499: "m_StaticEditorFlags", 519: "m_Type", 526: "m_Version", 536: "Object", 543: "pair",
    548: "PPtr<Component>", 564: "PPtr<GameObject>", 581: "PPtr<Material>",
    596: "PPtr<MonoBehaviour>", 616: "PPtr<MonoScript>", 633: "PPtr<Object>",
    646: "PPtr<Prefab>", 659: "PPtr<Sprite>", 672: "PPtr<TextAsset>", 688: "PPtr<Texture>",
    702: "PPtr<Texture2D>", 718: "PPtr<Transform>", 734: "Prefab", 741: "Quaternionf",
    753: "Rectf", 759: "RectInt", 767: "RectOffset", 778: "second", 785: "set", 789: "short",
    795: "size", 800: "SInt16", 807: "SInt32", 814: "SInt64", 821: "SInt8", 827: "staticvector",
    840: "string", 847: "TextAsset", 857: "TextMesh", 866: "Texture", 874: "Texture2D",
    884: "Transform", 894: "TypelessData", 907: "UInt16", 914: "UInt32", 921: "UInt64",
    928: "UInt8", 934: "unsigned int", 947: "unsigned long long", 966: "unsigned short",
    981: "vector", 988: "Vector2f", 997: "Vector3f", 1006: "Vector4f",
    1015: "m_ScriptingClassIdentifier", 1042: "Gradient", 1051: "Type*", 1057: "int2_storage",
    1070: "int3_storage", 1083: "BoundsInt", 1093: "m_CorrespondingSourceObject",
    1121: "m_PrefabInstance", 1138: "m_PrefabAsset", 1152: "FileSize", 1161: "Hash128",
}

_PRIMITIVES = {
    "SInt8": ("<b", 1), "UInt8": ("<B", 1), "char": ("<H", 2),
    "short": ("<h", 2), "SInt16": ("<h", 2),
    "UInt16": ("<H", 2), "unsigned short": ("<H", 2),
    "int": ("<i", 4), "SInt32": ("<i", 4),
    "UInt32": ("<I", 4), "unsigned int": ("<I", 4), "Type*": ("<I", 4),
    "long long": ("<q", 8), "SInt64": ("<q", 8),
    "UInt64": ("<Q", 8), "unsigned long long": ("<Q", 8), "FileSize": ("<Q", 8),
    "float": ("<f", 4), "double": ("<d", 8),
}

_INT_NAMES = ("int", "SInt32", "UInt32", "unsigned int")


class TypeTreeDecodeError(ValueError):
    """Raised when a body cannot be decoded against its type tree: out-of-bounds read,
    implausible count, or a node type this decoder does not support."""


def _tree_string(value, string_buffer):
    if value & 0x80000000:
        key = value & 0x7FFFFFFF
        if key not in COMMON_STRINGS:
            raise ValueError("common string offset %d is not in the build-time table" % key)
        return COMMON_STRINGS[key]
    end = string_buffer.find(b"\0", value)
    if end < 0:
        raise ValueError("string offset %d has no terminator in the type's buffer" % value)
    return string_buffer[value:end].decode("utf-8", "replace")


def _parse_type_nodes(r):
    """[nodeCount i32][stringBufferSize i32][nodes 32B][stringBuffer] -> (nodes, buffer);
    the caller continues with the typeDependencies count right after the buffer."""
    count = r.i32()
    string_size = r.i32()
    if not 0 <= count <= 100000 or not 0 <= string_size <= 16 * 1024 * 1024:
        raise ValueError(f"implausible typetree counts nodes={count} strings={string_size}")
    raw = r.d[r.p:r.p + count * 32]
    if len(raw) != count * 32:
        raise ValueError("type tree node block is truncated")
    r.p += count * 32
    string_buffer = r.d[r.p:r.p + string_size]
    if len(string_buffer) != string_size:
        raise ValueError("type tree string buffer is truncated")
    r.p += string_size
    nodes = []
    prev_level = -1
    for i in range(count):
        base = i * 32
        version, level, type_flags = struct.unpack_from("<HBB", raw, base)
        type_str, name_str, byte_size, index, meta_flag, ref_hash = struct.unpack_from(
            "<IIiiIQ", raw, base + 4)
        if level > prev_level + 1:
            raise ValueError("node %d level %d skips a level after %d" % (i, level, prev_level))
        prev_level = level
        nodes.append({"version": version, "level": level, "typeFlags": type_flags,
                      "type": _tree_string(type_str, string_buffer),
                      "name": _tree_string(name_str, string_buffer),
                      "byteSize": byte_size, "index": index, "metaFlag": meta_flag,
                      "refTypeHash": ref_hash})
    return nodes, string_buffer


def _serialized_type_typed(r, enable_type_tree, slot):
    """Mirrors read_unity_serialized._serialized_type field order exactly, but preserves the
    type tree (nodes, string buffer) and the dependency list instead of skipping them."""
    class_id = r.i32()
    stripped = r.u8()
    script_index = r.i16()
    script_id = None
    if class_id == 114:
        script_id = r.d[r.p:r.p + 16].hex()
        r.p += 16
    old_type_hash = r.d[r.p:r.p + 16].hex()
    r.p += 16
    nodes, string_buffer, dependencies = [], b"", []
    if enable_type_tree:
        nodes, string_buffer = _parse_type_nodes(r)
        dep_count = r.i32()
        if not 0 <= dep_count <= 4096:
            raise ValueError(f"type {class_id}: implausible dependency count {dep_count}")
        dependencies = [r.i32() for _ in range(dep_count)]
    return {"slot": slot, "classID": class_id, "stripped": stripped,
            "scriptIndex": script_index, "scriptID": script_id,
            "oldTypeHash": old_type_hash, "nodes": nodes,
            "stringBufferSize": len(string_buffer), "dependencies": dependencies}


def load_typed_bundle(path):
    """Canonical parse keeping type trees: {"stream", "rows", "types", "info"}. stream is the
    decompressed node stream; rows maps pathID -> {"offset", "size", "typeSlot", "classID"}
    (offset absolute in the stream); types is the per-slot SerializedType list with nodes.
    Same validations as read_unity_serialized.load_bundle (v22, little-endian, fileSize ==
    node size, metadata bounds, sane counts, unique pathIDs, objects inside the node, exact
    metadata end) plus a non-empty type tree for every slot."""
    raw = open(path, "rb").read()
    version = struct.unpack_from(">I", raw, 8)[0]
    off = 12
    for _ in range(2):
        off = raw.index(b"\0", off) + 1
    _, compressed, uncompressed, flags = struct.unpack_from(">QIII", raw, off)
    off += 20
    if version >= 7:
        off = (off + 15) // 16 * 16
    metadata = read_unityfs.decode(raw[-compressed:] if flags & 128 else raw[off:off + compressed],
                                   uncompressed, flags & 63)
    data = read_unityfs.load(path)
    block_count = struct.unpack_from(">I", metadata, 16)[0]
    if block_count > 10000:
        raise ValueError(f"implausible block count {block_count}")
    node_count = struct.unpack_from(">i", metadata, 20 + block_count * 10)[0]
    if not 0 < node_count <= 10000:
        raise ValueError(f"implausible node count {node_count}")
    np_ = 20 + block_count * 10 + 4
    node = None
    for _ in range(node_count):
        n_off, n_size = struct.unpack_from(">qq", metadata, np_)
        name_end = metadata.index(b"\0", np_ + 20)
        nm = metadata[np_ + 20:name_end].decode()
        np_ = name_end + 1
        if not nm.endswith((".resS", ".resource")):
            node = (n_off, n_size, nm)
            break
    if node is None:
        raise ValueError("no serialized-file node in bundle")
    n_off, n_size, nm = node

    file_version = struct.unpack_from(">I", data, n_off + 8)[0]
    endian = data[n_off + 16]
    metadata_size = struct.unpack_from(">I", data, n_off + 20)[0]
    file_size = struct.unpack_from(">q", data, n_off + 24)[0]
    data_offset = struct.unpack_from(">q", data, n_off + 32)[0]
    if file_version != 22:
        raise ValueError(f"expected SerializedFile v22, got {file_version}")
    if endian != 0:
        raise ValueError(f"expected little-endian marker, got {endian}")
    if file_size != n_size:
        raise ValueError(f"fileSize {file_size} != node size {n_size}")
    if not 48 <= metadata_size <= data_offset <= n_size:
        raise ValueError(f"metadata bounds broken: {metadata_size}/{data_offset}/{n_size}")

    m = U._Reader(data, n_off + 48)
    editor_version = m.strz()
    platform = m.i32()
    enable_type_tree = m.u8()
    if not enable_type_tree:
        raise ValueError("bundle carries no type trees; typed decode is impossible")
    type_count = m.i32()
    if not 0 < type_count <= 4096:
        raise ValueError(f"implausible type count {type_count}")
    types = [_serialized_type_typed(m, True, slot) for slot in range(type_count)]
    for t in types:
        if not t["nodes"]:
            raise ValueError(f"type slot {t['slot']} (classID {t['classID']}) has no nodes")

    object_count = m.i32()
    if not 0 < object_count <= 1000000:
        raise ValueError(f"implausible object count {object_count}")
    rows = {}
    for _ in range(object_count):
        m.align()
        pid = m.i64()
        byte_start = m.i64()
        byte_size = m.u32()
        type_id = m.i32()
        if pid in rows:
            raise ValueError(f"duplicate pathID {pid}")
        if byte_start < 0 or byte_size <= 0:
            raise ValueError(f"object {pid:016x}: bad blob bounds start={byte_start} size={byte_size}")
        abs_off = n_off + data_offset + byte_start
        if abs_off + byte_size > n_off + n_size:
            raise ValueError(f"object {pid:016x} out of file bounds")
        if not 0 <= type_id < type_count:
            raise ValueError(f"object {pid:016x} typeID {type_id} outside type table")
        rows[pid] = {"offset": abs_off, "size": byte_size, "typeSlot": type_id,
                     "classID": types[type_id]["classID"]}
    table_end = m.p

    script_count = m.i32()
    if not 0 <= script_count <= 1000000:
        raise ValueError(f"implausible script count {script_count}")
    for _ in range(script_count):
        m.i32()
        m.align()
        m.i64()
    external_count = m.i32()
    if not 0 <= external_count <= 1000000:
        raise ValueError(f"implausible external count {external_count}")
    externals = []
    for _ in range(external_count):
        m.strz()
        m.p += 16
        m.i32()
        externals.append(m.strz())
    ref_count = m.i32()
    if not 0 <= ref_count <= 4096:
        raise ValueError(f"implausible refType count {ref_count}")
    for _ in range(ref_count):
        _serialized_type_typed(m, enable_type_tree, -1)
    user_info = m.strz()
    if m.p != n_off + 48 + metadata_size:
        raise ValueError(f"metadata end {m.p - n_off} != 48+metadataSize {48 + metadata_size}")
    if not 48 <= table_end <= data_offset:
        raise ValueError(f"object table end {table_end} outside metadata region")

    info = {"node": nm, "editor": editor_version, "platform": platform,
            "fileVersion": file_version, "metadataSize": metadata_size, "fileSize": file_size,
            "dataOffset": data_offset, "typeCount": type_count, "objectCount": object_count,
            "tableEnd": table_end, "userInfo": user_info, "externals": externals,
            "refTypeCount": ref_count}
    return {"stream": data, "rows": rows, "types": types, "info": info}


def _subtree_end(nodes, i):
    """Index of the first node after node i's subtree (next sibling or earlier), from levels."""
    level = nodes[i]["level"]
    j = i + 1
    while j < len(nodes) and nodes[j]["level"] > level:
        j += 1
    return j


class _Cursor:
    __slots__ = ("pos",)

    def __init__(self, pos):
        self.pos = pos


def _record(records, path, value, offset, size, type_name):
    records.append({"path": path, "value": value, "offset": offset, "size": size,
                    "type": type_name})


def _need(body, cur, count, path):
    if cur.pos + count > len(body):
        raise TypeTreeDecodeError(
            f"field {path!r} needs {count} bytes at {cur.pos} but the body has {len(body)}")


def _i32(body, cur, path):
    _need(body, cur, 4, path)
    value = struct.unpack_from("<i", body, cur.pos)[0]
    cur.pos += 4
    return value


def _read_array_container(body, nodes, i, path, cur, records, kind):
    """Shared vector/map body: i32 count then count repeats of the template that starts after
    the size node's subtree (for maps that template is the pair struct, decoded as a struct so
    first/second keep their names). Returns the index after the container's subtree."""
    array_node = i + 1
    if nodes[array_node]["type"] != "Array":
        raise TypeTreeDecodeError(f"{kind} {path!r} has no Array child")
    size_node = array_node + 1
    if size_node >= len(nodes) or nodes[size_node]["type"] not in _INT_NAMES:
        raise TypeTreeDecodeError(
            f"{kind} {path!r} size node is {nodes[size_node]['type']!r}, not an int")
    start = cur.pos
    count = _i32(body, cur, path + ".Array.size")
    _record(records, path + ".Array.size", count, start, 4, "int")
    template = _subtree_end(nodes, size_node)
    if count < 0 or count > len(body) - cur.pos:
        raise TypeTreeDecodeError(
            f"{kind} {path!r} count {count} cannot fit in {len(body) - cur.pos} bytes")
    element_path = path + ".Array.data"
    for k in range(count):
        _decode_node(body, nodes, template, "%s[%d]" % (element_path, k), cur, records)
    return _subtree_end(nodes, i)


def _decode_node(body, nodes, i, path, cur, records):
    """Decode node i (path = its dotted path, "" for the root); returns the node index after
    the subtree and advances cur.pos. Alignment rule: AFTER the node iff its metaFlag (or, for
    arrays/maps, also the Array child's metaFlag) has 0x4000; always to 4, never to 8."""
    node = nodes[i]
    type_name = node["type"]
    align = bool(node["metaFlag"] & ALIGN_FLAG)

    if type_name == "string":
        start = cur.pos
        length = _i32(body, cur, path)
        if length < 0:
            raise TypeTreeDecodeError(f"string {path!r} has negative length {length}")
        _need(body, cur, length, path)
        value = body[cur.pos:cur.pos + length].decode("utf-8", "replace")
        cur.pos += length
        cur.pos += (-cur.pos) % 4
        _record(records, path, value, start, 4 + length, "string")
        nxt = _subtree_end(nodes, i)
    elif type_name == "TypelessData":
        start = cur.pos
        length = _i32(body, cur, path)
        if length < 0:
            raise TypeTreeDecodeError(f"TypelessData {path!r} has negative size {length}")
        _need(body, cur, length, path)
        cur.pos += length
        _record(records, path, length, start, 4 + length, "TypelessData")
        nxt = _subtree_end(nodes, i)
    elif type_name.startswith("PPtr"):
        _need(body, cur, 12, path)
        file_id = struct.unpack_from("<i", body, cur.pos)[0]
        path_id = struct.unpack_from("<q", body, cur.pos + 4)[0]
        _record(records, path + ".m_FileID", file_id, cur.pos, 4, "int")
        _record(records, path + ".m_PathID", path_id, cur.pos + 4, 8, "SInt64")
        cur.pos += 12
        nxt = _subtree_end(nodes, i)
    elif type_name == "bool":
        _need(body, cur, 1, path)
        _record(records, path, body[cur.pos] != 0, cur.pos, 1, "bool")
        cur.pos += 1
        nxt = i + 1
    elif type_name in _PRIMITIVES:
        fmt, size = _PRIMITIVES[type_name]
        _need(body, cur, size, path)
        value = struct.unpack_from(fmt, body, cur.pos)[0]
        _record(records, path, value, cur.pos, size, type_name)
        cur.pos += size
        nxt = i + 1
    elif i + 1 < len(nodes) and nodes[i + 1]["type"] == "Array":
        align = align or bool(nodes[i + 1]["metaFlag"] & ALIGN_FLAG)
        nxt = _read_array_container(body, nodes, i, path, cur, records, "array")
    else:
        nxt = _subtree_end(nodes, i)
        if nxt == i + 1:
            raise TypeTreeDecodeError(
                f"unsupported variable type {type_name!r} at {path or node['name']!r}")
        j = i + 1
        while j < nxt:
            child = nodes[j]["name"]
            child_path = f"{path}.{child}" if path else child
            j = _decode_node(body, nodes, j, child_path, cur, records)

    if align:
        cur.pos += (-cur.pos) % 4
    return nxt


def decode_object(body, nodes):
    """Decode one object body against its type tree: (records, consumed). records are flat
    {"path", "value", "offset", "size", "type"} leaf entries (offset body-relative, size
    without trailing alignment); consumed is the final cursor. Raises TypeTreeDecodeError on
    any out-of-bounds read, implausible count or unsupported variable type."""
    if not nodes or nodes[0]["level"] != 0:
        raise TypeTreeDecodeError("type tree must start with a level-0 root node")
    records = []
    cur = _Cursor(0)
    _decode_node(body, nodes, 0, "", cur, records)
    return records, cur.pos


def main():
    ap = argparse.ArgumentParser(description="decode objects of the type tree carrying FIELD "
                                             "and print flat fields plus consumed size")
    ap.add_argument("--bundle", required=True, help="UnityFS bundle file (read-only)")
    ap.add_argument("--inspect-target", required=True, metavar="FIELD",
                    help="field name that identifies the type tree to decode")
    args = ap.parse_args()
    tb = load_typed_bundle(args.bundle)
    info = tb["info"]
    print("bundle %s" % args.bundle)
    print("node %s editor %s platform %d fileVersion %d types %d objects %d"
          % (info["node"], info["editor"], info["platform"], info["fileVersion"],
             info["typeCount"], info["objectCount"]))
    hits = [t for t in tb["types"] if any(n["name"] == args.inspect_target for n in t["nodes"])]
    if not hits:
        raise SystemExit("no type tree carries a field named %r" % args.inspect_target)
    for t in hits:
        script = " scriptID %s" % t["scriptID"] if t["scriptID"] else ""
        print("type slot %d classID %d nodes %d%s"
              % (t["slot"], t["classID"], len(t["nodes"]), script))
        for pid in sorted(tb["rows"]):
            row = tb["rows"][pid]
            if row["typeSlot"] != t["slot"]:
                continue
            print("object %d offset %d size %d" % (pid, row["offset"], row["size"]))
            body = tb["stream"][row["offset"]:row["offset"] + row["size"]]
            try:
                records, consumed = decode_object(body, t["nodes"])
            except TypeTreeDecodeError as exc:
                print("  decode failed: %s" % exc)
                continue
            for r in records:
                print("  %s = %r @%d +%d %s"
                      % (r["path"], r["value"], r["offset"], r["size"], r["type"]))
            print("  consumed %d of %d" % (consumed, row["size"]))


if __name__ == "__main__":
    main()
