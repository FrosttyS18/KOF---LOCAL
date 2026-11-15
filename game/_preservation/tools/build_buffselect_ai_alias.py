"""Deterministic stdlib builder for ONE container alias in the prefabs_ai_buffselect bundle.

Buff Select's Goenitz graph loads through CharacterInitializer_Monster.SetAI (0x1810954E0), which
appends "_Mob" and GetAssets "assets/.../buffselect_goenitz_1_normal_mob.asset" -- a container key
the original bundle does not carry, so mob mode can never resolve the original BehaviourTree graph.
Swapping in a generic fighter is not approved; this tool regenerates the bundle with one extra
m_Container entry, the alias key pointing at the SAME AssetInfo (preloadIndex/preloadSize/fileID/
pathID) as the original graph entry. The graph object and every other object keep their exact bytes;
the old AssetBundle object body stays in the file as unaddressed bytes.

Canonical discovery, no hardcoded offsets. The SerializedFile v22 walk (types with type trees,
object table, exact metadata end) is tools/read_unity_serialized.py's, imported read-only; the
block info is parsed here because that module stops at the first node. Class 142 is a NamedObject:
m_Name is the FIRST field of the body (verified against this bundle's bytes: 21 = "prefabs_"
"ai_buffselect"), followed by preloadCount + PPtr[12] each, then containerCount + (aligned string
key + AssetInfo[preloadIndex i32, preloadSize i32, PPtr 12]) each, then the remainder verbatim.

Layout changes vs the input, kept minimal: object 142's table row is redirected to a copy appended
8-aligned at the end of the SerializedFile (byteStart is relative to m_DataOffset, so the new value
is nodeEnd + pad - m_DataOffset); the header's BIG-ENDIAN i64 fileSize @+24 grows; the object's
byteSize follows the new body. m_MetadataSize, m_DataOffset, the object count, every pathID and
every other table row are untouched. The new body differs from the original ONLY in containerCount
+1 and the inserted entry at its lexical position ("_mob" sorts right after the base key).

The UnityFS re-emit writes every storage block UNCOMPRESSED (mode 0): the project has no LZ4
compressor and determinism matters more than size. The block info's 16-byte hash field is zero in
this bundle and is re-emitted as zero (it is not a CRC; nothing is invented). Header strings
("5.x.x", "2021.3.12f1"), the CAB- node name/flags and the type trees are preserved from the parse.
Supported input shape, on purpose exactly this bundle's: SerializedFile v22, platform 19, ONE node
at stream offset 0, blocks-info not at end. Anything else aborts.

Outputs go ONLY to the required --output directory: the rebuilt bundle under its original md5
bundle-name filename, an assetbundles.info derived from the original with exactly this bundle's
32 hex hash characters swapped for the rebuilt file's md5 (the index hash IS the bundle md5 here;
measured 3eff7522... == file md5), and report.json. Before anything is written the candidate bytes
are fully re-parsed and verified canonically (all objects byte-identical except the redirected 142,
17 original container entries preserved, alias carrying the base AssetInfo) from a TEMP copy --
never the cache, which is only ever opened read-only and hash-checked before and after the run.

Aborts (no partial output; everything is built and verified in memory first): missing cache file,
bundle absent from assetbundles.info, index hash != input md5, unparseable/truncated input (every
walk must reach its exact end), multi-node or offset-non-zero or .resS bundles, blocks-info-at-end,
platform/fileVersion surprises, not exactly one class-142 object, base graph key absent, alias key
already present (identical or divergent), output directory inside the cache, verification failure.

usage: build_buffselect_ai_alias.py --cache DIR --output DIR
"""
import argparse
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # the embedded python's _pth never adds the script's own folder
import read_unityfs
import read_unity_serialized as U

BUNDLE_NAME = "prefabs_ai_buffselect"
BASE_KEY = "assets/resources_assetbundles/prefabs/ai/buffselect/buffselect_goenitz_1_normal.asset"
ALIAS_KEY = BASE_KEY[: -len(".asset")] + "_mob.asset"
BLOCK_SIZE = 131072
FILE_VERSION, PLATFORM = 22, 19


def fail(msg):
    sys.exit("build_buffselect_ai_alias: %s" % msg)


def astring(blob, pos):
    """Aligned string of a serialized object body: [i32 len][bytes][pad to 4]; pos stays 4-aligned."""
    n = struct.unpack_from("<i", blob, pos)[0]
    if not 0 <= n <= 4096:
        fail("implausible string length %d at object offset %d" % (n, pos))
    return blob[pos + 4:pos + 4 + n].decode("utf-8"), pos + 4 + n + ((4 - n % 4) % 4)


