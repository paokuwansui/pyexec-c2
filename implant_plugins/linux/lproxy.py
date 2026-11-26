import base64
import socket

PLUGIN = {
    "name": "Linux 反向代理会话",
    "commands": ["lproxy"],
    "platform": "linux",
    "risk": "R3",
    "description": "为服务端 SOCKS5 网关提供目标端 socket 会话",
    "write_disk": False,
}


def _sessions(runtime):
    if "proxy_sessions" not in runtime.shared:
        runtime.shared["proxy_sessions"] = {}
    return runtime.shared["proxy_sessions"]


def run(runtime, args):
    op = args.get("op", "")
    sessions = _sessions(runtime)
    if op == "open":
        sock = socket.create_connection((args["host"], int(args["port"])), timeout=10)
        sock.settimeout(1.0)
        sid = args["session_id"]
        sessions[sid] = sock
        runtime.emit(f"proxy open {args['host']}:{args['port']} session={sid}")
        return {"session_id": sid, "connected": True}
    if op == "read":
        sid = args["session_id"]
        sock = sessions.get(sid)
        if not sock:
            return {"eof": True, "error": "unknown session"}
        try:
            data = sock.recv(int(args.get("size", 65536)))
            if not data:
                return {"eof": True, "data_b64": ""}
            return {"eof": False, "data_b64": base64.b64encode(data).decode(), "bytes": len(data)}
        except socket.timeout:
            return {"eof": False, "timeout": True, "data_b64": ""}
    if op == "write":
        sid = args["session_id"]
        sock = sessions.get(sid)
        if not sock:
            return {"error": "unknown session"}
        data = base64.b64decode(args.get("data_b64", ""))
        sock.sendall(data)
        return {"bytes": len(data)}
    if op == "close":
        sid = args["session_id"]
        sock = sessions.pop(sid, None)
        if sock:
            try:
                sock.close()
            except Exception:
                pass
        return {"closed": True}
    return {"error": f"unknown proxy op: {op}"}
