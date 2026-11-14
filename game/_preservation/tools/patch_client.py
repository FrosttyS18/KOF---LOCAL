"""Point the KOF ALLSTAR PC client at a local server and disable XIGNCODE.

  python patch_client.py            install (backs up originals as *.orig the first time)
  python patch_client.py --uninstall restore originals

Changes:
  - global-metadata.dat: Netmarble/Facebook URL literals  https://HOST/path -> http://127.0.0.1:PORT/HOST/path,
    and table folders table/common/ + table/lang_ -> table/offline_common/ + table/offline_lang_
    (new strings are appended to the end of the file; only the literal table entries are rewritten)
  - Plugins/x86_64/NMSSWBase.dll: replaced by the stub from stubs/build_nmssw_stub.py
  - boot.config: drop "nolog=" so Unity writes Player.log
  - GameAssembly.dll: four small code patches, the battle tutorial's download bar and the summon pick-up
    Select button (see CODE_PATCHES)
"""
import os, re, shutil, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA = os.path.join(GAME, "KOF ALLSTAR_Data")
META = os.path.join(DATA, "il2cpp_data", "Metadata", "global-metadata.dat")
NMSSW = os.path.join(DATA, "Plugins", "x86_64", "NMSSWBase.dll")
GA = os.path.join(GAME, "GameAssembly.dll")
BOOT = os.path.join(DATA, "boot.config")
STUB = os.path.join(HERE, "..", "stubs", "NMSSWBase.dll")
LOCAL = "http://127.0.0.1:18080/"

# hosts whose literals we redirect; '{0}' covers URLs whose host is filled in at runtime
REDIRECT = re.compile(r"^https?://((?:[\w-]+\.)*(?:netmarble\.(?:com|net)|facebook\.(?:com|net))"
                      r"|\{0\}|dev-\{0\}|graph\.\{0\})")


# Rebuilt master-data tables live in their own folders so the original (encrypted) tables under
# storage/cache/table/common and lang_* are never read or overwritten again. Only DownloadManager.GetTablePath
# uses these two literals.
LITERALS = {
    "table/common/": "table/offline_common/",
    "table/lang_": "table/offline_lang_",
}


def backup(path):
    if not os.path.exists(path + ".orig"):
        shutil.copy2(path, path + ".orig")
    return path + ".orig"


