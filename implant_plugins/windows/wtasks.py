PLUGIN = {
    "name": "Windows 运行中任务",
    "commands": ["wtasks"],
    "platform": "windows",
    "risk": "R1",
    "description": "查看 Beacon 当前正在运行的任务",
    "write_disk": False,
}


def run(runtime, args):
    result = runtime.control("list_tasks", {})
    tasks = result if isinstance(result, list) else []
    lines = [f"{len(tasks)} running task(s)"]
    for item in tasks:
        lines.append(
            f"{item.get('task_id', '')}  "
            f"plugin={item.get('plugin') or item.get('display') or '-'}  "
            f"elapsed={item.get('elapsed', 0)}s  "
            f"mode={item.get('mode', 'plugin')}"
        )
    runtime.emit("\n".join(lines))
    return {"tasks": tasks}
