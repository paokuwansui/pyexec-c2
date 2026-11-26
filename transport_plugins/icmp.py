PLUGIN = {
    "name": "ICMP Listener",
    "protocol": "icmp",
    "default_port": 0,
    "supports_payload": False,
    "disabled": True,
    "description": "ICMP is deferred for v1",
}


async def start(runtime, listener):
    raise RuntimeError("ICMP is not implemented in v1")


async def stop(handle):
    return None
