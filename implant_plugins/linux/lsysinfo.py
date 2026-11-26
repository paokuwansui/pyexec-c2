import getpass
import json
import os
import platform
import socket
import sys

PLUGIN = {
    "name": "Linux sysinfo 系统信息",
    "commands": ["lsysinfo"],
    "platform": "linux",
    "risk": "R0",
    "description": "Python 实现的 uname / 系统信息",
    "write_disk": False,
}


def run(runtime, args):
    uname = os.uname()
    data = {
        "hostname": socket.gethostname(),
        "sysname": uname.sysname,
        "release": uname.release,
        "version": uname.version,
        "machine": uname.machine,
        "platform": platform.platform(),
        "python": sys.version,
        "user": getpass.getuser(),
        "cwd": os.getcwd(),
        "pid": os.getpid(),
    }
    runtime.emit(json.dumps(data, ensure_ascii=False, indent=2))
    return data
