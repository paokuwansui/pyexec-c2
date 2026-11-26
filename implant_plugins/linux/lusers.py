import pwd

PLUGIN = {"name": "Linux 用户列表", "commands": ["lusers"], "platform": "linux", "risk": "R1", "description": "Python 读取 /etc/passwd 用户列表", "write_disk": False}


def run(runtime, args):
    rows = [{"name": p.pw_name, "uid": p.pw_uid, "gid": p.pw_gid, "home": p.pw_dir, "shell": p.pw_shell} for p in pwd.getpwall()]
    runtime.emit("\n".join(f"{r['name']:<20} {r['uid']:<8} {r['gid']:<8} {r['home']}" for r in rows))
    return {"users": rows}
