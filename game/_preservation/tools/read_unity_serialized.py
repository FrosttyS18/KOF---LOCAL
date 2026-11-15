"""Read-only SerializedFile v22 (Unity 2021.3.12f1, this client's bundles) parser following
AssetStudio's SerializedFile.cs field order, layered on tools/read_unityfs.py for UnityFS node
streams. Canonical layout, no empirical calibration: every offset comes from the header, the
counted tables and the type trees.

Header (48 bytes, the first four u32 big-endian): m_MetadataSize u32 @0, m_FileSize u32 @4,
m_Version u32 @8 (=22), m_DataOffset u32 @12, endian u8 @16 (0 = little), reserved[3] @17;
LargeFilesSupport re-reads metadataSize u32 @20, fileSize i64 @24, dataOffset i64 @32,
unknown i64 @40; m_EditorVersion strz @48. Metadata (little-endian) ends EXACTLY at
48 + metadataSize: platform i32; enableTypeTree u8; typeCount i32; per SerializedType: classID
i32, isStripped u8, scriptTypeIndex i16, scriptID 16B (classID 114 only), oldTypeHash 16B, then
with enableTypeTree the TypeTree blob [nodeCount i32][stringBufferSize i32][nodeCount x 32B
nodes][stringBuffer] followed by typeDependencies i32[count] (version 21+); m_Objects: count
i32 + align-4 records [pathID i64][byteStart i64][byteSize u32][typeID i32] (blob address =
node start + dataOffset + byteStart); m_ScriptTypes; m_Externals; THEN m_RefTypes (count i32 +
SerializedType entries, 0 in every bundle seen here) and m_UserInformation strz -- the port's
strict end-of-metadata equality is what proves whether refTypes were consumed correctly.

Structure readers cover only the three classes the trigger graphs need, read straight from the
serialized bytes with sanity bounds (no generic TypeTreeReader): GameObject = [component count
i32][PPtr pairs 12B][layer i32][m_Name aligned string]; MonoBehaviour = [gameObject PPtr]
[enabled u8 + pad 3][script PPtr][m_Name aligned string][payload]; Transform = [gameObject
PPtr][local 40B][children PPtrs][father PPtr].
"""
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import read_unityfs


MONSTER_TOKEN = re.compile(rb"Monster\.[A-Za-z0-9_.]+")
GRAPH_MARKER = b"NodeCanvas.BehaviourTree"


