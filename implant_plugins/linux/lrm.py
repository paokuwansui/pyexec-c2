import os
import shutil

PLUGIN = {"name": "Linux 删除文件或目录", "commands": ["lrm"], "platform": "linux", "risk": "R3", "description": "Python 删除文件/目录", "write_disk": True}


def run(runtime, args):
    path = os.path.abspath(os.path.expanduser(str(args.get("path", ""))))
    recursive = bool(args.get("recursive", False))
    if os.path.isdir(path):
        if not recursive:
            os.rmdir(path)
        else:
            shutil.rmtree(path)
    elif os.path.exists(path):
        os.remove(path)
    runtime.emit(f"removed {path}")
    return {"path": path, "removed": True}
