import ctypes
from ctypes import wintypes

PLUGIN = {"name": "Windows 终止进程", "commands": ["wkill"], "platform": "windows", "risk": "R3", "description": "Python WinAPI TerminateProcess", "write_disk": False}

PROCESS_TERMINATE = 0x0001


def run(runtime, args):
    pid = int(args.get("pid"))
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not handle:
        return {"pid": pid, "error": "OpenProcess failed"}
    try:
        ok = ctypes.windll.kernel32.TerminateProcess(handle, int(args.get("exit_code", 1)))
        if not ok:
            return {"pid": pid, "error": "TerminateProcess failed"}
        runtime.emit(f"terminated pid {pid}")
        return {"pid": pid, "terminated": True}
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
