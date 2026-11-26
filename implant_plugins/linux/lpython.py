PLUGIN = {
    "name": "Linux Python 代码片段",
    "commands": ["lpython"],
    "platform": "linux",
    "risk": "R3",
    "description": "执行服务端下发的 raw Python 代码片段",
    "write_disk": False,
}


def run(runtime, args):
    code = str(args.get("code", ""))
    result = runtime.exec_snippet(code)
    runtime.emit(runtime.stringify(result))
    return result
