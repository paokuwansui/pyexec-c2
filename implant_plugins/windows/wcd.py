import os

PLUGIN = {
    "name": "Windows cd 切换目录",
    "commands": ["wcd"],
    "platform": "windows",
    "risk": "R0",
    "description": "Python os.chdir 实现的当前工作目录切换",
    "write_disk": False,
}


def run(runtime, args):
    target = str(args.get("path", "")).strip()
    if not target:
        return {"error": "path is required"}
    target = os.path.abspath(os.path.expanduser(target))
    previous = os.getcwd()
    os.chdir(target)
    current = os.getcwd()
    runtime.emit(current)
    return {"previous": previous, "cwd": current}
