import base64
import hashlib
import os

PLUGIN = {
    "name": "Linux dd 分块读写",
    "commands": ["ldd"],
    "platform": "linux",
    "risk": "R2",
    "description": "Python 实现的 dd 分块读写，供文件上传下载和命令行使用",
    "write_disk": True,
}


def run(runtime, args):
    path = os.path.abspath(os.path.expanduser(str(args.get("path", ""))))
    op = str(args.get("op", "read")).lower()
    offset = int(args.get("offset", 0))
    if op == "read":
        length = int(args.get("length", 1024 * 1024))
        with open(path, "rb") as fh:
            fh.seek(offset)
            data = fh.read(length)
            eof = not fh.read(1)
        runtime.emit(f"dd read {offset}:{offset + len(data)} of {path}")
        return {
            "path": path,
            "offset": offset,
            "length": len(data),
            "eof": eof,
            "content_b64": base64.b64encode(data).decode(),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    if op == "write":
        data = base64.b64decode(args.get("content_b64", ""))
        mode = str(args.get("mode", "write"))
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if mode == "start":
            fh = open(path, "wb")
        elif mode == "append":
            fh = open(path, "ab")
        else:
            fh = open(path, "r+b" if os.path.exists(path) else "wb")
        with fh:
            if mode == "write":
                fh.seek(offset)
            fh.write(data)
        runtime.emit(f"dd write {len(data)} bytes at {offset} to {path}")
        return {"path": path, "offset": offset, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return {"error": f"dd: unsupported op {op}"}
