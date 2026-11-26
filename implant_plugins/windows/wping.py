import socket
import time

PLUGIN = {
    "name": "Windows 主机存活探测",
    "commands": ["wping"],
    "platform": "windows",
    "risk": "R1",
    "description": "Python TCP 多端口探测主机存活（无需 shell ping）",
    "write_disk": False,
}

DEFAULT_PORTS = [80, 443, 22, 445, 3389]


def run(runtime, args):
    host = str(args.get("host", ""))
    ports = args.get("ports") or DEFAULT_PORTS
    timeout = float(args.get("timeout", 0.8))
    started = time.time()
    results = []
    for port in ports:
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                results.append({"port": int(port), "open": True})
        except OSError:
            results.append({"port": int(port), "open": False})
    alive = any(item["open"] for item in results)
    data = {"host": host, "alive": alive, "results": results, "elapsed": round(time.time() - started, 3)}
    runtime.emit(f"{host} alive={alive} open={[r['port'] for r in results if r['open']]}")
    return data
