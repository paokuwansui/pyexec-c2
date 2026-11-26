import asyncio
import json

PLUGIN = {
    "name": "HTTP Listener",
    "protocol": "http",
    "default_port": 9002,
    "supports_payload": True,
    "description": "Minimal HTTP/1.1 encrypted transport",
}


async def _read_request(reader):
    data = await reader.readuntil(b"\r\n\r\n")
    head, body = data.split(b"\r\n\r\n", 1)
    lines = head.decode("latin1").split("\r\n")
    method, path, _ = lines[0].split(" ", 2)
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    length = int(headers.get("content-length", "0"))
    if length < 0 or length > 16 * 1024 * 1024:
        raise ValueError("request body too large")
    while len(body) < length:
        body += await reader.read(length - len(body))
    return method, path, headers, body


async def handle_client(runtime, listener, reader, writer):
    try:
        method, path, headers, body = await _read_request(reader)
        if method != "POST" or path not in {"/poll", "/"}:
            writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await writer.drain()
            return
        request = json.loads(body.decode("utf-8"))
        response = runtime.transport_poll(request)
        payload = json.dumps(response).encode("utf-8")
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            + b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(payload)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
            + payload
        )
        await writer.drain()
    except Exception:
        try:
            writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await writer.drain()
        except Exception:
            pass
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
    listener["runtime"] = {"kind": "http", "port": listener["port"]}
    return server


async def stop(handle):
    if handle:
        handle.close()
        await handle.wait_closed()
