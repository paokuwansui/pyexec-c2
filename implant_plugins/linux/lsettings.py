PLUGIN = {
    "name": "Linux 回连参数设置",
    "commands": ["lsettings"],
    "platform": "linux",
    "risk": "R1",
    "description": "按需修改快端、慢端、当前间隔、抖动、聚合和并发；未指定的参数保持不变",
    "write_disk": False,
}

ALIASES = {
    "fast": "fast_interval",
    "min": "fast_interval",
    "fast_interval": "fast_interval",
    "slow": "slow_interval",
    "max": "slow_interval",
    "slow_interval": "slow_interval",
    "current": "current_interval",
    "current_interval": "current_interval",
    "jitter": "jitter",
    "finish": "finish_delay",
    "aggregate": "finish_delay",
    "finish_delay": "finish_delay",
    "concurrency": "max_concurrent_tasks",
    "workers": "max_concurrent_tasks",
    "max_concurrent_tasks": "max_concurrent_tasks",
}


def run(runtime, args):
    payload = {}
    for key, value in (args or {}).items():
        mapped = ALIASES.get(str(key))
        if mapped and value not in (None, ""):
            payload[mapped] = value
    if not payload:
        return {"error": "no settings supplied; use --min, --max, --current, --jitter, --finish or --concurrency"}
    result = runtime.control("set_runtime_settings", payload)
    runtime.emit(runtime.stringify(result))
    return result
