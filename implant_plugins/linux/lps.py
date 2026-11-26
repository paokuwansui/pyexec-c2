import os

PLUGIN = {
    "name": "Linux 进程列表",
    "commands": ["lps"],
    "platform": "linux",
    "risk": "R0",
    "description": "读取 /proc 进程列表",
    "write_disk": False,
}


def run(runtime, args):
    rows = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            with open(f"/proc/{pid}/comm", "r") as fh:
                comm = fh.read().strip()
            status = {}
            with open(f"/proc/{pid}/status", "r") as fh:
                for line in fh:
                    if ":" in line:
                        key, value = line.split(":", 1)
                        status[key.strip()] = value.strip()
            rows.append({
                "pid": pid,
                "ppid": int(status.get("PPid", "0")),
                "user": status.get("Uid", "").split()[0] if status.get("Uid") else "",
                "name": comm,
                "state": status.get("State", ""),
            })
        except (OSError, ValueError):
            continue
    rows.sort(key=lambda row: row["pid"])
    runtime.emit("\n".join(f"{r['pid']:>7} {r['ppid']:>7} {r['user']:>8} {r['name']} {r['state']}" for r in rows))
    return {"processes": rows}
