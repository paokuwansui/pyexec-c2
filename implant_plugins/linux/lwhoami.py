import getpass
import os

PLUGIN = {"name": "Linux 当前用户", "commands": ["lwhoami"], "platform": "linux", "risk": "R0", "description": "Python 实现的 whoami", "write_disk": False}


def run(runtime, args):
    data = {"user": getpass.getuser(), "uid": os.getuid(), "gid": os.getgid(), "groups": os.getgroups()}
    runtime.emit(data["user"])
    return data
