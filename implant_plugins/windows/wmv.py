import os
import shutil

PLUGIN = {"name": "Windows 移动或重命名", "commands": ["wmv"], "platform": "windows", "risk": "R2", "description": "Python 移动/重命名", "write_disk": True}


def run(runtime, args):
    source = os.path.abspath(os.path.expanduser(str(args.get("source", ""))))
    target = os.path.abspath(os.path.expanduser(str(args.get("target", ""))))
    shutil.move(source, target)
    runtime.emit(f"moved {source} -> {target}")
    return {"source": source, "target": target}
