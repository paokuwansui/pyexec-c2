import os

PLUGIN = {"name": "Windows 当前目录", "commands": ["wpwd"], "platform": "windows", "risk": "R0", "description": "Python 实现的当前目录", "write_disk": False}


def run(runtime, args):
    value = os.getcwd()
    runtime.emit(value)
    return {"cwd": value}