def parse_container(body):
    """AssetBundle (class 142, a NamedObject: m_Name FIRST) -> name, preloads, entries, remainder."""
    pos = 0
    name, pos = astring(body, pos)
    preload_count = struct.unpack_from("<i", body, pos)[0]
    if not 0 <= preload_count <= 4096:
        fail("implausible preload count %d" % preload_count)
    pos += 4
    preloads = body[pos:pos + preload_count * 12]
    pos += preload_count * 12
    entry_count = struct.unpack_from("<i", body, pos)[0]
    if not 0 <= entry_count <= 4096:
        fail("implausible container count %d" % entry_count)
    pos += 4
    entries = []
    for _ in range(entry_count):
        key, pos = astring(body, pos)
        info = body[pos:pos + 20]
        if len(info) != 20:
            fail("container entry overruns the object body")
        pos += 20
        entries.append((key, info))
    return {"name": name, "preload_count": preload_count, "preloads": preloads,
            "entries": entries, "remainder": body[pos:]}


def build_object(new_entries, parsed):
    """The new class-142 body: same name/preloads/remainder, containerCount+1, alias lexical."""
    out = bytearray()
    for key, info in new_entries:
        raw = key.encode("utf-8")
        out += struct.pack("<i", len(raw)) + raw + b"\0" * ((4 - len(raw) % 4) % 4)
        out += info
    body = bytearray()
    n = len(parsed["name"].encode("utf-8"))
    body += struct.pack("<i", n) + parsed["name"].encode("utf-8") + b"\0" * ((4 - n % 4) % 4)
    body += struct.pack("<i", parsed["preload_count"]) + parsed["preloads"]
    body += struct.pack("<i", len(new_entries)) + out + parsed["remainder"]
    return bytes(body)


def parse_index(blob):
    """The whole assetbundles.info -> [(name, value)]; both halves must parse to the exact end."""
    entries, i = [], 0
    while i + 4 <= len(blob):
        n = struct.unpack_from("<i", blob, i)[0]
        if not 0 < n <= 256:
            fail("assetbundles.info: implausible name length %d at %d" % (n, i))
        name = blob[i + 4:i + 4 + n].decode("utf-8")
        i += 4 + n
        n2 = struct.unpack_from("<i", blob, i)[0]
        if not 0 < n2 <= 256:
            fail("assetbundles.info: implausible value length %d at %d" % (n2, i))
        entries.append((name, blob[i + 4:i + 4 + n2].decode("utf-8")))
        i += 4 + n2
    if i != len(blob):
        fail("assetbundles.info does not parse to its exact end")
    return entries


def bundle_layout(path):
    """Canonical walk of a bundle file -> dict with stream, data_offset, object rows and block info.
    Row: pathID -> (byteStart_field_pos, byteStart, byteSize_field_pos, byteSize, typeID, classID);
    byteStart values are relative to m_DataOffset, positions are absolute in the node stream."""
    raw = open(path, "rb").read()
    data, objects, classes, info = U.load_bundle(path)          # data = decompressed node stream
    off = 12
    for _ in range(2):
        off = raw.index(b"\0", off) + 1
    _, comp, uncomp, flags = struct.unpack_from(">QIII", raw, off)
    head_end = (off + 20 + 15) // 16 * 16
    bi = read_unityfs.decode(raw[head_end:head_end + comp], uncomp, flags & 63)
    block_count = struct.unpack_from(">I", bi, 16)[0]
    p = 20 + block_count * 10
    node_count = struct.unpack_from(">i", bi, p)[0]
    p += 4
    nodes = []
    for _ in range(node_count):
        n_off, n_size = struct.unpack_from(">qq", bi, p)
        p += 16
        n_flags = struct.unpack_from(">I", bi, p)[0]
        p += 4
        end = bi.index(b"\0", p)
        nodes.append((n_off, n_size, n_flags, bi[p:end].decode()))
        p = end + 1
    if p != len(bi):
        fail("block info does not parse to its exact end (%d of %d)" % (p, len(bi)))
    m = U._Reader(data, 48)                    # single node at stream offset 0: positions absolute
    m.strz()
    platform = m.i32()
    if platform != PLATFORM:
        fail("platform %d, expected %d" % (platform, PLATFORM))
    if not m.u8():
        fail("input carries no type trees; unsupported input shape")
    type_count = m.i32()
    for _ in range(type_count):
        U._serialized_type(m, True)
    object_count = m.i32()
    rows = {}
    for _ in range(object_count):
        m.align()
        pid = m.i64()
        start_field = m.p
        byte_start = m.i64()
        size_field = m.p
        byte_size = m.u32()
        type_id = m.i32()
        rows[pid] = (start_field, byte_start, size_field, byte_size, type_id, classes[type_id])
    if len(rows) != len(objects) or len(rows) != object_count:
        fail("object table mismatch")
    return {"raw": raw, "stream": data, "info": info, "flags": flags, "nodes": nodes,
            "rows": rows, "blocks": block_count}


