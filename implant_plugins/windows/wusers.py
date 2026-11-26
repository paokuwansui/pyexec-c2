import getpass
import os

PLUGIN = {"name": "Windows 用户上下文", "commands": ["wusers"], "platform": "windows", "risk": "R1", "description": "Windows 当前用户与域上下文（无需外部命令）", "write_disk": False}


def run(runtime, args):
    data = {
        "user": getpass.getuser(),
        "username": os.environ.get("USERNAME", ""),
        "userdomain": os.environ.get("USERDOMAIN", ""),
        "userprofile": os.environ.get("USERPROFILE", ""),
        "computername": os.environ.get("COMPUTERNAME", ""),
    }
    runtime.emit("\n".join(f"{key}: {value}" for key, value in data.items()))
    return data
