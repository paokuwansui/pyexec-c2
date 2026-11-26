import asyncio
import json
import socket

PLUGIN = {
    "name": "UDP Listener",
    "protocol": "udp",
    "default_port": 9000,
    "supports_payload": True,
    "description": "UDP request/response transport",
}


class UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, runtime, listener):
        self.runtime = runtime
        self.listener = listener
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        try:
            request = json.loads(data.decode("utf-8"))
            response = self.runtime.transport_poll(request)
            self.transport.sendto(json.dumps(response).encode("utf-8"), addr)
        except Exception:
            return


async def start(runtime, listener):
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: UdpProtocol(runtime, listener),
        local_addr=(listener.get("host", "0.0.0.0"), int(listener["port"])),
    )
    listener["runtime"] = {"kind": "udp", "port": listener["port"]}
    return transport


async def stop(handle):
    if handle:
        handle.close()
