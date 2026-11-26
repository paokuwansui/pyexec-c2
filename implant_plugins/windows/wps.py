import ctypes
from ctypes import wintypes

PLUGIN = {
    "name": "Windows 进程列表",
    "commands": ["wps"],
    "platform": "windows",
    "risk": "R0",
    "description": "Windows EnumProcesses 进程列表",
    "write_disk": False,
}

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)


def run(runtime, args):
    count = 2048
    pid_array = (wintypes.DWORD * count)()
    needed = wintypes.DWORD()
    if not psapi.EnumProcesses(pid_array, ctypes.sizeof(pid_array), ctypes.byref(needed)):
        return {"processes": [], "error": "EnumProcesses failed"}
    rows = []
    for pid in pid_array[: needed.value // ctypes.sizeof(wintypes.DWORD)]:
        if not pid:
            continue
        handle = kernel32.OpenProcess(0x1000, False, pid)
        name = ""
        if handle:
            buf = ctypes.create_unicode_buffer(260)
            size = wintypes.DWORD(260)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                name = buf.value.rsplit("\\", 1)[-1]
            kernel32.CloseHandle(handle)
        rows.append({"pid": int(pid), "name": name})
    rows.sort(key=lambda row: row["pid"])
    runtime.emit("\n".join(f"{r['pid']:>7} {r['name']}" for r in rows))
    return {"processes": rows}
