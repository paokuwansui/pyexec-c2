import os
import shutil
import string

PLUGIN = {"name": "Windows df 磁盘列表", "commands": ["wdf"], "platform": "windows", "risk": "R0", "description": "Python 实现的磁盘列表", "write_disk": False}


def run(runtime, args):
    rows = []
    for letter in string.ascii_uppercase:
        path = f"{letter}:\\"
        if os.path.exists(path):
            try:
                usage = shutil.disk_usage(path)
                rows.append({"path": path, "total": usage.total, "used": usage.used, "free": usage.free})
            except OSError:
                continue
    runtime.emit("\n".join(f"{r['path']} total={r['total']} used={r['used']} free={r['free']}" for r in rows))
    return {"drives": rows}
