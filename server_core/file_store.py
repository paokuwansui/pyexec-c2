from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None
    import msvcrt


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def new_id(prefix: str = "") -> str:
    raw = uuid.uuid4().hex
    return f"{prefix}{raw}" if prefix else raw


class FileStore:
    """Small crash-conscious file database.

    JSON files are written through a temporary sibling and atomically replaced.
    The lock is process-local plus an advisory OS file lock where available.
    """

    def __init__(self, data_dir: Path):
        self.root = Path(data_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._ensure_tree()

    def _ensure_tree(self) -> None:
        for name in (
            "beacons",
            "listeners",
            "tasks",
            "queues",
            "results",
            "artifacts",
            "plugins",
            "events",
            "approvals",
            "scripts",
            "proxy",
        ):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def _safe(self, rel: str | Path) -> Path:
        path = (self.root / rel).resolve()
        if self.root.resolve() not in path.parents and path != self.root.resolve():
            raise ValueError("path escapes data directory")
        return path

    def path(self, rel: str | Path) -> Path:
        return self._safe(rel)

    def _lock_path(self, target: Path) -> Path:
        return target.with_name(target.name + ".lock")

    def locked(self, target: Path):
        store = self

        class _Ctx:
            def __enter__(self_inner):
                self_inner.handle = open(store._lock_path(target), "a+b")
                if fcntl is not None:
                    fcntl.flock(self_inner.handle.fileno(), fcntl.LOCK_EX)
                else:  # pragma: no cover
                    self_inner.handle.seek(0)
                    msvcrt.locking(self_inner.handle.fileno(), msvcrt.LK_LOCK, 1)
                return self_inner

            def __exit__(self_inner, exc_type, exc, tb):
                if fcntl is not None:
                    fcntl.flock(self_inner.handle.fileno(), fcntl.LOCK_UN)
                else:  # pragma: no cover
                    self_inner.handle.seek(0)
                    msvcrt.locking(self_inner.handle.fileno(), msvcrt.LK_UNLCK, 1)
                self_inner.handle.close()

        return _Ctx()

    def write_json(self, rel: str | Path, value: dict, *, lock: bool = True) -> Path:
        target = self.path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            context = self.locked(target) if lock else _null_context()
            with context:
                tmp = target.with_name(target.name + f".tmp-{os.getpid()}-{threading.get_ident()}")
                tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
                with open(tmp, "rb") as fh:
                    os.fsync(fh.fileno())
                os.replace(tmp, target)
                self._fsync_dir(target.parent)
        return target

    def read_json(self, rel: str | Path, default: Any = None) -> Any:
        target = self.path(rel)
        if not target.exists():
            return default
        with self._lock:
            try:
                return json.loads(target.read_text(encoding="utf-8"))
            except Exception:
                return default

    def update_json(self, rel: str | Path, mutator, default: dict | None = None) -> dict:
        target = self.path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.locked(target):
                value = self.read_json(rel, default or {})
                value = mutator(value)
                tmp = target.with_name(target.name + f".tmp-{os.getpid()}-{threading.get_ident()}")
                tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(tmp, target)
                self._fsync_dir(target.parent)
                return value

    def write_bytes(self, rel: str | Path, data: bytes) -> Path:
        target = self.path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.locked(target):
                tmp = target.with_name(target.name + f".tmp-{os.getpid()}-{threading.get_ident()}")
                tmp.write_bytes(data)
                with open(tmp, "rb") as fh:
                    os.fsync(fh.fileno())
                os.replace(tmp, target)
                self._fsync_dir(target.parent)
        return target

    def read_bytes(self, rel: str | Path) -> bytes:
        return self.path(rel).read_bytes()

    def append_jsonl(self, rel: str | Path, value: dict) -> Path:
        target = self.path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(value, ensure_ascii=False) + "\n"
        with self._lock:
            with self.locked(target):
                with open(target, "a", encoding="utf-8") as fh:
                    fh.write(line)
                    fh.flush()
                    os.fsync(fh.fileno())
        return target

    def iter_jsonl(self, rel: str | Path) -> Iterable[dict]:
        target = self.path(rel)
        if not target.exists():
            return []
        out = []
        with target.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def list_dirs(self, rel: str | Path) -> list[Path]:
        target = self.path(rel)
        if not target.exists():
            return []
        return sorted([p for p in target.iterdir() if p.is_dir()], key=lambda p: p.name)

    def list_files(self, rel: str | Path, pattern: str = "*.json") -> list[Path]:
        target = self.path(rel)
        if not target.exists():
            return []
        return sorted(target.glob(pattern), key=lambda p: p.name)

    def delete(self, rel: str | Path) -> None:
        target = self.path(rel)
        if target.is_dir():
            import shutil

            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            target.unlink(missing_ok=True)

    def _fsync_dir(self, path: Path) -> None:
        try:
            fd = os.open(path, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass

    def event(self, kind: str, payload: dict, actor: str = "system") -> dict:
        event = {
            "id": new_id("evt_"),
            "kind": kind,
            "actor": actor,
            "ts": now_iso(),
            "payload": payload,
        }
        day = time.strftime("%Y-%m-%d")
        self.append_jsonl(f"events/{day}.jsonl", event)
        return event

    def recent_events(self, limit: int = 200) -> list[dict]:
        files = sorted(self.path("events").glob("*.jsonl"), reverse=True)
        events: list[dict] = []
        for path in files:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in reversed(lines):
                if not line.strip():
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
                if len(events) >= limit:
                    return list(reversed(events))
        return list(reversed(events))


class _null_context:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False
