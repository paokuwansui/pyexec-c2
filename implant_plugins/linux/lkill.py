import os
import signal

PLUGIN = {"name": "Linux 终止进程", "commands": ["lkill"], "platform": "linux", "risk": "R3", "description": "Python os.kill 终止进程", "write_disk": False}


def run(runtime, args):
    pid = int(args.get("pid"))
    sig = int(args.get("signal", signal.SIGTERM))
    os.kill(pid, sig)
    runtime.emit(f"sent signal {sig} to pid {pid}")
    return {"pid": pid, "signal": sig}
