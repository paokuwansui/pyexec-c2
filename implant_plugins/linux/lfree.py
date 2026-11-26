PLUGIN = {"name": "Linux 内存信息", "commands": ["lfree"], "platform": "linux", "risk": "R0", "description": "Python 读取 /proc/meminfo", "write_disk": False}


def run(runtime, args):
    info = {}
    with open("/proc/meminfo", "r") as fh:
        for line in fh:
            key, value = line.split(":", 1)
            info[key.strip()] = value.strip()
    runtime.emit("\n".join(f"{key}: {value}" for key, value in info.items()))
    return {"meminfo": info}
