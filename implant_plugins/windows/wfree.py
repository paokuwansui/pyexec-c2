import ctypes
from ctypes import wintypes

PLUGIN = {"name": "Windows free 内存信息", "commands": ["wfree"], "platform": "windows", "risk": "R0", "description": "Python WinAPI 内存信息", "write_disk": False}


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def run(runtime, args):
    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(stat)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    data = {"percent": stat.dwMemoryLoad, "total_phys": stat.ullTotalPhys, "avail_phys": stat.ullAvailPhys}
    runtime.emit("\n".join(f"{key}: {value}" for key, value in data.items()))
    return data
