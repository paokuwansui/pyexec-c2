import shutil

PLUGIN = {"name": "Linux 磁盘使用", "commands": ["ldf"], "platform": "linux", "risk": "R0", "description": "Python 实现的 df", "write_disk": False}


def run(runtime, args):
    path = args.get("path", "/")
    usage = shutil.disk_usage(path)
    data = {"path": path, "total": usage.total, "used": usage.used, "free": usage.free, "percent": round(usage.used / usage.total * 100, 2) if usage.total else 0}
    runtime.emit(f"{path} total={data['total']} used={data['used']} free={data['free']} ({data['percent']}%)")
    return data
