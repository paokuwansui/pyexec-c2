PLUGIN = {
    "name": "Windows 独立 Fork",
    "commands": ["wfork"],
    "platform": "windows",
    "risk": "R2",
    "description": "复制出一个参数完全相同的独立 Beacon 进程；两个进程互不依赖",
    "write_disk": False,
}


def run(runtime, args):
    result = runtime.fork_independent()
    runtime.emit(runtime.stringify(result))
    return result