class _Reader:
    def __init__(self, data, pos=0):
        self.d, self.p = data, pos

    def u8(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def i16(self):
        v = struct.unpack_from("<h", self.d, self.p)[0]
        self.p += 2
        return v

    def i32(self):
        v = struct.unpack_from("<i", self.d, self.p)[0]
        self.p += 4
        return v

    def u32(self):
        v = struct.unpack_from("<I", self.d, self.p)[0]
        self.p += 4
        return v

    def i64(self):
        v = struct.unpack_from("<q", self.d, self.p)[0]
        self.p += 8
        return v

    def u64(self):
        v = struct.unpack_from("<Q", self.d, self.p)[0]
        self.p += 8
        return v

    def align(self, n=4):
        while self.p % n:
            self.p += 1

    def strz(self):
        end = self.d.index(b"\0", self.p)
        v = self.d[self.p:end].decode("utf-8", "replace")
        self.p = end + 1
        return v

    def astring(self):
        n = self.i32()
        v = self.d[self.p:self.p + n].decode("utf-8", "replace")
        self.p += n
        self.align()
        return v


def _typetree_blob(r):
    """[nodeCount i32][stringBufferSize i32][nodes 32B from +8][stringBuffer]; typeDependencies
    (i32[count], version 21+) are read separately by the caller right after the buffer."""
    count = r.i32()
    string_size = r.i32()
    if not 0 <= count <= 100000 or not 0 <= string_size <= 16 * 1024 * 1024:
        raise ValueError(f"implausible typetree counts nodes={count} strings={string_size}")
    r.p += count * 32
    strings = r.d[r.p:r.p + string_size]
    r.p += string_size
    return strings


def _serialized_type(r, enable_type_tree):
    class_id = r.i32()
    r.u8()   # isStripped
    r.i16()  # scriptTypeIndex
    if class_id == 114:
        r.p += 16  # scriptID
    r.p += 16     # oldTypeHash
    if enable_type_tree:
        _typetree_blob(r)
        dep_count = r.i32()
        if not 0 <= dep_count <= 4096:
            raise ValueError(f"type {class_id}: implausible dependency count {dep_count}")
        r.p += 4 * dep_count
    return class_id


def load_bundle(path):
    """Canonical parse: (data stream, objects {pathID: (abs offset, size, typeID)},
    classes [classID per type slot], info dict). Validates fileVersion 22, little-endian,
    fileSize == node size, metadata bounds, sane counts, unique pathIDs, byteStart >= 0 and
    every object inside the node."""
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

    m = _Reader(data, n_off + 48)
    editor_version = m.strz()
    platform = m.i32()
    enable_type_tree = m.u8()
    type_count = m.i32()
    if not 0 < type_count <= 4096:
        raise ValueError(f"implausible type count {type_count}")
    classes = [_serialized_type(m, enable_type_tree) for _ in range(type_count)]

    object_count = m.i32()
    if not 0 < object_count <= 1000000:
        raise ValueError(f"implausible object count {object_count}")
    objects = {}
    for _ in range(object_count):
        m.align()
        pid = m.i64()
        byte_start = m.i64()
        byte_size = m.u32()
        type_id = m.i32()
        # duplicate pathIDs are rejected BEFORE the dict: inserting first and checking after
        # would collapse the duplicate and detect nothing
        if pid in objects:
            raise ValueError(f"duplicate pathID {pid}")
        if byte_start < 0 or byte_size <= 0:
            raise ValueError(f"object {pid:016x}: bad blob bounds start={byte_start} size={byte_size}")
        abs_off = n_off + data_offset + byte_start
        if abs_off + byte_size > n_off + n_size:
            raise ValueError(f"object {pid:016x} out of file bounds")
        if not 0 <= type_id < type_count:
            raise ValueError(f"object {pid:016x} typeID {type_id} outside type table")
        objects[pid] = (abs_off, byte_size, type_id)
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
        m.strz()          # tempEmpty
        m.p += 16         # guid
        m.i32()           # type
        externals.append(m.strz())
    ref_count = m.i32()  # m_RefTypes, after m_Externals
    if not 0 <= ref_count <= 4096:
        raise ValueError(f"implausible refType count {ref_count}")
    for _ in range(ref_count):
        _serialized_type(m, enable_type_tree)
    user_info = m.strz()
    if m.p != n_off + 48 + metadata_size:
        raise ValueError(f"metadata end {m.p - n_off} != 48+metadataSize {48 + metadata_size}")
    if not 48 <= table_end <= data_offset:
        raise ValueError(f"object table end {table_end} outside metadata region")

    info = {"node": nm, "editor": editor_version, "platform": platform, "fileVersion": file_version,
            "metadataSize": metadata_size, "fileSize": file_size, "dataOffset": data_offset,
            "typeCount": type_count, "objectCount": object_count, "tableEnd": table_end,
            "userInfo": user_info, "externals": externals, "classes": classes,
            "refTypeCount": ref_count}
    return data, objects, classes, info


def read_gameobject(data, off, size):
    try:
        count = struct.unpack_from("<i", data, off)[0]
        if not 0 <= count <= 64:
            return None
        r, comps = off + 4, []
        for _ in range(count):
            fid, pid = struct.unpack_from("<Iq", data, r)
            if fid != 0:
                return None
            comps.append(pid)
            r += 12
        layer = struct.unpack_from("<i", data, r)[0]
        if not 0 <= layer <= 32:
            return None
        r += 4
        n = struct.unpack_from("<i", data, r)[0]
        if not 1 <= n <= 60:
            return None
        name = data[r + 4:r + 4 + n].decode()
        if not all(32 <= ord(c) < 127 for c in name):
            return None
        return {"name": name, "components": comps}
    except Exception:
        return None


def read_monobehaviour(data, off, size):
    try:
        go_fid, go_pid = struct.unpack_from("<Iq", data, off)
        if data[off + 13:off + 16] != b"\0\0\0":
            return None
        r = off + 28
        n = struct.unpack_from("<i", data, r)[0]
        if not 0 <= n <= 64:
            return None
        name = data[r + 4:r + 4 + n].decode("utf-8", "replace")
        r += 4 + n + (-n) % 4
        return {"go_pid": go_pid, "name": name, "payload": data[r:off + size]}
    except Exception:
        return None


def read_transform(data, off, size):
    try:
        go_fid, go_pid = struct.unpack_from("<Iq", data, off)
        r = off + 52
        n = struct.unpack_from("<i", data, r)[0]
        if not 0 <= n <= 64:
            return None
        r += 4
        kids = []
        for _ in range(n):
            fid, cid = struct.unpack_from("<Iq", data, r)
            if fid != 0:
                return None
            kids.append(cid)
            r += 12
        return {"go_pid": go_pid, "children": kids}
    except Exception:
        return None


def index_bundle(path):
    """(data, gameobjects, monobehaviours, transforms, info) with per-class pid maps; only the
    three classes the trigger graphs need are read."""
    data, objects, classes, info = load_bundle(path)
    go_tids = {i for i, c in enumerate(classes) if c == 1}
    mb_tids = {i for i, c in enumerate(classes) if c == 114}
    tr_tids = {i for i, c in enumerate(classes) if c == 4}
    gos, mbs, trs = {}, {}, {}
    for pid, (off, size, tid) in objects.items():
        if tid in go_tids:
            g = read_gameobject(data, off, size)
            if g:
                gos[pid] = g
        elif tid in mb_tids:
            m = read_monobehaviour(data, off, size)
            if m:
                mbs[pid] = m
        elif tid in tr_tids:
            t = read_transform(data, off, size)
            if t:
                trs[pid] = t
    info["gos"], info["mbs"], info["transforms"] = len(gos), len(mbs), len(trs)
    return data, gos, mbs, trs, info


def subtree_gameobjects(gos, transforms, root_pid):
    """Every GameObject pid under `root_pid`, following component->Transform->children and
    child->GameObject PPtrs only (no name or proximity matching)."""
    seen, frontier = {root_pid}, []
    for c in gos[root_pid]["components"]:
        t = transforms.get(c)
        if t:
            frontier.extend(t["children"])
    while frontier:
        tp = frontier.pop()
        if tp in seen or tp not in transforms:
            continue
        seen.add(tp)
        frontier.extend(transforms[tp]["children"])
        gp = transforms[tp]["go_pid"]
        if gp in gos:
            seen.add(gp)
            for c in gos[gp]["components"]:
                t = transforms.get(c)
                if t:
                    frontier.extend(t["children"])
    return seen


def graph_monsters(mbs, go_pids, marker=GRAPH_MARKER, token=MONSTER_TOKEN):
    """(holders, monsters): the NodeCanvas graphs pointer-linked to GameObjects in go_pids and
    the Monster.* tokens inside those payloads -- the only string matching, inside an already
    pointer-linked graph."""
    monsters = set()
    holders = []
    for pid, m in mbs.items():
        if m["go_pid"] not in go_pids or marker not in m["payload"]:
            continue
        found = sorted(x.decode() for x in token.findall(m["payload"]))
        holders.append({"mb_pid": f"{pid:016x}", "mb_name": m["name"], "monsters": found})
        monsters |= set(found)
    return holders, monsters
