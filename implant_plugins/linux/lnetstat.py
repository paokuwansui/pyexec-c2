import os

PLUGIN = {
    "name": "Linux 网络连接",
    "commands": ["lnetstat"],
    "platform": "linux",
    "risk": "R1",
    "description": "读取 /proc/net/tcp/udp 连接",
    "write_disk": False,
}

_STATES = {"01": "ESTABLISHED", "02": "SYN_SENT", "06": "TIME_WAIT", "0A": "LISTEN", "07": "CLOSE"}


def _decode_addr(value):
    host, port = value.split(":")
    ip = ".".join(str(int(host[i:i + 2], 16)) for i in (6, 4, 2, 0))
    return ip, int(port, 16)


def run(runtime, args):
    rows = []
    for proto, path in (("tcp", "/proc/net/tcp"), ("tcp6", "/proc/net/tcp6"), ("udp", "/proc/net/udp"), ("udp6", "/proc/net/udp6")):
        if not os.path.exists(path):
            continue
        with open(path, "r") as fh:
            next(fh, None)
            for line in fh:
                parts = line.split()
                if len(parts) < 10:
                    continue
                try:
                    local_ip, local_port = _decode_addr(parts[1])
                    remote_ip, remote_port = _decode_addr(parts[2])
                    rows.append({
                        "proto": proto,
                        "local": f"{local_ip}:{local_port}",
                        "remote": f"{remote_ip}:{remote_port}",
                        "state": _STATES.get(parts[3], parts[3]),
                        "uid": parts[7],
                        "inode": parts[9],
                    })
                except Exception:
                    continue
    runtime.emit("\n".join(f"{r['proto']:<5} {r['local']:<22} {r['remote']:<22} {r['state']}" for r in rows))
    return {"connections": rows}
