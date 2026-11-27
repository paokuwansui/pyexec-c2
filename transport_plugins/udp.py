import asyncio
import base64
import hashlib
import json
import socket
import time
import zlib

PLUGIN = {
    "name": "UDP Listener",
    "protocol": "udp",
    "default_port": 9000,
    "supports_payload": True,
    "description": "UDP request/response transport with application-layer fragmentation and retry support",
}

UDP_MAX_DATAGRAM = 1200
UDP_MAX_MESSAGE = 64 * 1024
UDP_FRAGMENT_TTL = 30.0
UDP_MAX_ASSEMBLIES = 64


def _fragment_payload(raw, kind, message_id=None):
    message_id = message_id or hashlib.sha256(f"{time.time()}:{id(raw)}".encode()).hexdigest()[:24]
    digest = hashlib.sha256(raw).hexdigest()
    total = max(1, (len(raw) + 699) // 700)
    packets = []
    for index in range(total):
        chunk = raw[index * 700:(index + 1) * 700]
        packet = {
            "v": 1,
            "t": kind,
            "m": message_id,
            "i": index,
            "n": total,
            "h": digest,
            "c": f"{zlib.crc32(chunk) & 0xffffffff:08x}",
            "d": base64.b64encode(chunk).decode("ascii"),
        }
        encoded = json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > UDP_MAX_DATAGRAM:
            raise ValueError(f"UDP fragment exceeds {UDP_MAX_DATAGRAM} bytes")
        packets.append(encoded)
    return packets


class UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, runtime, listener):
        self.runtime = runtime
        self.listener = listener
        self.transport = None
        self.assemblies = {}

    def connection_made(self, transport):
        self.transport = transport

    def _cleanup_assemblies(self):
        now = time.time()
        for key, item in list(self.assemblies.items()):
            if now - float(item.get("updated_at", 0)) > UDP_FRAGMENT_TTL:
                self.assemblies.pop(key, None)
        while len(self.assemblies) > UDP_MAX_ASSEMBLIES:
            oldest = min(self.assemblies.items(), key=lambda pair: pair[1].get("updated_at", 0))[0]
            self.assemblies.pop(oldest, None)

    def _send_fragmented(self, addr, response):
        raw = json.dumps(response, ensure_ascii=False).encode("utf-8")
        for packet in _fragment_payload(raw, "resp"):
            self.transport.sendto(packet, addr)

    def _handle_fragment(self, packet, addr):
        self._cleanup_assemblies()
        message_id = str(packet.get("m", ""))
        if not message_id:
            return
        try:
            index = int(packet.get("i", 0))
            total = int(packet.get("n", 1))
            chunk = base64.b64decode(packet.get("d", ""))
        except Exception:
            return
        if total < 1 or total > 256 or index < 0 or index >= total:
            return
        expected_crc = str(packet.get("c", ""))
        if expected_crc and expected_crc != f"{zlib.crc32(chunk) & 0xffffffff:08x}":
            return
        key = (str(addr[0]), int(addr[1]), message_id)
        state = self.assemblies.get(key)
        if not state:
            state = {
                "total": total,
                "digest": str(packet.get("h", "")),
                "chunks": {},
                "updated_at": time.time(),
                "size": 0,
            }
            self.assemblies[key] = state
        if state["total"] != total or (state["digest"] and packet.get("h") and state["digest"] != packet.get("h")):
            self.assemblies.pop(key, None)
            return
        if index not in state["chunks"]:
            state["chunks"][index] = chunk
            state["size"] += len(chunk)
        state["updated_at"] = time.time()
        if state["size"] > UDP_MAX_MESSAGE:
            self.assemblies.pop(key, None)
            return
        if len(state["chunks"]) != total:
            return
        raw = b"".join(state["chunks"][i] for i in range(total))
        self.assemblies.pop(key, None)
        if state["digest"] and hashlib.sha256(raw).hexdigest() != state["digest"]:
            return
        request = json.loads(raw.decode("utf-8"))
        response = self.runtime.transport_poll(request)
        self._send_fragmented(addr, response)

    def datagram_received(self, data, addr):
        try:
            packet = json.loads(data.decode("utf-8"))
        except Exception:
            return
        try:
            if packet.get("v") == 1 and packet.get("t") == "req":
                self._handle_fragment(packet, addr)
                return
            # Backward compatibility for old payloads that send the complete
            # request in one datagram.
            response = self.runtime.transport_poll(packet)
            self.transport.sendto(json.dumps(response, ensure_ascii=False).encode("utf-8"), addr)
        except Exception:
            # A lost/corrupt request is retried by the client. Do not kill the
            # listener because one malformed datagram arrived.
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
