import os

PLUGIN = {"name": "Linux 当前目录", "commands": ["lpwd"], "platform": "linux", "risk": "R0", "description": "Python 实现的 pwd", "write_disk": False}


def run(runtime, args):
    value = os.getcwd()
    runtime.emit(value)
    return {"cwd": value}