def main():
    ap = argparse.ArgumentParser(description="add one m_Container alias to prefabs_ai_buffselect "
                                             "(outputs to TEMP only; never touches the cache)")
    ap.add_argument("--cache", required=True, help="the client's storage/cache directory (read-only)")
    ap.add_argument("--output", required=True, help="TEMP output directory for the rebuilt files")
    args = ap.parse_args()
    cache = os.path.abspath(args.cache)
    out_dir = os.path.abspath(args.output)
    if os.path.commonpath([cache, out_dir]) == cache:
        fail("output directory must not live inside the cache")

    src = os.path.join(cache, "assetbundles", hashlib.md5(BUNDLE_NAME.encode()).hexdigest())
    if not os.path.isfile(src):
        fail("no cached bundle for %s" % BUNDLE_NAME)
    raw = open(src, "rb").read()
    input_md5 = hashlib.md5(raw).hexdigest()
    input_sha = hashlib.sha256(raw).hexdigest()

    index = open(os.path.join(cache, "assetbundles.info"), "rb").read()
    entries = parse_index(index)
    hit = [e for e in entries if e[0] == BUNDLE_NAME]
    if not hit:
        fail("assetbundles.info carries no entry for %s" % BUNDLE_NAME)
    if hit[0][1] != input_md5:
        fail("assetbundles.info hash %s != input file md5 %s" % (hit[0][1], input_md5))
    value_at = index.index(input_md5.encode(), index.index(BUNDLE_NAME.encode()))

    lay = bundle_layout(src)
    if len(lay["nodes"]) != 1:
        fail("bundle carries %d nodes; only single-node bundles are supported" % len(lay["nodes"]))
    n_off, n_size, n_flags, n_name = lay["nodes"][0]
    if n_off != 0:
        fail("node offset %d != 0; unsupported input shape" % n_off)
    if n_name.endswith((".resS", ".resource")):
        fail("node %s is a resource stream; unsupported on purpose" % n_name)
    if lay["flags"] & 128:
        fail("blocks-info-at-end flag is unsupported")
    data_offset = lay["info"]["dataOffset"]

    rows_142 = [pid for pid, r in lay["rows"].items() if r[5] == 142]
    if len(rows_142) != 1:
        fail("expected exactly one AssetBundle object, found %d" % len(rows_142))
    pid142 = rows_142[0]
    row142 = lay["rows"][pid142]
    body = lay["stream"][data_offset + row142[1]:data_offset + row142[1] + row142[3]]
    if len(body) != row142[3]:
        fail("AssetBundle object body is truncated")

    parsed = parse_container(body)
    keys = [k for k, _i in parsed["entries"]]
    if ALIAS_KEY in keys:
        if dict(parsed["entries"])[ALIAS_KEY] == dict(parsed["entries"]).get(BASE_KEY):
            fail("alias key already present (identical AssetInfo); input is not the original bundle")
        fail("alias key already present with a divergent AssetInfo; refusing")
    if BASE_KEY not in keys:
        fail("original graph key %s not in the container (%d entries)" % (BASE_KEY, len(keys)))
    base_info = dict(parsed["entries"])[BASE_KEY]
    new_entries = list(parsed["entries"])
    insert_at = sum(1 for k, _i in new_entries if k < ALIAS_KEY)
    new_entries.insert(insert_at, (ALIAS_KEY, base_info))
    new_body = build_object(new_entries, parsed)

    stream = bytearray(lay["stream"])
    pad = (8 - len(stream) % 8) % 8
    append_at = len(stream) + pad                                  # absolute, in the node stream
    stream += b"\0" * pad + new_body
    struct.pack_into(">q", stream, 24, len(stream))                # BE i64 fileSize @+24
    struct.pack_into("<q", stream, row142[0], append_at - data_offset)   # byteStart: dataOffset-relative
    struct.pack_into("<I", stream, row142[2], len(new_body))
    stream = bytes(stream)

    blocks = [stream[i:i + BLOCK_SIZE] for i in range(0, len(stream), BLOCK_SIZE)]
    new_bi = bytearray(16) + struct.pack(">I", len(blocks))
    for b in blocks:
        new_bi += struct.pack(">IIH", len(b), len(b), 0)           # mode 0: stored, uncompressed
    new_bi += struct.pack(">i", 1) + struct.pack(">qqI", 0, len(stream), n_flags) \
        + n_name.encode() + b"\0"
    new_flags = (lay["flags"] & ~0x3F) | 0
    u1 = raw.index(b"\0", 12)
    u2 = raw.index(b"\0", u1 + 1)
    out = bytearray(raw[:12])                                      # "UnityFS\0" + version u32
    out += raw[12:u2 + 1]                                          # "5.x.x\0" + "2021.3.12f1\0"
    size_at = len(out)
    out += struct.pack(">QIII", 0, len(new_bi), len(new_bi), new_flags)
    while len(out) % 16:
        out += b"\0"
    out += new_bi
    if new_flags & 0x200:
        while len(out) % 16:
            out += b"\0"
    for b in blocks:
        out += b
    struct.pack_into(">Q", out, size_at, len(out))                 # bundleSize u64
    out_md5 = hashlib.md5(out).hexdigest()

    new_index = bytearray(index)
    new_index[value_at:value_at + 32] = out_md5.encode()
    new_entries_idx = parse_index(bytes(new_index))
    if ([(n, v) for n, v in new_entries_idx if n != BUNDLE_NAME]
            != [(n, v) for n, v in entries if n != BUNDLE_NAME]
            or dict(new_entries_idx)[BUNDLE_NAME] != out_md5):
        fail("assetbundles.info verification failed")

    # full canonical reparse of the candidate bytes from a system TEMP copy -- never the cache,
    # never the output dir (which must not exist yet when an abort happens)
    import tempfile
    probe_fd, probe = tempfile.mkstemp(prefix="buffselect_alias_verify_")
    os.write(probe_fd, out)
    os.close(probe_fd)
    try:
        back = bundle_layout(probe)
        c1 = parse_container(back["stream"][back["info"]["dataOffset"] + back["rows"][pid142][1]:
                             back["info"]["dataOffset"] + back["rows"][pid142][1]
                             + back["rows"][pid142][3]])
        keys1 = [k for k, _i in c1["entries"]]
        others = [pid for pid in lay["rows"] if pid != pid142]
        if sorted(keys1) != sorted(keys + [ALIAS_KEY]) or \
                dict(c1["entries"])[ALIAS_KEY] != base_info or \
                any(dict(c1["entries"])[k] != dict(parsed["entries"])[k] for k in keys) or \
                c1["name"] != parsed["name"] or c1["preloads"] != parsed["preloads"] or \
                c1["remainder"] != parsed["remainder"] or \
                any(back["rows"][pid][1] != lay["rows"][pid][1]
                    or back["rows"][pid][3] != lay["rows"][pid][3]
                    or back["rows"][pid][4] != lay["rows"][pid][4]
                    or back["stream"][data_offset + back["rows"][pid][1]:
                        data_offset + back["rows"][pid][1] + back["rows"][pid][3]]
                    != lay["stream"][data_offset + lay["rows"][pid][1]:
                        data_offset + lay["rows"][pid][1] + lay["rows"][pid][3]]
                    for pid in others) or \
                len(back["nodes"]) != 1 or back["nodes"][0][3] != n_name:
            fail("verification: reparsed output does not match the contract")
    finally:
        os.remove(probe)
    if hashlib.md5(open(src, "rb").read()).hexdigest() != input_md5:
        fail("input file changed during the run; outputs are invalid")
    os.makedirs(out_dir, exist_ok=True)

    report = {"bundle": BUNDLE_NAME, "node": {"name": n_name, "flags": n_flags,
                                              "old_size": n_size, "new_size": len(stream)},
              "blocks": {"old": lay["blocks"], "new": len(blocks), "mode": 0,
                         "old_flags": lay["flags"], "new_flags": new_flags},
              "asset_bundle_object": {"path_id": pid142, "old_byte_start": row142[1],
                                      "old_byte_size": row142[3],
                                      "new_byte_start": append_at - data_offset,
                                      "new_byte_size": len(new_body), "name": parsed["name"],
                                      "preload_count": parsed["preload_count"],
                                      "container_entries": len(parsed["entries"])},
              "alias": {"key": ALIAS_KEY, "base_key": BASE_KEY, "info_hex": base_info.hex(),
                        "insert_at": insert_at},
              "input": {"md5": input_md5, "sha256": input_sha, "size": len(raw)},
              "output": {"md5": out_md5, "size": len(out)},
              "index_hash_swapped": {"from": input_md5, "to": out_md5}}
    open(os.path.join(out_dir, hashlib.md5(BUNDLE_NAME.encode()).hexdigest()), "wb").write(out)
    open(os.path.join(out_dir, "assetbundles.info"), "wb").write(new_index)
    json.dump(report, open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)
    print("verified: 17 original entries + alias (same AssetInfo), %d other objects byte-identical"
          % len([p for p in lay["rows"] if p != pid142]))
    print("alias %s -> base %s | object %d: %d@%d -> %d@%d appended"
          % (ALIAS_KEY, BASE_KEY, pid142, row142[3], row142[1], len(new_body),
             append_at - data_offset))
    print("bundle %d -> %d bytes, %d stored blocks | index hash %s -> %s"
          % (len(raw), len(out), len(blocks), input_md5, out_md5))
    print("outputs: %s" % out_dir)


if __name__ == "__main__":
    main()
