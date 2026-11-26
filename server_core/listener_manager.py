from __future__ import annotations

import asyncio
import socket
from typing import Any

from .file_store import new_id, now_iso


class ListenerError(Exception):
    pass


def detect_local_ip() -> str:
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            address = probe.getsockname()[0]
        finally:
            probe.close()
        if address and not address.startswith("127."):
            return address
    except OSError:
        pass
    try:
        address = socket.gethostbyname(socket.gethostname())
        if address and not address.startswith("127."):
            return address
    except OSError:
        pass
    return "127.0.0.1"


class ListenerManager:
    def __init__(self, runtime):
        self.runtime = runtime
        self.store = runtime.store
        self.loader = runtime.plugins
        self._handles: dict[str, Any] = {}

    def protocols(self) -> list[dict]:
        result = []
        for plugin in self.loader.list("transport"):
            manifest = plugin.get("manifest") or {}
            result.append(
                {
                    "protocol": manifest.get("protocol", plugin["name"]),
                    "name": manifest.get("name", plugin["display_name"]),
                    "default_port": manifest.get("default_port"),
                    "disabled": manifest.get("disabled", False),
                    "description": manifest.get("description", ""),
                    "file": plugin["file"],
                }
            )
        return result

    async def create(self, protocol: str, host: str, port: int, public_host: str = "", options: dict | None = None) -> dict:
        protocol = protocol.lower().strip()
        plugin = self.loader.load_module("transport", protocol)
        manifest = getattr(plugin, "PLUGIN", {})
        if manifest.get("disabled"):
            raise ListenerError(f"protocol disabled in v1: {protocol}")
        bind_host = host or "0.0.0.0"
        wildcard_hosts = {"0.0.0.0", "::", ""}
        loopbacks = {"127.0.0.1", "localhost", "::1"}
        if not public_host:
            target_host = detect_local_ip() if bind_host in wildcard_hosts else bind_host
        else:
            target_host = public_host
            if target_host in loopbacks and bind_host not in loopbacks | wildcard_hosts:
                target_host = bind_host
        listener_id = new_id("lst_")
        record = {
            "id": listener_id,
            "protocol": protocol,
            "host": bind_host,
            "port": int(port),
            "public_host": target_host,
            "options": options or {},
            "status": "starting",
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        try:
            handle = await plugin.start(self.runtime, record)
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = str(exc)
            self.store.write_json(f"listeners/{listener_id}/listener.json", record)
            raise ListenerError(f"failed to start {protocol} listener: {exc}") from exc
        self._handles[listener_id] = handle
        record["status"] = "listening"
        self.store.write_json(f"listeners/{listener_id}/listener.json", record)
        self.store.event("listener.created", {"listener_id": listener_id, "protocol": protocol, "port": int(port)})
        return record

    async def start(self, listener_id: str) -> dict:
        record = self.store.read_json(f"listeners/{listener_id}/listener.json")
        if not record:
            raise ListenerError(f"listener not found: {listener_id}")
        existing = self._handles.get(listener_id)
        if existing is not None and record.get("status") == "listening":
            return record
        protocol = record["protocol"]
        plugin = self.loader.load_module("transport", protocol)
        try:
            handle = await plugin.start(self.runtime, record)
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = str(exc)
            record["updated_at"] = now_iso()
            self.store.write_json(f"listeners/{listener_id}/listener.json", record)
            raise ListenerError(f"failed to start {protocol} listener: {exc}") from exc
        self._handles[listener_id] = handle
        record["status"] = "listening"
        record.pop("error", None)
        record.pop("stop_error", None)
        record["updated_at"] = now_iso()
        self.store.write_json(f"listeners/{listener_id}/listener.json", record)
        self.store.event("listener.started", {"listener_id": listener_id, "protocol": protocol, "port": int(record["port"])})
        return record

    async def restart(self, listener_id: str) -> dict:
        record = self.get(listener_id)
        handle = self._handles.pop(listener_id, None)
        if handle is not None:
            plugin = self.loader.load_module("transport", record["protocol"])
            try:
                await plugin.stop(handle)
                await asyncio.sleep(0.1)
            except Exception:
                pass
        return await self.start(listener_id)

    async def remove(self, listener_id: str) -> dict:
        record = self.get(listener_id)
        handle = self._handles.pop(listener_id, None)
        if handle is not None:
            try:
                plugin = self.loader.load_module("transport", record["protocol"])
                await plugin.stop(handle)
                await asyncio.sleep(0.1)
            except Exception:
                pass
        self.store.delete(f"listeners/{listener_id}")
        self.store.event("listener.removed", {"listener_id": listener_id, "protocol": record.get("protocol"), "port": record.get("port")})
        return {"id": listener_id, "protocol": record.get("protocol"), "port": record.get("port"), "removed": True}

    async def stop(self, listener_id: str) -> dict:
        record = self.store.read_json(f"listeners/{listener_id}/listener.json")
        if not record:
            raise ListenerError(f"listener not found: {listener_id}")
        handle = self._handles.pop(listener_id, None)
        plugin = self.loader.load_module("transport", record["protocol"])
        if handle is not None:
            try:
                await plugin.stop(handle)
            except Exception as exc:
                record["stop_error"] = str(exc)
        record["status"] = "stopped"
        record["updated_at"] = now_iso()
        self.store.write_json(f"listeners/{listener_id}/listener.json", record)
        self.store.event("listener.stopped", {"listener_id": listener_id, "protocol": record["protocol"]})
        return record

    def list(self) -> list[dict]:
        out = []
        for directory in self.store.list_dirs("listeners"):
            record = self.store.read_json(f"listeners/{directory.name}/listener.json")
            if record:
                bind_host = str(record.get("host", ""))
                public_host = str(record.get("public_host", ""))
                if public_host in {"127.0.0.1", "localhost", "::1"}:
                    if bind_host in {"0.0.0.0", "::", ""}:
                        record["public_host"] = detect_local_ip()
                        self.store.write_json(f"listeners/{directory.name}/listener.json", record)
                    elif bind_host not in {"127.0.0.1", "localhost", "::1"}:
                        record["public_host"] = bind_host
                        self.store.write_json(f"listeners/{directory.name}/listener.json", record)
                out.append(record)
        out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return out

    def get(self, listener_id: str) -> dict:
        record = self.store.read_json(f"listeners/{listener_id}/listener.json")
        if not record:
            raise ListenerError(f"listener not found: {listener_id}")
        return record

    async def start_all(self) -> list[dict]:
        started = []
        for record in self.list():
            if record.get("status") in {"listening", "starting"}:
                protocol = record["protocol"]
                try:
                    plugin = self.loader.load_module("transport", protocol)
                    handle = await plugin.start(self.runtime, record)
                    self._handles[record["id"]] = handle
                    record["status"] = "listening"
                    record["updated_at"] = now_iso()
                    self.store.write_json(f"listeners/{record['id']}/listener.json", record)
                    started.append(record)
                except Exception as exc:
                    record["status"] = "failed"
                    record["error"] = str(exc)
                    self.store.write_json(f"listeners/{record['id']}/listener.json", record)
        return started

    async def stop_all(self) -> None:
        # Server shutdown must not persist listeners as user-stopped.  The
        # listener config remains "listening" so start_all() can restore it.
        for listener_id, handle in list(self._handles.items()):
            record = self.store.read_json(f"listeners/{listener_id}/listener.json", default={})
            try:
                plugin = self.loader.load_module("transport", record.get("protocol", ""))
                await plugin.stop(handle)
            except Exception:
                pass
        self._handles.clear()
