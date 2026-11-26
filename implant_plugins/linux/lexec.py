import subprocess

PLUGIN = {"name": "Linux Bash 执行", "commands": ["lexec"], "platform": "linux", "risk": "R3", "description": "显式通过 /bin/bash -lc 执行命令（危险能力）", "write_disk": False}


def run(runtime, args):
    command = str(args.get("command", ""))
    if not command:
        return {"error": "command is required"}
    timeout = args.get("timeout")
    proc = subprocess.Popen(["/bin/bash", "-lc", command], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    runtime.track_process(proc)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    finally:
        runtime.untrack_process(proc)
    output = stdout + stderr
    runtime.emit(output)
    return {"command": command, "returncode": proc.returncode, "stdout": stdout, "stderr": stderr}
