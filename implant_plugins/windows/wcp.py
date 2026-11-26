import os
import shutil

PLUGIN = {"name": "Windows 复制文件或目录", "commands": ["wcp"], "platform": "windows", "risk": "R2", "description": "Python 复制文件/目录", "write_disk": True}


def run(runtime, args):
    source = os.path.abspath(os.path.expanduser(str(args.get("source", ""))))
    target = os.path.abspath(os.path.expanduser(str(args.get("target", ""))))
    if os.path.isdir(source):
        shutil.copytree(source, target, dirs_exist_ok=bool(args.get("overwrite", False)))
    else:
        shutil.copy2(source, target)
    runtime.emit(f"copied {source} -> {target}")
    return {"source": source, "target": target}
