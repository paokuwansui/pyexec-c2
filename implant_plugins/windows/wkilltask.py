PLUGIN = {
    "name": "Windows 终止运行任务",
    "commands": ["wkilltask"],
    "platform": "windows",
    "risk": "R2",
    "description": "强制终止 Beacon 上正在运行的指定任务",
    "write_disk": False,
}


def run(runtime, args):
    task_id = str(args.get("task_id", "")).strip()
    if not task_id:
        return {"error": "task_id is required"}
    current = (runtime.task or {}).get("id")
    if task_id == current:
        return {"error": "cannot cancel the running killtask plugin itself"}
    result = runtime.control("cancel_task", {"task_id": task_id})
    if result.get("ok"):
        runtime.emit(f"cancel requested: {task_id}")
    else:
        runtime.emit(f"cancel failed: {result.get('error', 'unknown error')}")
    return result
