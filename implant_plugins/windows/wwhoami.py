import getpass
import os

PLUGIN = {"name": "Windows 当前用户", "commands": ["wwhoami"], "platform": "windows", "risk": "R0", "description": "Python 实现的 whoami", "write_disk": False}


def run(runtime, args):
    data = {"user": getpass.getuser(), "username_env": os.environ.get("USERNAME", ""), "domain": os.environ.get("USERDOMAIN", "")}
    runtime.emit(data["user"])
    return data
