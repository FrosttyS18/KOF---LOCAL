"""Initialize the empty first-clear slot in the supported PC client, in memory only.

SetStarMission skips initialization for NULL missions and no first-clear reward.
Removing that early return lets its existing SetResultData(NULL, true, false) path
show the received state. Real first clears and non-NULL missions keep their paths.
No executable, asset, reward data, save or preference file is written.
"""
import ctypes
from ctypes import wintypes as W
import hashlib
import os
import time

BUILD_SHA256 = "6fc8a66893ddd282b9297c4cbe619b445c4121373fc2734e879faf4f5504c651"
RVA = 0x7F6F48
EXPECTED = bytes.fromhex("440fb64e364584c97497488b46704885c00f847f01000083")
PATCH_AT = 8
PATCH = b"\x90\x90"


class ModuleEntry(ctypes.Structure):
    _fields_ = [("dwSize", W.DWORD), ("th32ModuleID", W.DWORD),
                ("th32ProcessID", W.DWORD), ("GlblcntUsage", W.DWORD),
                ("ProccntUsage", W.DWORD), ("modBaseAddr", ctypes.c_void_p),
                ("modBaseSize", W.DWORD), ("hModule", W.HMODULE),
                ("szModule", W.WCHAR * 256), ("szExePath", W.WCHAR * 260)]


def patched_window(data):
    patched = EXPECTED[:PATCH_AT] + PATCH + EXPECTED[PATCH_AT + len(PATCH):]
    if data not in (EXPECTED, patched):
        raise RuntimeError("Cliente incompatível: instruções da recompensa divergiram.")
    return patched


def apply_reward_compat(process, dll_path, timeout=20):
    if os.name != "nt":
        raise RuntimeError("A correção de compatibilidade exige Windows.")
    with open(dll_path, "rb") as source:
        if hashlib.sha256(source.read()).hexdigest() != BUILD_SHA256:
            raise RuntimeError("Build do cliente não reconhecida; correção não aplicada.")
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
    k.CreateToolhelp32Snapshot.restype = W.HANDLE
    k.Module32FirstW.argtypes = [W.HANDLE, ctypes.POINTER(ModuleEntry)]
    k.Module32NextW.argtypes = [W.HANDLE, ctypes.POINTER(ModuleEntry)]
    k.CloseHandle.argtypes = [W.HANDLE]
    k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k.OpenProcess.restype = W.HANDLE
    k.ReadProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k.WriteProcessMemory.argtypes = k.ReadProcessMemory.argtypes
    k.VirtualProtectEx.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_size_t, W.DWORD, ctypes.POINTER(W.DWORD)]
    k.FlushInstructionCache.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_size_t]
    expected_path = os.path.normcase(os.path.abspath(dll_path))
    deadline = time.monotonic() + timeout
    base = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("O jogo fechou antes de carregar o cliente.")
        snapshot = k.CreateToolhelp32Snapshot(0x18, process.pid)
        if snapshot not in (None, ctypes.c_void_p(-1).value):
            try:
                row = ModuleEntry()
                row.dwSize = ctypes.sizeof(row)
                found = k.Module32FirstW(snapshot, ctypes.byref(row))
                while found:
                    if os.path.normcase(os.path.abspath(row.szExePath)) == expected_path:
                        base = row.modBaseAddr
                        break
                    found = k.Module32NextW(snapshot, ctypes.byref(row))
            finally:
                k.CloseHandle(snapshot)
        if base is not None:
            break
        time.sleep(0.05)
    if base is None:
        raise RuntimeError("O cliente não carregou no prazo da correção de recompensa.")
    handle = k.OpenProcess(0x438, False, process.pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        def read(address, size):
            buffer = ctypes.create_string_buffer(size)
            count = ctypes.c_size_t()
            if not k.ReadProcessMemory(handle, address, buffer, size, ctypes.byref(count)) or count.value != size:
                raise ctypes.WinError(ctypes.get_last_error())
            return buffer.raw

        address = base + RVA
        before = read(address, len(EXPECTED))
        patched = patched_window(before)
        if before == patched:
            return {"rewardCompat": "already_applied", "pid": process.pid}
        protection = W.DWORD()
        if not k.VirtualProtectEx(handle, address + PATCH_AT, len(PATCH), 0x40, ctypes.byref(protection)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            count = ctypes.c_size_t()
            buffer = ctypes.create_string_buffer(PATCH)
            if not k.WriteProcessMemory(handle, address + PATCH_AT, buffer, len(PATCH), ctypes.byref(count)) or count.value != len(PATCH):
                raise ctypes.WinError(ctypes.get_last_error())
            if not k.FlushInstructionCache(handle, address + PATCH_AT, len(PATCH)):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            restored = W.DWORD()
            if not k.VirtualProtectEx(handle, address + PATCH_AT, len(PATCH), protection.value, ctypes.byref(restored)):
                raise ctypes.WinError(ctypes.get_last_error())
        if read(address, len(EXPECTED)) != patched:
            raise RuntimeError("A verificação da correção em memória falhou.")
        return {"rewardCompat": "applied", "pid": process.pid, "changedBytes": len(PATCH)}
    finally:
        k.CloseHandle(handle)
