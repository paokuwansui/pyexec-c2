import os
import re

PLUGIN = {"name": "Linux 文本搜索", "commands": ["lgrep"], "platform": "linux", "risk": "R1", "description": "Python 实现的 grep（递归）", "write_disk": False}


def run(runtime, args):
    path = os.path.abspath(os.path.expanduser(args.get("path") or "."))
    pattern = args.get("pattern") or ""
    flags = re.IGNORECASE if args.get("ignore_case") else 0
    regex = re.compile(pattern, flags)
    rows = []
    files = [path] if os.path.isfile(path) else [os.path.join(base, name) for base, _, names in os.walk(path) for name in names]
    for filename in files:
        try:
            with open(filename, "r", encoding="utf-8", errors="replace") as fh:
                for number, line in enumerate(fh, 1):
                    if regex.search(line):
                        rows.append({"path": filename, "line": number, "text": line.rstrip("\n")})
        except OSError:
            continue
    runtime.emit("\n".join(f"{r['path']}:{r['line']}:{r['text']}" for r in rows))
    return {"matches": rows}
