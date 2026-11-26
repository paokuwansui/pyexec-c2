import base64
import hashlib
import os

PLUGIN = {
    "name": "Windows tee 写入文件",
    "commands": ["wtee"],
    "platform": "windows",
    "risk": "R2",
    "description": "Python 实现的 tee 写入",
    "write_disk": True,
}


def run(runtime, args):
    path = os.path.abspath(os.path.expanduser(str(args.get("path", ""))))
    mode = args.get("mode", "overwrite")
    if args.get("content_b64") is not None:
        data = base64.b64decode(args["content_b64"])
    else:
        data = str(args.get("content", "")).encode(args.get("encoding", "utf-8"))
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    flag = "ab" if mode == "append" else "wb"
    with open(path, flag) as fh:
        fh.write(data)
    digest = hashlib.sha256(open(path, "rb").read()).hexdigest() if os.path.getsize(path) <= 16 * 1024 * 1024 else ""
    runtime.emit(f"wrote {len(data)} bytes to {path}")
    return {"path": path, "bytes": len(data), "sha256": digest}
