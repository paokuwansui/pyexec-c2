import ctypes
import socket
import struct
from ctypes import wintypes

PLUGIN = {
    "name": "Windows 网络连接",
    "commands": ["wnetstat"],
    "platform": "windows",
    "risk": "R1",
    "description": "Windows GetExtendedTcpTable 连接列表",
    "write_disk": False,
}

AF_INET = 2
TCP_TABLE_OWNER_PID_ALL = 5
iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)


class MIB_TCPROW_OWNER_PID(ctypes.Structure):
    _fields_ = [
        ("dwState", wintypes.DWORD),
        ("dwLocalAddr", wintypes.DWORD),
        ("dwLocalPort", wintypes.DWORD),
        ("dwRemoteAddr", wintypes.DWORD),
        ("dwRemotePort", wintypes.DWORD),
        ("dwOwningPid", wintypes.DWORD),
    ]


def run(runtime, args):
    size = wintypes.DWORD(0)
    iphlpapi.GetExtendedTcpTable(None, ctypes.byref(size), False, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0)
    buf = ctypes.create_string_buffer(size.value)
    if iphlpapi.GetExtendedTcpTable(buf, ctypes.byref(size), False, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0) != 0:
        return {"connections": [], "error": "GetExtendedTcpTable failed"}
    count = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD)).contents.value
    rows = []
    offset = ctypes.sizeof(wintypes.DWORD)
    for index in range(count):
        row = MIB_TCPROW_OWNER_PID.from_buffer_copy(buf.raw[offset + index * ctypes.sizeof(MIB_TCPROW_OWNER_PID):])
        local_ip = socket.inet_ntoa(struct.pack("<I", row.dwLocalAddr))
        remote_ip = socket.inet_ntoa(struct.pack("<I", row.dwRemoteAddr))
        local_port = socket.ntohs(row.dwLocalPort & 0xFFFF)
        remote_port = socket.ntohs(row.dwRemotePort & 0xFFFF)
        rows.append({"local": f"{local_ip}:{local_port}", "remote": f"{remote_ip}:{remote_port}", "pid": int(row.dwOwningPid), "state": int(row.dwState)})
    runtime.emit("\n".join(f"{r['local']:<22} {r['remote']:<22} {r['pid']}" for r in rows))
    return {"connections": rows}
