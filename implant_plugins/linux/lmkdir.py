import os

PLUGIN = {"name": "Linux 创建目录", "commands": ["lmkdir"], "platform": "linux", "risk": "R2", "description": "Python 递归创建目录", "write_disk": True}


def run(runtime, args):
    path = os.path.abspath(os.path.expanduser(str(args.get("path", ""))))
    os.makedirs(path, exist_ok=bool(args.get("exist_ok", True)))
    runtime.emit(path)
    return {"path": path, "created": True}
