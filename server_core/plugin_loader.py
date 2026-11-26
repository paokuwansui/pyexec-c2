from __future__ import annotations

import ast
import hashlib
import importlib.util
import os
from pathlib import Path
from typing import Any

from .code_sanitizer import strip_comments


class PluginError(Exception):
    pass


class PluginLoader:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.dirs = {
            "implant": self.root / "implant_plugins",
            "server": self.root / "server_plugins",
            "transport": self.root / "transport_plugins",
        }
        for path in self.dirs.values():
            path.mkdir(parents=True, exist_ok=True)
        self._modules: dict[tuple[str, str], Any] = {}
        self.errors: dict[str, str] = {}

    def _path(self, kind: str, name: str) -> Path:
        if kind not in self.dirs:
            raise PluginError(f"unknown plugin kind: {kind}")
        safe_name = name.replace("\\", "/")
        path = (self.dirs[kind] / safe_name).resolve()
        if self.dirs[kind].resolve() not in path.parents:
            raise PluginError("plugin path escapes plugin directory")
        return path

    def list(self, kind: str | None = None, include_source: bool = False) -> list[dict]:
        kinds = [kind] if kind else list(self.dirs)
        result = []
        for current_kind in kinds:
            for path in sorted(self.dirs[current_kind].rglob("*.py")):
                if path.name.startswith("_"):
                    continue
                rel = path.relative_to(self.dirs[current_kind]).as_posix()
                source = path.read_text(encoding="utf-8")
                meta = {
                    "kind": current_kind,
                    "name": rel[:-3],
                    "file": rel,
                    "path": str(path),
                    "hash": hashlib.sha256(source.encode()).hexdigest(),
                    "error": self.errors.get(f"{current_kind}:{rel}"),
                }
                if include_source:
                    meta["source"] = source
                try:
                    sanitized = strip_comments(source, filename=str(path))
                    meta["stripped_hash"] = sanitized.stripped_hash
                    meta["removed_comment_tokens"] = sanitized.removed_tokens
                except Exception as exc:
                    meta["error"] = str(exc)
                manifest = self._extract_manifest(source)
                if manifest:
                    meta["manifest"] = manifest
                    meta["display_name"] = manifest.get("name", rel)
                    meta["platform"] = manifest.get("platform", "all")
                    meta["commands"] = manifest.get("commands", [])
                    meta["risk"] = manifest.get("risk", "R1")
                else:
                    meta["display_name"] = rel
                result.append(meta)
        return result

    def delete(self, kind: str, name: str) -> dict:
        safe_name = name.strip().replace("\\", "/")
        if safe_name.endswith(".py"):
            safe_name = safe_name[:-3]
        path = self._path(kind, safe_name + ".py")
        if not path.exists():
            raise PluginError(f"plugin not found: {kind}/{safe_name}")
        path.unlink()
        self._modules.pop((kind, safe_name), None)
        return {"kind": kind, "name": safe_name, "deleted": True}

    def _extract_manifest(self, source: str) -> dict | None:
        try:
            tree = ast.parse(source)
            for node in tree.body:
                if isinstance(node, ast.Assign) and len(node.targets) == 1:
                    target = node.targets[0]
                    if isinstance(target, ast.Name) and target.id == "PLUGIN":
                        value = ast.literal_eval(node.value)
                        return value if isinstance(value, dict) else None
        except Exception as exc:
            key = f"manifest:{hashlib.sha256(source.encode()).hexdigest()[:12]}"
            self.errors[key] = str(exc)
        return None


    def create(self, kind: str, name: str, source: str | None = None, command: str = "", overwrite: bool = False, platform: str = "") -> dict:
        if kind not in {"implant", "server", "transport"}:
            raise PluginError(f"unsupported plugin kind: {kind}")
        if not name or not name.strip():
            raise PluginError("plugin name is required")
        safe_name = name.strip().replace("\\", "/")
        if safe_name.endswith(".py"):
            safe_name = safe_name[:-3]
        path = self._path(kind, safe_name + ".py")
        if path.exists() and not overwrite:
            raise PluginError(f"plugin already exists: {kind}/{safe_name}")
        if source is None or not str(source).strip():
            source = self.template(kind, safe_name, command, platform)
        result = self.save_source(kind, safe_name, source)
        result["name"] = safe_name
        result["file"] = (safe_name + ".py").replace("\\", "/")
        return result

    def template(self, kind: str, name: str, command: str = "", platform: str = "") -> str:
        stem = name.split("/")[-1]
        command = command.strip() or f"{'plugin' if kind == 'implant' else 'server'}.{stem.replace('-', '_')}"
        display = stem.replace("_", " ").replace("-", " ")
        if kind == "implant":
            return f"""PLUGIN = {{
    "name": "{display}",
    "commands": ["{command}"],
    "platform": "{platform or 'all'}",
    "risk": "R1",
    "description": "new implant plugin",
    "write_disk": False,
}}


def run(runtime, args):
    runtime.emit("hello from {command}")
    return {{"ok": True, "command": "{command}", "args": args}}
"""
        if kind == "server":
            return f"""PLUGIN = {{
    "name": "{display}",
    "commands": ["{command}"],
    "platform": "all",
    "risk": "R0",
    "description": "new server plugin",
}}


def handle(runtime, args):
    return {{"ok": True, "command": "{command}", "args": args}}
"""
        return f"""PLUGIN = {{
    "name": "{display}",
    "commands": ["{command}"],
    "platform": "all",
    "risk": "R1",
    "description": "new transport plugin",
}}


async def start(runtime, record):
    raise NotImplementedError("implement transport listener")


async def stop(handle):
    return None
"""


    def read_source(self, kind: str, name: str) -> str:
        path = self._path(kind, name if name.endswith(".py") else name + ".py")
        if not path.exists():
            raise PluginError(f"plugin not found: {kind}/{name}")
        return path.read_text(encoding="utf-8")

    def save_source(self, kind: str, name: str, source: str) -> dict:
        path = self._path(kind, name if name.endswith(".py") else name + ".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        result = strip_comments(source, filename=str(path))
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(source, encoding="utf-8")
        os.replace(tmp, path)
        if kind == "implant":
            self._modules.pop((kind, path.stem), None)
            return {
                "kind": kind,
                "name": path.stem,
                "file": path.relative_to(self.dirs[kind]).as_posix(),
                "stripped_hash": result.stripped_hash,
                "reloaded": True,
                "validation": "syntax-ok",
            }
        self.reload(kind, name)
        return {
            "kind": kind,
            "name": path.stem,
            "file": path.relative_to(self.dirs[kind]).as_posix(),
            "stripped_hash": result.stripped_hash,
            "reloaded": True,
        }

    def load_module(self, kind: str, name: str):
        path = self._path(kind, name if name.endswith(".py") else name + ".py")
        if not path.exists():
            raise PluginError(f"plugin not found: {kind}/{name}")
        key = (kind, path.stem)
        if key in self._modules:
            return self._modules[key]
        module_name = f"pyexec2_{kind}_{path.stem}_{abs(hash(str(path)))}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise PluginError(f"cannot load plugin {path}")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            self.errors[f"{kind}:{path.stem}"] = str(exc)
            raise PluginError(f"failed to load {kind}/{name}: {exc}") from exc
        manifest = getattr(module, "PLUGIN", None)
        if not isinstance(manifest, dict):
            raise PluginError(f"{kind}/{name} missing PLUGIN manifest")
        self._modules[key] = module
        return module

    def reload(self, kind: str, name: str):
        stem = name if not name.endswith(".py") else name[:-3]
        self._modules.pop((kind, stem), None)
        if kind == "implant":
            # Implant plugins execute on targets, not on the server. Validate
            # syntax and manifest, but never import them here.
            source = self.read_source(kind, stem)
            sanitized = strip_comments(source, filename=stem)
            manifest = self._extract_manifest(source)
            if manifest is None:
                raise PluginError(f"implant plugin {stem} missing PLUGIN manifest")
            return {"kind": kind, "name": stem, "reloaded": True, "stripped_hash": sanitized.stripped_hash}
        return self.load_module(kind, name)

    def reload_all(self):
        errors = {}
        for kind in self.dirs:
            for path in self.dirs[kind].rglob("*.py"):
                if path.name.startswith("_"):
                    continue
                name = path.relative_to(self.dirs[kind]).as_posix()[:-3]
                try:
                    self.reload(kind, name)
                except Exception as exc:
                    errors[f"{kind}:{name}"] = str(exc)
        self.errors.update(errors)
        return errors
