import asyncio
import json
import struct

PLUGIN = {
    "name": "TCP Listener",
    "protocol": "tcp",
    "default_port": 9001,
    "supports_payload": True,
    "description": "Length-prefixed encrypted TCP transport",
}


async def _read_exact(reader, n):
    return await reader.readexactly(n)


async def handle_client(runtime, listener, reader, writer):
    try:
        while True:
            header = await reader.readexactly(4)
            length = struct.unpack(">I", header)[0]
            if length <= 0 or length > 16 * 1024 * 1024:
                return
            body = await reader.readexactly(length)
            request = json.loads(body.decode("utf-8"))
            response = runtime.transport_poll(request)
            payload = json.dumps(response).encode("utf-8")
            writer.write(struct.pack(">I", len(payload)) + payload)
            await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError, json.JSONDecodeError):
        return
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def start(runtime, listener):
    server = await asyncio.start_server(
        lambda r, w: handle_client(runtime, listener, r, w),
        listener.get("host", "0.0.0.0"),
        int(listener["port"]),
    )
    listener["runtime"] = {"kind": "tcp", "port": listener["port"]}
    return server


async def stop(handle):
    if handle:
        handle.close()
        await handle.wait_closed()
