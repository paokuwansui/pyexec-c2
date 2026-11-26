import json
import os
import stat
import time

PLUGIN = {
    "name": "Windows 列目录",
    "commands": ["wls"],
    "platform": "windows",
    "risk": "R0",
    "description": "Python 实现的 Windows 目录列表",
    "write_disk": False,
}


def run(runtime, args):
    path = os.path.abspath(os.path.expanduser(args.get("path") or "."))
    items = []
    with os.scandir(path) as entries:
        for entry in entries:
            try:
                info = entry.stat(follow_symlinks=False)
                items.append({
                    "name": entry.name,
                    "kind": "dir" if entry.is_dir(follow_symlinks=False) else "file",
                    "size": info.st_size,
                    "mode": stat.filemode(info.st_mode),
                    "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(info.st_mtime)),
                    "ctime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(info.st_ctime)),
                    "atime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(info.st_atime)),
                    "path": os.path.join(path, entry.name),
                })
            except OSError as exc:
                items.append({"name": entry.name, "kind": "error", "error": str(exc)})
    items.sort(key=lambda item: (item["kind"] != "dir", item["name"].lower()))
    lines = [f"{path}  ({len(items)} entries)"]
    for item in items:
        if item.get("kind") == "error":
            lines.append(f"?????????? {item['name']}  [error: {item.get('error', '')}]")
        else:
            kind = "d" if item.get("kind") == "dir" else "-"
            mode = str(item.get("mode", "----------"))
            mode = (kind + mode[1:]) if len(mode) >= 10 else kind + "---------"
            lines.append(f"{mode} {int(item.get('size', 0)):>10}  {item.get('mtime', '')}  {item.get('name', '')}")
    runtime.emit("\n".join(lines))
    return {"path": path, "entries": items}
