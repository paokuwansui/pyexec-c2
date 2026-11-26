import asyncio
import ssl
import pathlib

from transport_plugins.http import handle_client

PLUGIN = {
    "name": "HTTPS Listener",
    "protocol": "https",
    "default_port": 9003,
    "supports_payload": True,
    "description": "HTTP over TLS encrypted transport",
}


def _ssl_context(runtime):
    cert = pathlib.Path(runtime.settings.workdir) / "config" / "server.crt"
    key = pathlib.Path(runtime.settings.workdir) / "config" / "server.key"
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    return context


async def start(runtime, listener):
    server = await asyncio.start_server(
        lambda r, w: handle_client(runtime, listener, r, w),
        listener.get("host", "0.0.0.0"),
        int(listener["port"]),
        ssl=_ssl_context(runtime),
    )
    listener["runtime"] = {"kind": "https", "port": listener["port"]}
    return server


async def stop(handle):
    if handle:
        handle.close()
        await handle.wait_closed()