def patch_metadata():
    src = open(backup(META), "rb").read()
    hdr = struct.unpack_from("<2I" + "i" * 60, src, 0)
    lit_off, lit_size, data_off = hdr[2], hdr[3], hdr[4]
    out = bytearray(src)
    changed = []
    for i in range(lit_size // 8):
        ln, idx = struct.unpack_from("<Ii", src, lit_off + i * 8)
        s = src[data_off + idx:data_off + idx + ln].decode("utf-8", "replace")
        if s in LITERALS:
            new = LITERALS[s]
        elif REDIRECT.match(s):
            new = LOCAL + s.split("://", 1)[1]
        else:
            continue
        nb = new.encode()
        pos = len(out)
        out += nb
        struct.pack_into("<Ii", out, lit_off + i * 8, len(nb), pos - data_off)
        changed.append((s, new))
    open(META, "wb").write(out)
    return changed


# The battle tutorial's "DOWNLOADING..." bar. SceneBattleTutorial.LoadingEnd gives the background downloader a
# finished callback (OnFinishedDownloading) and turns the bar on; a download's progress then reaches it through
# AssetBundleManager.UpdateCDNProgress -> UIView_BattleTutorial.SetDownLoadProgresValue, which hides it at 100%.
# With every bundle cached the title starts no download (UIView_Title.CheckBundleSize: 5 MB or less missing), so
# nothing ever finished and the bar stayed up for the whole tutorial. LoadingEnd now leaves it off
# (SafeSetActive(bar, true) -> false); a real download's first progress update still turns it on.
BAR_RVA = 0x1624E42                                      # in SceneBattleTutorial.LoadingEnd
BAR_ORIG = bytes.fromhex("4533c0" "b201" "488bc8")       # xor r8d,r8d / mov dl,1 / mov rcx,rax (-> SafeSetActive)
BAR_PATCHED = bytes.fromhex("4533c0" "33d2" "488bc8")    # xor r8d,r8d / xor edx,edx / mov rcx,rax

# The summon SELECT PICK UP popup's Select button applies a selection only when SelectPickupModel.MaxChecker passes,
# and that asks the limit's IsFull: picked count == slot count, then IsForceLineupFull. So picks, once set, could only
# be swapped, never cleared. IsFull now skips the count test (je -> jmp to the force-lineup test, which still decides),
# so Select also applies one pick or none. Controller_SelectPickup.SendGachaSelectPickup then sends only when
# SelectPickupManager.Changed, which asks whether a selected unit is not among the saved ones - fewer picks read as
# unchanged - so its "unchanged" answer is now "changed" (xor al,al -> mov al,1): a smaller selection is sent, and an
# unchanged one is sent again, which the server just saves.
FULL_ORIG, FULL_PATCHED = bytes.fromhex("7403"), bytes.fromhex("eb03")   # je +3 / jmp +3, after cmp count,max

CODE_PATCHES = [
    (BAR_RVA, BAR_ORIG, BAR_PATCHED, "battle tutorial download bar off until a real download reports progress"),
    (0x6FF236, FULL_ORIG, FULL_PATCHED, "summon pick-up Select applies fewer fighter picks than slots"),  # SelectPickupFighterLimit.get_IsFull
    (0x6FE806, FULL_ORIG, FULL_PATCHED, "summon pick-up Select applies fewer card picks than slots"),  # SelectPickupBattlecardLimit.get_IsFull
    (0x170891A, bytes.fromhex("32c0"), bytes.fromhex("b001"), "summon pick-up Select sends fewer picks than saved"),  # SelectPickupManager.Changed
]


def file_offset(out, rva):
    pe, = struct.unpack_from("<I", out, 0x3C)
    nsec, opt_size = struct.unpack_from("<H", out, pe + 6)[0], struct.unpack_from("<H", out, pe + 20)[0]
    for i in range(nsec):
        vsize, va, raw_size, raw_ptr = struct.unpack_from("<IIII", out, pe + 24 + opt_size + 40 * i + 8)
        if va <= rva < va + raw_size:
            return raw_ptr + rva - va
    sys.exit(f"GameAssembly.dll has no section at RVA {rva:#x}")


def patch_code():
    out = bytearray(open(backup(GA), "rb").read())
    for rva, orig, patched, _ in CODE_PATCHES:
        off = file_offset(out, rva)
        if out[off:off + len(orig)] != orig:
            sys.exit("GameAssembly.dll is not the v1.17.0 build this patch was made for")
        out[off:off + len(orig)] = patched
    open(GA, "wb").write(out)
    return [what for *_, what in CODE_PATCHES]


def install():
    for old, new in patch_metadata():
        print(f"  literal  {old}\n       -> {new}")
    for what in patch_code():
        print("  GameAssembly.dll:", what)
    backup(NMSSW)
    shutil.copy2(STUB, NMSSW)
    print("  NMSSWBase.dll -> offline stub")
    lines = open(backup(BOOT), encoding="utf-8").read().splitlines()
    open(BOOT, "w", encoding="utf-8", newline="\n").write(
        "\n".join(l for l in lines if not l.startswith("nolog")) + "\n")
    print("  boot.config: logging enabled")


def uninstall():
    for p in (META, NMSSW, BOOT, GA):
        if os.path.exists(p + ".orig"):
            shutil.copy2(p + ".orig", p)
            print("  restored", os.path.relpath(p, GAME))


if __name__ == "__main__":
    uninstall() if "--uninstall" in sys.argv else install()
