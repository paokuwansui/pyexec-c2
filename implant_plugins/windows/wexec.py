import subprocess

PLUGIN = {"name": "Windows PowerShell 执行", "commands": ["wexec"], "platform": "windows", "risk": "R3", "description": "显式通过 PowerShell 执行命令（危险能力）", "write_disk": False}


def run(runtime, args):
    command = str(args.get("command", ""))
    if not command:
        return {"error": "command is required"}
    shell = str(args.get("shell", "powershell")).lower()
    if shell == "cmd":
        argv = ["cmd.exe", "/d", "/s", "/c", command]
    else:
        argv = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    runtime.track_process(proc)
    try:
        stdout, stderr = proc.communicate(timeout=args.get("timeout"))
    finally:
        runtime.untrack_process(proc)
    output = stdout + stderr
    runtime.emit(output)
    return {"command": command, "shell": shell, "returncode": proc.returncode, "stdout": stdout, "stderr": stderr}
