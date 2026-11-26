import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

PLUGIN = {
    "name": "Windows 端口扫描",
    "commands": ["wnmap"],
    "platform": "windows",
    "risk": "R2",
    "description": "Python 并发 TCP 端口扫描",
    "write_disk": False,
}


def parse_ports(value):
    if isinstance(value, list):
        return [int(x) for x in value]
    text = str(value or "1-1024")
    ports = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            ports.extend(range(int(start), int(end) + 1))
        else:
            ports.append(int(part))
    return sorted(set(p for p in ports if 1 <= p <= 65535))


def probe(host, port, timeout):
    started = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"port": port, "open": True, "elapsed": round(time.time() - started, 3)}
    except OSError:
        return {"port": port, "open": False, "elapsed": round(time.time() - started, 3)}


def run(runtime, args):
    host = str(args.get("host", ""))
    ports = parse_ports(args.get("ports", "1-1024"))
    timeout = float(args.get("timeout", 0.5))
    workers = min(int(args.get("workers", 100)), 500)
    open_ports = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(probe, host, port, timeout) for port in ports]
        for future in as_completed(futures):
            result = future.result()
            if result["open"]:
                open_ports.append(result)
    open_ports.sort(key=lambda item: item["port"])
    runtime.emit(f"{host} open ports: {[item['port'] for item in open_ports]}")
    return {"host": host, "scanned": len(ports), "open_ports": open_ports}
