import getpass
import json
import os
import platform
import socket
import sys

PLUGIN = {
    "name": "Windows sysinfo",
    "commands": ["wsysinfo"],
    "platform": "windows",
    "risk": "R0",
    "description": "Python 实现的 Windows 系统信息",
    "write_disk": False,
}


def run(runtime, args):
    data = {
        "hostname": socket.gethostname(),
        "computername": os.environ.get("COMPUTERNAME", ""),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": sys.version,
        "user": getpass.getuser(),
        "userdomain": os.environ.get("USERDOMAIN", ""),
        "userprofile": os.environ.get("USERPROFILE", ""),
        "cwd": os.getcwd(),
        "pid": os.getpid(),
    }
    runtime.emit(json.dumps(data, ensure_ascii=False, indent=2))
    return data
