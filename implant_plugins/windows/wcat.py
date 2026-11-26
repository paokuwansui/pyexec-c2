import os

PLUGIN = {
    "name": "Windows 读文件",
    "commands": ["wcat"],
    "platform": "windows",
    "risk": "R1",
    "description": "Python 实现的 Windows type 等效读文件",
    "write_disk": False,
}


def run(runtime, args):
    import base64
    path = os.path.abspath(os.path.expanduser(args.get("path") or ""))
    offset = int(args.get("offset", 0))
    length = int(args.get("length", 16 * 1024 * 1024))
    with open(path, "rb") as fh:
        fh.seek(offset)
        data = fh.read(length)
        eof = not fh.read(1)
    try:
        text = data.decode(args.get("encoding", "utf-8"))
        binary = False
    except UnicodeDecodeError:
        text = ""
        binary = True
    runtime.emit(f"{len(data)} bytes read" if not binary else f"{len(data)} binary bytes read")
    return {
        "path": path,
        "offset": offset,
        "length": len(data),
        "eof": eof,
        "binary": binary,
        "content_b64": base64.b64encode(data).decode() if binary else "",
        "text": text,
    }
