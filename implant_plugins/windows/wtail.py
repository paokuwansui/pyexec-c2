import os
from collections import deque

PLUGIN = {"name": "Windows 读取文件尾部", "commands": ["wtail"], "platform": "windows", "risk": "R1", "description": "Python 实现的 tail", "write_disk": False}


def run(runtime, args):
    path = os.path.abspath(os.path.expanduser(str(args.get("path", ""))))
    lines = max(1, int(args.get("lines", 20)))
    with open(path, "r", encoding=args.get("encoding", "utf-8"), errors="replace") as fh:
        tail = list(deque(fh, maxlen=lines))
    text = "".join(tail)
    runtime.emit(text)
    return {"path": path, "lines": len(tail), "text": text}
