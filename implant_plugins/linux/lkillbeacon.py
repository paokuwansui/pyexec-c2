PLUGIN = {
    "name": "Linux 终止 Beacon",
    "commands": ["lkillbeacon"],
    "platform": "linux",
    "risk": "R3",
    "description": "在任务结果返回服务端后终止当前 Beacon 进程",
    "write_disk": False,
}


def run(runtime, args):
    result = runtime.schedule_shutdown()
    runtime.emit(runtime.stringify(result))
    return result
