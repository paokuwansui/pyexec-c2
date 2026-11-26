import json
import platform

PLUGIN = {
    "name": "服务端报告",
    "commands": ["server.report"],
    "platform": "all",
    "risk": "R0",
    "description": "生成服务端运行摘要并演示服务端插件运行时访问",
}


def handle(runtime, args):
    mode = str(args.get("mode", "summary"))
    data = {
        "mode": mode,
        "workdir": str(runtime.settings.workdir),
        "approval_mode": runtime.approval_mode,
        "beacons": len(runtime.list_beacons()),
        "listeners": len(runtime.listeners.list()),
        "tasks": len(runtime.tasks.list_tasks(limit=10000)),
        "plugins": len(runtime.plugins.list()),
        "platform": platform.platform(),
    }
    if mode == "json":
        return data
    runtime.store.event("server.report.generated", {"mode": mode}, actor="server_plugin")
    return {"report": data, "text": json.dumps(data, ensure_ascii=False, indent=2)}
