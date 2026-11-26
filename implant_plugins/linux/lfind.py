import fnmatch
import os

PLUGIN = {"name": "Linux 文件查找", "commands": ["lfind"], "platform": "linux", "risk": "R1", "description": "Python 实现的 find（按 glob）", "write_disk": False}


def run(runtime, args):
    root = os.path.abspath(os.path.expanduser(args.get("path") or "."))
    pattern = args.get("pattern") or "*"
    limit = int(args.get("limit", 2000))
    rows = []
    for base, dirs, files in os.walk(root):
        for name in dirs + files:
            if fnmatch.fnmatch(name, pattern):
                rows.append(os.path.join(base, name))
                if len(rows) >= limit:
                    break
        if len(rows) >= limit:
            break
    runtime.emit("\n".join(rows))
    return {"root": root, "pattern": pattern, "paths": rows, "truncated": len(rows) >= limit}
