from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import hashlib
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import uvicorn
from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "web" / "dist"
LOCAL_DATA = ROOT / "local_data"
HISTORY_DIR = LOCAL_DATA / "history"
TEMPLATE_DIR = LOCAL_DATA / "templates"
AI_AGENT_DIR = LOCAL_DATA / "ai_agent"
AI_CONFIG_PATH = AI_AGENT_DIR / "config.json"
AI_CONFIG_KEY_PATH = AI_AGENT_DIR / "config.key"
AI_MEMORY_PATH = AI_AGENT_DIR / "memory.json"
NOTEBOOK_DIR = LOCAL_DATA / "notebooks"
NOTEBOOKS_PATH = NOTEBOOK_DIR / "notebooks.json"
DEFAULT_REDTEAM_NOTES_DIR = ROOT / "default_redteam_notes"
DEFAULT_REDTEAM_MANIFEST = DEFAULT_REDTEAM_NOTES_DIR / "manifest.json"
DEFAULT_REDTEAM_MARKER = NOTEBOOK_DIR / ".default_redteam_seeded_v1"
DEFAULT_REDTEAM_SEED_VERSION = 2


def load_config(args) -> tuple[str, str]:
    config_path = Path(args.config)
    cfg = {}
    if config_path.exists():
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    server = args.server or cfg.get("server") or "http://127.0.0.1:18080"
    token = args.token or cfg.get("token") or ""
    return server.rstrip("/"), token


def create_local_app(server: str, token: str, config_path: str = "config.json") -> FastAPI:
    app = FastAPI(docs_url=None, openapi_url=None, redoc_url=None)
    cfg_path = Path(config_path).resolve()
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    AI_AGENT_DIR.mkdir(parents=True, exist_ok=True)
    NOTEBOOK_DIR.mkdir(parents=True, exist_ok=True)

    def safe_template_name(value: str) -> str:
        name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
        name = name.strip("._-") or f"template_{int(time.time())}"
        if name.endswith(".py"):
            name = name[:-3]
        return name

    def template_record(path: Path) -> dict:
        stat = path.stat()
        return {
            "name": path.stem,
            "file": path.name,
            "source": path.read_text(encoding="utf-8", errors="replace"),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(stat.st_mtime)),
            "bytes": stat.st_size,
        }

    def active_config() -> tuple[str, str]:
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                return str(cfg.get("server", server)).rstrip("/"), str(cfg.get("token", token))
            except Exception:
                pass
        return server.rstrip("/"), token

    def require_local_auth(request: Request) -> None:
        _, active_token = active_config()
        supplied = request.headers.get("x-pyexec-auth", "")
        if not active_token or not supplied or not hmac.compare_digest(supplied, active_token):
            raise HTTPException(status_code=401, detail=None)

    @app.get("/api/config")
    def config():
        active_server, _ = active_config()
        # Never return the control token to a caller. The operator enters it
        # in the first-visit connection screen and the browser keeps it only
        # in sessionStorage for local API calls.
        return {"server": active_server}

    def normalize_compat_mode(value) -> str:
        if isinstance(value, bool):
            return "other" if value else "openai"
        value = str(value or "openai").lower()
        aliases = {"anthropic": "claude", "claude-code": "claude", "gemini": "openai", "google": "openai", "other": "openai"}
        value = aliases.get(value, value)
        return value if value in {"openai", "claude"} else "openai"

    def ai_fernet() -> Fernet:
        AI_AGENT_DIR.mkdir(parents=True, exist_ok=True)
        if AI_CONFIG_KEY_PATH.exists():
            key = AI_CONFIG_KEY_PATH.read_bytes().strip()
        else:
            key = Fernet.generate_key()
            AI_CONFIG_KEY_PATH.write_bytes(key)
            try:
                AI_CONFIG_KEY_PATH.chmod(0o600)
            except OSError:
                pass
        return Fernet(key)

    def default_ai_config() -> dict:
        return {"base_url": "https://api.deepseek.com", "api_key": "", "model": "deepseek-flash", "thinking": "max", "compat_mode": "openai", "approval_mode": "ai", "role_prompt": "你是 PyExec2 的内置 C2 Agent。优先使用只读操作确认状态；执行写操作前说明目的；以实际工具返回结果为准，不要编造。"}

    def load_ai_config() -> dict:
        if AI_CONFIG_PATH.exists():
            try:
                stored = json.loads(AI_CONFIG_PATH.read_text(encoding="utf-8"))
                if isinstance(stored, dict) and stored.get("ciphertext"):
                    plaintext = ai_fernet().decrypt(str(stored["ciphertext"]).encode("ascii"))
                    return json.loads(plaintext.decode("utf-8"))
                if isinstance(stored, dict) and stored.get("base_url") is not None:
                    # Migrate legacy plaintext config to encrypted-at-rest format.
                    save_ai_config(stored)
                    return stored
            except (InvalidToken, ValueError, OSError, json.JSONDecodeError):
                pass
        return default_ai_config()

    def save_ai_config(config: dict) -> None:
        AI_AGENT_DIR.mkdir(parents=True, exist_ok=True)
        plaintext = json.dumps(config, ensure_ascii=False).encode("utf-8")
        ciphertext = ai_fernet().encrypt(plaintext).decode("ascii")
        tmp_path = AI_CONFIG_PATH.with_suffix(".tmp")
        tmp_path.write_text(json.dumps({"version": 1, "alg": "fernet", "ciphertext": ciphertext}, ensure_ascii=False), encoding="utf-8")
        try:
            tmp_path.chmod(0o600)
        except OSError:
            pass
        os.replace(tmp_path, AI_CONFIG_PATH)

    def normalize_memory_item(item: dict) -> dict:
        raw_text = str(item.get("text") or item.get("content") or "")
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or raw_text).strip()
        if not title:
            title = (content.splitlines()[0] if content else "未命名记忆")[:120]
        return {
            "id": str(item.get("id") or uuid.uuid4().hex),
            "title": title[:200],
            "content": content[:12000],
            "created_at": str(item.get("created_at") or time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())),
            **({"updated_at": item["updated_at"]} if item.get("updated_at") else {}),
        }

    def load_ai_memory() -> list[dict]:
        if AI_MEMORY_PATH.exists():
            try:
                data = json.loads(AI_MEMORY_PATH.read_text(encoding="utf-8"))
                return [normalize_memory_item(item) for item in (data.get("items") or []) if isinstance(item, dict)]
            except Exception:
                pass
        return []

    def save_ai_memory(items: list[dict]) -> None:
        normalized = [normalize_memory_item(item) for item in items[:200]]
        AI_MEMORY_PATH.write_text(json.dumps({"items": normalized}, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            AI_MEMORY_PATH.chmod(0o600)
        except OSError:
            pass

    def ai_config_public(config: dict) -> dict:
        key = str(config.get("api_key", ""))
        return {
            "base_url": config.get("base_url", ""),
            "model": config.get("model", "deepseek-flash"),
            "thinking": config.get("thinking", "max"),
            "compat_mode": normalize_compat_mode(config.get("compat_mode", "openai")),
            "approval_mode": str(config.get("approval_mode") or "ai") if str(config.get("approval_mode") or "ai") in {"human", "ai", "none"} else "ai",
            "role_prompt": config.get("role_prompt", ""),
            "api_key_set": bool(key),
            "api_key_hint": (key[-4:] if key else ""),
            "memory_count": len(load_ai_memory()),
        }

    @app.get("/api/ai-agent/config")
    def ai_agent_config(request: Request):
        require_local_auth(request)
        return {"ok": True, **ai_config_public(load_ai_config())}

    @app.post("/api/ai-agent/config")
    async def ai_agent_save_config(request: Request):
        require_local_auth(request)
        body = await request.json()
        config = load_ai_config()
        for field in ("base_url", "model", "thinking", "role_prompt"):
            if field in body:
                config[field] = str(body.get(field, ""))
        if "approval_mode" in body:
            config["approval_mode"] = str(body.get("approval_mode") or "ai") if str(body.get("approval_mode") or "ai") in {"human", "ai", "none"} else "ai"
        if "compat_mode" in body:
            config["compat_mode"] = normalize_compat_mode(body.get("compat_mode"))
        if body.get("api_key"):
            config["api_key"] = str(body["api_key"])
        config.setdefault("thinking", "max")
        if not str(config.get("base_url") or "").strip():
            config["base_url"] = "https://api.deepseek.com"
        save_ai_config(config)
        return {"ok": True, **ai_config_public(config)}

    def _request_config(body: dict) -> dict:
        saved = load_ai_config()
        return {
            "base_url": str(body.get("base_url") or saved.get("base_url", "")).strip(),
            "api_key": str(body.get("api_key") or saved.get("api_key", "")),
            "model": str(body.get("model") or saved.get("model", "deepseek-flash")),
            "thinking": str(body.get("thinking") or saved.get("thinking", "max")),
            "compat_mode": normalize_compat_mode(body.get("compat_mode", saved.get("compat_mode", "openai"))),
            "role_prompt": str(body.get("role_prompt") or saved.get("role_prompt", "")),
        }

    @app.post("/api/ai-agent/models")
    async def ai_agent_models(request: Request):
        require_local_auth(request)
        body = await request.json()
        config = _request_config(body)
        if not config["base_url"] or not config["api_key"]:
            return JSONResponse({"ok": False, "error": "Base URL and API Key are required"}, status_code=400)
        try:
            models = _provider_models(config)
            return {"ok": True, "models": models}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return JSONResponse({"ok": False, "error": f"模型列表 HTTP {exc.code}: {detail[:500]}"}, status_code=502)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"获取模型失败：{exc}"}, status_code=502)

    @app.post("/api/ai-agent/test")
    async def ai_agent_test(request: Request):
        require_local_auth(request)
        body = await request.json()
        config = _request_config(body)
        if not config["base_url"] or not config["api_key"] or not config["model"]:
            return JSONResponse({"ok": False, "error": "Base URL、API Key 和模型都必须填写"}, status_code=400)
        started = time.time()
        try:
            response = _llm_request(config, [
                {"role": "system", "content": "这是一次连接测试。请用中文只回复：连接成功"},
                {"role": "user", "content": "请回复：连接成功"},
            ], None)
            choice = (response.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            reply = message.get("content")
            if isinstance(reply, list):
                reply = "\n".join(part.get("text", "") for part in reply if isinstance(part, dict))
            reply = str(reply or "")
            connected = "连接成功" in reply
            return {"ok": connected, "connected": connected, "reply": reply, "elapsed_ms": int((time.time() - started) * 1000), "model": config["model"]}
        except Exception as exc:
            return JSONResponse({"ok": False, "connected": False, "reply": "", "error": str(exc)}, status_code=502)

    @app.post("/api/ai-agent/config/reset")
    def ai_agent_reset_config(request: Request):
        require_local_auth(request)
        try:
            AI_CONFIG_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        return {"ok": True, **ai_config_public(load_ai_config())}

    @app.get("/api/ai-agent/memory")
    def ai_agent_memory(request: Request):
        require_local_auth(request)
        items = load_ai_memory()
        return {"ok": True, "items": items, "count": len(items), "limit": 200}

    @app.post("/api/ai-agent/memory")
    async def ai_agent_add_memory(request: Request):
        require_local_auth(request)
        body = await request.json()
        title = str(body.get("title", "")).strip()
        content = str(body.get("content") or body.get("text") or "").strip()
        if not content:
            return JSONResponse({"ok": False, "error": "memory content is required"}, status_code=400)
        items = load_ai_memory()
        if len(items) >= 200:
            return JSONResponse({"ok": False, "error": "memory limit reached (200)"}, status_code=400)
        item = normalize_memory_item({"id": uuid.uuid4().hex, "title": title, "content": content, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())})
        items.append(item)
        save_ai_memory(items)
        return {"ok": True, "item": item, "count": len(items), "limit": 200}

    @app.put("/api/ai-agent/memory/{memory_id}")
    async def ai_agent_edit_memory(memory_id: str, request: Request):
        require_local_auth(request)
        body = await request.json()
        content = str(body.get("content") or body.get("text") or "").strip()
        if not content:
            return JSONResponse({"ok": False, "error": "memory content is required"}, status_code=400)
        items = load_ai_memory()
        for item in items:
            if item.get("id") == memory_id:
                if "title" in body:
                    item["title"] = str(body.get("title") or "").strip()[:200]
                item["content"] = content[:12000]
                item["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
                item = normalize_memory_item(item)
                save_ai_memory(items)
                return {"ok": True, "item": item, "count": len(items), "limit": 200}
        return JSONResponse({"ok": False, "error": "memory not found"}, status_code=404)

    @app.delete("/api/ai-agent/memory/{memory_id}")
    def ai_agent_delete_memory(memory_id: str, request: Request):
        require_local_auth(request)
        items = load_ai_memory()
        remaining = [item for item in items if item.get("id") != memory_id]
        if len(remaining) == len(items):
            return JSONResponse({"ok": False, "error": "memory not found"}, status_code=404)
        save_ai_memory(remaining)
        return {"ok": True, "count": len(remaining), "limit": 200}

    def _llm_base(base_url: str) -> str:
        base = str(base_url or "").rstrip("/")
        if not base:
            raise RuntimeError("AI base_url is not configured")
        for suffix in ("/chat/completions", "/messages"):
            if base.endswith(suffix):
                base = base[:-len(suffix)].rstrip("/")
        if "/models/" in base and ":generateContent" in base:
            base = base.split("/models/")[0].rstrip("/")
        return base

    def _http_json(req) -> dict:
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM HTTP {exc.code}: {detail[:500]}")

    def _openai_request(config: dict, messages: list[dict], tools: list[dict] | None = None) -> dict:
        base = _llm_base(config.get("base_url", ""))
        url = base + "/chat/completions"
        payload = {"model": str(config.get("model") or "gpt-4o-mini"), "messages": messages, "temperature": 0.2}
        if tools is not None:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        thinking = str(config.get("thinking") or "max")
        if thinking and thinking != "auto" and normalize_compat_mode(config.get("compat_mode")) == "openai":
            payload["reasoning_effort"] = thinking
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {config.get('api_key', '')}"}
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            return _http_json(req)
        except RuntimeError as exc:
            detail = str(exc)
            if "reasoning" in detail.lower() and "400" in detail:
                payload.pop("reasoning_effort", None)
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
                return _http_json(req)
            raise

    def _claude_tools(tools: list[dict] | None) -> list[dict] | None:
        if tools is None:
            return None
        result = []
        for item in tools:
            fn = item.get("function") or item
            result.append({"name": fn.get("name", ""), "description": fn.get("description", ""), "input_schema": fn.get("parameters") or {"type": "object", "properties": {}}})
        return result

    def _claude_request(config: dict, messages: list[dict], tools: list[dict] | None = None) -> dict:
        base = _llm_base(config.get("base_url", ""))
        system_parts = []
        converted = []
        for message in messages:
            role = message.get("role")
            if role == "system":
                system_parts.append(str(message.get("content") or ""))
                continue
            if role == "tool":
                converted.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": message.get("tool_call_id", ""), "content": str(message.get("content") or "")}]})
                continue
            if role == "assistant":
                content = []
                if message.get("content"):
                    content.append({"type": "text", "text": str(message["content"])})
                for call in message.get("tool_calls") or []:
                    fn = call.get("function") or {}
                    try:
                        call_args = json.loads(fn.get("arguments") or "{}")
                    except Exception:
                        call_args = {}
                    content.append({"type": "tool_use", "id": call.get("id", ""), "name": fn.get("name", ""), "input": call_args})
                if content:
                    converted.append({"role": "assistant", "content": content})
                continue
            converted.append({"role": "user", "content": [{"type": "text", "text": str(message.get("content") or "")}]})
        payload = {"model": str(config.get("model") or "claude-3-5-sonnet-latest"), "max_tokens": 4096, "system": "\n\n".join(system_parts), "messages": converted}
        if tools is not None:
            payload["tools"] = _claude_tools(tools)
        headers = {"Content-Type": "application/json", "x-api-key": config.get("api_key", ""), "anthropic-version": "2023-06-01"}
        req = urllib.request.Request(base + "/messages", data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        data = _http_json(req)
        text_parts = []
        thinking_parts = []
        tool_calls = []
        for block in data.get("content") or []:
            if block.get("type") == "text":
                text_parts.append(str(block.get("text") or ""))
            elif block.get("type") == "thinking":
                thinking_parts.append(str(block.get("thinking") or block.get("text") or ""))
            elif block.get("type") == "tool_use":
                tool_calls.append({"id": block.get("id", ""), "type": "function", "function": {"name": block.get("name", ""), "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False)}})
        message = {"role": "assistant", "content": "".join(text_parts) or None}
        if thinking_parts:
            message["thinking"] = "\n".join(thinking_parts)
        if tool_calls:
            message["tool_calls"] = tool_calls
        return {"choices": [{"message": message, "finish_reason": data.get("stop_reason")}]}

    def _gemini_request(config: dict, messages: list[dict], tools: list[dict] | None = None) -> dict:
        base = _llm_base(config.get("base_url", ""))
        system_parts = []
        contents = []
        tool_names = {}
        for message in messages:
            role = message.get("role")
            if role == "system":
                system_parts.append(str(message.get("content") or ""))
                continue
            if role == "tool":
                raw = str(message.get("content") or "{}")
                try:
                    response_obj = json.loads(raw)
                except Exception:
                    response_obj = {"result": raw}
                if not isinstance(response_obj, dict):
                    response_obj = {"result": response_obj}
                contents.append({"role": "user", "parts": [{"functionResponse": {"name": tool_names.get(message.get("tool_call_id", ""), "c2_action"), "response": response_obj}}]})
                continue
            if role == "assistant":
                parts = []
                if message.get("content"):
                    parts.append({"text": str(message["content"])})
                for call in message.get("tool_calls") or []:
                    fn = call.get("function") or {}
                    name = fn.get("name", "")
                    tool_names[call.get("id", "")] = name
                    try:
                        call_args = json.loads(fn.get("arguments") or "{}")
                    except Exception:
                        call_args = {}
                    parts.append({"functionCall": {"name": name, "args": call_args}})
                if parts:
                    contents.append({"role": "model", "parts": parts})
                continue
            contents.append({"role": "user", "parts": [{"text": str(message.get("content") or "")}]})
        payload = {"contents": contents}
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        if tools is not None:
            declarations = []
            for item in tools:
                fn = item.get("function") or item
                declarations.append({"name": fn.get("name", ""), "description": fn.get("description", ""), "parameters": fn.get("parameters") or {"type": "object", "properties": {}}})
            payload["tools"] = [{"functionDeclarations": declarations}]
        base_for_model = base[:-len("/models")].rstrip("/") if base.endswith("/models") else base
        model = str(config.get("model") or "gemini-2.0-flash")
        url = base_for_model + "/models/" + urllib.parse.quote(model, safe="") + ":generateContent?key=" + urllib.parse.quote(config.get("api_key", ""), safe="")
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        data = _http_json(req)
        candidate = (data.get("candidates") or [{}])[0]
        parts = (candidate.get("content") or {}).get("parts") or []
        text_parts = []
        thinking_parts = []
        tool_calls = []
        for index, part in enumerate(parts):
            if "text" in part:
                if part.get("thought"):
                    thinking_parts.append(str(part.get("text") or ""))
                else:
                    text_parts.append(str(part.get("text") or ""))
            if "functionCall" in part:
                call = part["functionCall"] or {}
                tool_calls.append({"id": f"gemini_call_{index}", "type": "function", "function": {"name": call.get("name", ""), "arguments": json.dumps(call.get("args") or {}, ensure_ascii=False)}})
        message = {"role": "assistant", "content": "".join(text_parts) or None}
        if thinking_parts:
            message["thinking"] = "\n".join(thinking_parts)
        if tool_calls:
            message["tool_calls"] = tool_calls
        return {"choices": [{"message": message, "finish_reason": candidate.get("finishReason")}]}

    def _llm_request(config: dict, messages: list[dict], tools: list[dict] | None = None) -> dict:
        mode = normalize_compat_mode(config.get("compat_mode"))
        if mode == "claude":
            return _claude_request(config, messages, tools)
        if mode == "gemini":
            return _gemini_request(config, messages, tools)
        return _openai_request(config, messages, tools)

    def _provider_models(config: dict) -> list[str]:
        mode = normalize_compat_mode(config.get("compat_mode"))
        base = _llm_base(config.get("base_url", ""))
        if mode == "gemini":
            req = urllib.request.Request(base + "/models?key=" + urllib.parse.quote(config.get("api_key", ""), safe=""), method="GET")
            data = _http_json(req)
            return [str(item.get("name", "")).replace("models/", "") for item in (data.get("models") or []) if isinstance(item, dict) and item.get("name")]
        if mode == "claude":
            req = urllib.request.Request(base + "/models", headers={"x-api-key": config.get("api_key", ""), "anthropic-version": "2023-06-01"}, method="GET")
            data = _http_json(req)
            return [str(item.get("id")) for item in (data.get("data") or []) if isinstance(item, dict) and item.get("id")]
        req = urllib.request.Request(base + "/models", headers={"Authorization": f"Bearer {config.get('api_key', '')}"}, method="GET")
        data = _http_json(req)
        return [str(item.get("id")) for item in (data.get("data") or []) if isinstance(item, dict) and item.get("id")]

    def _ai_worker_token() -> str:
        try:
            cfg = json.loads((ROOT / "ai" / "config.json").read_text(encoding="utf-8"))
            return str(cfg.get("token") or "").strip()
        except Exception:
            return ""

    def _c2_tool(action: str, args: dict, use_human: bool = False) -> dict:
        active_server, human_token = active_config()
        # AI Agent actions use the AI worker token so server-side per_action
        # approval policy actually applies. They must not inherit human bypass.
        active_token = human_token if use_human else _ai_worker_token()
        if not active_token:
            return {"status": "error", "error": "AI Worker token is not configured in clients/ai/config.json"}
        req = urllib.request.Request(
            active_server + "/api/action",
            data=json.dumps({"action": action, "args": args or {}}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {active_token}", "X-PyExec-Origin": "ai-agent"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return {"status": "error", "http": exc.code, "error": exc.read().decode("utf-8", errors="replace") or "request failed"}

    def _wait_for_approval(approval: dict, run: dict, emit=None) -> dict:
        approval_id = str((approval or {}).get("id") or "")
        if not approval_id:
            return {"status": "error", "error": "approval id missing"}
        run["waiting_approval"] = approval
        if emit:
            emit({"type": "approval_wait", "approval": approval, "message": "等待人工审批，审批通过后自动继续执行"})
        while not run.get("abort"):
            shown = _c2_tool("approval.show", {"approval_id": approval_id})
            record = shown.get("data") if shown.get("status") == "ok" else None
            if isinstance(record, dict) and record.get("status") in {"approved", "rejected", "failed"}:
                run["waiting_approval"] = None
                if emit:
                    emit({"type": "approval_resolved", "approval": record})
                if record.get("status") == "approved":
                    return {"status": "ok", "data": record.get("result")}
                if record.get("status") == "failed":
                    return {"status": "error", "error": record.get("error") or "approved action failed", "approval": record}
                return {
                    "status": "error",
                    "error": "human operator rejected this tool call",
                    "rejected": True,
                    "suggestion": record.get("suggestion") or "",
                    "approval": record,
                }
            time.sleep(1)
        run["waiting_approval"] = None
        return {"status": "error", "error": "agent run aborted while waiting for approval", "aborted": True}

    def _agent_tools() -> list[dict]:
        return [
            {"type": "function", "function": {"name": "c2_action", "description": "Execute a PyExec2 server action as the AI worker role. Write actions may return approval_required when server approval policy is per_action.", "parameters": {"type": "object", "properties": {"action": {"type": "string"}, "args": {"type": "object"}}, "required": ["action", "args"]}}},
            {"type": "function", "function": {"name": "remember", "description": "Store one important durable memory with a title and content (max 200 entries). Use for stable operational facts, not every chat turn.", "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "content": {"type": "string"}}, "required": ["title", "content"]}}},
        ]

    agent_runs: dict[str, dict] = {}
    agent_runs_lock = threading.Lock()

    def _agent_run_get(run_id: str):
        with agent_runs_lock:
            return agent_runs.get(run_id)

    def _agent_run_drop(run_id: str):
        with agent_runs_lock:
            agent_runs.pop(run_id, None)

    def _agent_think(run: dict, text, emit=None):
        text = str(text or "").strip()
        if text:
            run["thinking"].append(text)
            if emit: emit({"type": "thinking", "text": text})

    def _agent_tool_result(run: dict, call: dict, approved: bool = True, emit=None) -> dict:
        fn = call.get("function") or {}
        name = fn.get("name", "")
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except Exception:
            args = {}
        if emit: emit({"type": "tool_call", "id": call.get("id", ""), "name": name, "args": args, "approved": approved})
        if not approved:
            result = {"status": "error", "error": "human operator denied this tool call"}
        elif name == "remember":
            title = str(args.get("title", "")).strip()
            content = str(args.get("content") or args.get("text") or "").strip()
            items = load_ai_memory()
            if content and len(items) < 200:
                items.append(normalize_memory_item({"id": uuid.uuid4().hex, "title": title, "content": content, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())}))
                save_ai_memory(items)
            result = {"ok": bool(content), "count": len(load_ai_memory()), "limit": 200}
        elif name == "c2_action":
            action = str(args.get("action", ""))
            result = _c2_tool(action, args.get("args") or {})
            if result.get("status") == "approval_required":
                result = _wait_for_approval(result.get("approval") or {}, run, emit)
            if result.get("status") == "ok" and action in {"task.create", "script.run"}:
                data = result.get("data") or {}
                task_id = data.get("id")
                if task_id and task_id not in run["task_ids"]:
                    run["task_ids"].append(task_id)
                beacon_id = data.get("beacon_id")
                if beacon_id and beacon_id not in run["beacon_ids"]:
                    run["beacon_ids"].append(beacon_id)
        else:
            result = {"status": "error", "error": f"unknown tool: {name}"}
        run["trace"].append({"tool": name, "args": args, "result": result, "approved": approved, "approval_mode": run["approval_mode"]})
        if emit: emit({"type": "tool_result", "id": call.get("id", ""), "name": name, "args": args, "result": result, "approved": approved})
        result_text = json.dumps(result, ensure_ascii=False)
        if len(result_text) > 16000:
            result_text = result_text[:16000] + "\n...[tool result truncated for model context]"
        run["messages"].append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result_text})
        return result

    def _agent_payload(run: dict, **extra) -> dict:
        payload = {
            "ok": True,
            "run_id": run["run_id"],
            "trace": run["trace"],
            "thinking": "\n\n".join(run["thinking"]),
            "memory_count": len(load_ai_memory()),
        }
        payload.update(extra)
        return payload

    def _run_agent_loop(run: dict, pending_calls=None, approved: bool = True, emit=None) -> dict:
        try:
            if pending_calls:
                for call in pending_calls:
                    if run.get("abort"):
                        return _agent_payload(run, ok=False, aborted=True)
                    _agent_tool_result(run, call, approved, emit)
                run["pending_calls"] = None
            while True:
                if run.get("abort"):
                    return _agent_payload(run, ok=False, aborted=True)
                if emit: emit({"type": "status", "text": "AI 正在思考并等待模型响应…"})
                response = _llm_request(run["config"], run["messages"], _agent_tools())
                choice = (response.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                thinking = message.get("thinking") or message.get("reasoning_content") or message.get("reasoning")
                if thinking:
                    _agent_think(run, thinking, emit)
                tool_calls = message.get("tool_calls") or []
                if not tool_calls:
                    reply = message.get("content")
                    if isinstance(reply, list):
                        reply = "\n".join(part.get("text", "") for part in reply if isinstance(part, dict))
                    return _agent_payload(run, reply=str(reply or ""))
                run["messages"].append({"role": "assistant", "content": message.get("content"), "tool_calls": tool_calls})
                if emit and message.get("content"): emit({"type": "assistant_partial", "text": str(message.get("content"))})
                names = [((call.get("function") or {}).get("name") or "tool") for call in tool_calls]
                _agent_think(run, f"步骤 {len(run['trace']) + 1}: 准备调用工具 {', '.join(names)}", emit)
                if run["approval_mode"] == "human":
                    run["pending_calls"] = tool_calls
                    pending = []
                    for call in tool_calls:
                        fn = call.get("function") or {}
                        try:
                            args = json.loads(fn.get("arguments") or "{}")
                        except Exception:
                            args = {}
                        pending.append({"id": call.get("id", ""), "name": fn.get("name", ""), "args": args})
                        if emit: emit({"type": "tool_call", "id": call.get("id", ""), "name": fn.get("name", ""), "args": args, "approved": False})
                    return _agent_payload(run, awaiting_approval=True, pending_tools=pending)
                for call in tool_calls:
                    if run.get("abort"):
                        return _agent_payload(run, ok=False, aborted=True)
                    _agent_tool_result(run, call, True, emit)
        except Exception as exc:
            return _agent_payload(run, ok=False, error=str(exc))

    def _sse_agent_response(run: dict, pending_calls=None, approved: bool = True):
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def emit(event):
            loop.call_soon_threadsafe(queue.put_nowait, event)

        def worker():
            try:
                result = _run_agent_loop(run, pending_calls, approved, emit)
            except Exception as exc:
                result = {"ok": False, "error": str(exc), "run_id": run["run_id"], "trace": run.get("trace", []), "thinking": "\n\n".join(run.get("thinking", []))}
            emit({"type": "done", "result": result})
            if not result.get("awaiting_approval"):
                _agent_run_drop(run["run_id"])

        asyncio.create_task(asyncio.to_thread(worker))

        async def generator():
            yield "retry: 1000\n\n"
            while True:
                event = await queue.get()
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                if event.get("type") == "done":
                    break
        return StreamingResponse(generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})

    @app.post("/api/ai-agent/chat")
    async def ai_agent_chat(request: Request):
        require_local_auth(request)
        body = await request.json()
        incoming = body.get("messages") or []
        if not isinstance(incoming, list) or not incoming:
            return JSONResponse({"ok": False, "error": "messages are required"}, status_code=400)
        config = load_ai_config()
        if not config.get("base_url") or not config.get("api_key"):
            return JSONResponse({"ok": False, "error": "AI base URL and API key are required"}, status_code=400)
        memory = load_ai_memory()
        memory_text = "\n\n".join(f"## {item.get('title', '未命名记忆')}\n{item.get('content', '')}" for item in memory) if memory else "(empty)"
        skill_notes = [item for item in load_notebooks() if item.get("category") == "redteam" and item.get("ai_skill")]
        skill_text = "\n\n".join(f"## {item.get('title') or '未命名红队笔记'}\n{str(item.get('content') or '')[:4000]}" for item in skill_notes) if skill_notes else "(empty)"
        system = (
            f"{config.get('role_prompt', '')}\n\n"
            "You are the PyExec2 built-in C2 agent. Use the c2_action tool to operate the server. "
            "You act as the AI worker role. Server approval policy applies to your C2 actions; "
            "you cannot approve or reject your own operations. When a write action requires approval, "
            "the runtime pauses the tool and waits for a human automatically. Continue only after the "
            "approval result is returned; do not retry the same write action while it is pending. "
            "If the human rejects an action, read the rejection suggestion as high-priority operator "
            "guidance, revise your plan, and issue a new tool request that addresses it. Never retry the "
            "same rejected action unchanged. "
            "Use read-only actions first when uncertain. Never invent tool results. "
            "When you need a durable fact, call remember. Do not store every message. "
            "There is no fixed tool-call limit: keep using tools until the task is complete, then stop and summarize. "
            "Avoid repeating identical tool calls unnecessarily.\n\n"
            "Common C2 actions: server.status, server.capabilities, beacon.list, beacon.show, task.list, task.show, "
            "task.create, script.run, task.cancel, file.list, file.read, file.write, file.upload_chunk, "
            "listener.list, listener.create, payload.generate, plugin.list, group.list, group.create, "
            "group.batch_dispatch, auto.global.get, auto.global.set, approval.pending, approval.show, "
            "approval.approve, approval.reject, approval.approve_all, approval.reject_all. "
            "For Python execution prefer script.run with source.\n\n"
            "Durable memory (separate from chat compression, do not rewrite or summarize it):\n" + memory_text +
            "\n\nRed-team skill notebooks authored by the operator (use as playbooks/skills when relevant):\n" + skill_text
        )
        messages = [{"role": "system", "content": system}]
        for message in incoming[-24:]:
            if message.get("role") in {"user", "assistant"} and message.get("content"):
                messages.append({"role": message["role"], "content": str(message["content"])})
        run_id = str(body.get("run_id") or uuid.uuid4().hex)
        run = {
            "run_id": run_id,
            "config": config,
            "messages": messages,
            "trace": [],
            "thinking": [],
            "task_ids": [],
            "beacon_ids": [],
            "pending_calls": None,
            "abort": False,
            "approval_mode": str(config.get("approval_mode") or "ai") if str(config.get("approval_mode") or "ai") in {"human", "ai", "none"} else "ai",
        }
        with agent_runs_lock:
            agent_runs[run_id] = run
        result = await asyncio.to_thread(_run_agent_loop, run, None, True)
        if not result.get("awaiting_approval"):
            _agent_run_drop(run_id)
        return JSONResponse(result, status_code=200 if result.get("ok") or result.get("awaiting_approval") else 502)

    @app.post("/api/ai-agent/stream")
    async def ai_agent_stream(request: Request):
        require_local_auth(request)
        body = await request.json()
        incoming = body.get("messages") or []
        if not isinstance(incoming, list) or not incoming:
            return JSONResponse({"ok": False, "error": "messages are required"}, status_code=400)
        config = load_ai_config()
        if not config.get("base_url") or not config.get("api_key"):
            return JSONResponse({"ok": False, "error": "AI base URL and API key are required"}, status_code=400)
        memory = load_ai_memory()
        memory_text = "\n\n".join(f"## {item.get('title', '未命名记忆')}\n{item.get('content', '')}" for item in memory) if memory else "(empty)"
        skill_notes = [item for item in load_notebooks() if item.get("category") == "redteam" and item.get("ai_skill")]
        skill_text = "\n\n".join(f"## {item.get('title') or '未命名红队笔记'}\n{str(item.get('content') or '')[:4000]}" for item in skill_notes) if skill_notes else "(empty)"
        system = (
            f"{config.get('role_prompt', '')}\n\n"
            "You are the PyExec2 built-in C2 agent. Use the c2_action tool to operate the server. "
            "You act as the AI worker role. Server approval policy applies to your C2 actions; "
            "you cannot approve or reject your own operations. When a write action requires approval, "
            "the runtime pauses the tool and waits for a human automatically. Continue only after the "
            "approval result is returned; do not retry the same write action while it is pending. "
            "If the human rejects an action, read the rejection suggestion as high-priority operator "
            "guidance, revise your plan, and issue a new tool request that addresses it. Never retry the "
            "same rejected action unchanged. "
            "Use read-only actions first when uncertain. Never invent tool results. "
            "When you need a durable fact, call remember. Do not store every message. "
            "There is no fixed tool-call limit: keep using tools until the task is complete, then stop and summarize. "
            "Avoid repeating identical tool calls unnecessarily.\n\n"
            "Common C2 actions: server.status, server.capabilities, beacon.list, beacon.show, task.list, task.show, "
            "task.create, script.run, task.cancel, file.list, file.read, file.write, file.upload_chunk, "
            "listener.list, listener.create, payload.generate, plugin.list, group.list, group.create, "
            "group.batch_dispatch, auto.global.get, auto.global.set, approval.pending, approval.show, "
            "approval.approve, approval.reject, approval.approve_all, approval.reject_all. "
            "For Python execution prefer script.run with source.\n\n"
            "Durable memory (separate from chat compression, do not rewrite or summarize it):\n" + memory_text +
            "\n\nRed-team skill notebooks authored by the operator (use as playbooks/skills when relevant):\n" + skill_text
        )
        messages = [{"role": "system", "content": system}]
        for message in incoming[-24:]:
            if message.get("role") in {"user", "assistant"} and message.get("content"):
                messages.append({"role": message["role"], "content": str(message["content"])})
        run_id = str(body.get("run_id") or uuid.uuid4().hex)
        run = {
            "run_id": run_id, "config": config, "messages": messages,
            "trace": [], "thinking": [], "task_ids": [], "beacon_ids": [],
            "pending_calls": None, "abort": False,
            "approval_mode": str(config.get("approval_mode") or "ai") if str(config.get("approval_mode") or "ai") in {"human", "ai", "none"} else "ai",
        }
        with agent_runs_lock:
            agent_runs[run_id] = run
        return _sse_agent_response(run)

    @app.post("/api/ai-agent/stream/continue")
    async def ai_agent_stream_continue(request: Request):
        require_local_auth(request)
        body = await request.json()
        run_id = str(body.get("run_id") or "")
        run = _agent_run_get(run_id)
        if not run:
            return JSONResponse({"ok": False, "error": "agent run not found or already finished"}, status_code=404)
        run["abort"] = False
        pending = run.get("pending_calls") or []
        return _sse_agent_response(run, pending, bool(body.get("approved", False)))

    @app.post("/api/ai-agent/continue")
    async def ai_agent_continue(request: Request):
        require_local_auth(request)
        body = await request.json()
        run_id = str(body.get("run_id") or "")
        run = _agent_run_get(run_id)
        if not run:
            return JSONResponse({"ok": False, "error": "agent run not found or already finished"}, status_code=404)
        run["abort"] = False
        approved = bool(body.get("approved", False))
        pending = run.get("pending_calls") or []
        result = await asyncio.to_thread(_run_agent_loop, run, pending, approved)
        if not result.get("awaiting_approval"):
            _agent_run_drop(run_id)
        return JSONResponse(result, status_code=200 if result.get("ok") or result.get("awaiting_approval") else 502)

    @app.post("/api/ai-agent/stop")
    async def ai_agent_stop(request: Request):
        require_local_auth(request)
        body = await request.json()
        run_id = str(body.get("run_id") or "")
        run = _agent_run_get(run_id)
        cancelled = []
        cleared_beacons = []
        if run:
            run["abort"] = True
            for beacon_id in list(run.get("beacon_ids") or []):
                result = _c2_tool("beacon.stop_queue", {"beacon_id": beacon_id}, use_human=True)
                cleared_beacons.append({"beacon_id": beacon_id, "result": result})
                if result.get("status") == "ok":
                    cancelled.extend((result.get("data") or {}).get("cancelled_task_ids") or [])
        _agent_run_drop(run_id)
        return {"ok": True, "aborted": bool(run), "cancelled_tasks": cancelled, "cleared_beacons": cleared_beacons}

    def load_notebooks() -> list[dict]:
        if NOTEBOOKS_PATH.exists():
            try:
                data = json.loads(NOTEBOOKS_PATH.read_text(encoding="utf-8"))
                return list(data.get("items") or [])
            except Exception:
                pass
        return []

    def save_notebooks(items: list[dict]) -> None:
        NOTEBOOKS_PATH.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            NOTEBOOKS_PATH.chmod(0o600)
        except OSError:
            pass

    def default_redteam_fingerprint(manifest: list[dict]) -> str:
        digest = hashlib.sha256()
        digest.update(DEFAULT_REDTEAM_MANIFEST.read_bytes())
        for entry in manifest:
            filename = str(entry.get("file") or "").strip()
            if not filename:
                continue
            source_path = DEFAULT_REDTEAM_NOTES_DIR / filename
            digest.update(filename.encode("utf-8"))
            if source_path.exists():
                digest.update(source_path.read_bytes())
        return digest.hexdigest()

    def seed_default_redteam_notes() -> None:
        if not DEFAULT_REDTEAM_MANIFEST.exists():
            return
        try:
            manifest = json.loads(DEFAULT_REDTEAM_MANIFEST.read_text(encoding="utf-8"))
        except Exception:
            return
        expected_fingerprint = default_redteam_fingerprint(manifest)
        current_version = 0
        current_fingerprint = ""
        if DEFAULT_REDTEAM_MARKER.exists():
            try:
                marker_data = json.loads(DEFAULT_REDTEAM_MARKER.read_text(encoding="utf-8"))
                current_version = int(marker_data.get("version", 0))
                current_fingerprint = str(marker_data.get("fingerprint", ""))
            except Exception:
                current_version = 0
        if current_version >= DEFAULT_REDTEAM_SEED_VERSION and current_fingerprint == expected_fingerprint:
            return
        items = load_notebooks()
        by_id = {str(item.get("id", "")): item for item in items}
        existing_titles = {(str(item.get("title", "")), str(item.get("category", "standard"))) for item in items}
        now = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        added = 0
        updated = 0
        for entry in manifest:
            title = str(entry.get("title") or "").strip()
            filename = str(entry.get("file") or "").strip()
            entry_id = str(entry.get("id") or "")
            if not title or not filename or not entry_id:
                continue
            source_path = DEFAULT_REDTEAM_NOTES_DIR / filename
            if not source_path.exists():
                continue
            content = source_path.read_text(encoding="utf-8", errors="replace")
            existing = by_id.get(entry_id)
            if existing:
                # Refresh system-default content while preserving the operator's
                # AI Skill enable/disable choice and created_at.
                existing["title"] = title
                existing["content"] = content
                existing["category"] = "redteam"
                existing["builtin"] = True
                existing["source"] = "system-default"
                existing["updated_at"] = now
                updated += 1
                continue
            if (title, "redteam") in existing_titles:
                continue
            item = {
                "id": entry_id,
                "title": title,
                "content": content,
                "category": "redteam",
                "ai_skill": bool(entry.get("ai_skill", False)),
                "builtin": True,
                "source": "system-default",
                "created_at": now,
                "updated_at": now,
            }
            items.append(item)
            by_id[entry_id] = item
            existing_titles.add((title, "redteam"))
            added += 1
        if added or updated:
            save_notebooks(items)
        NOTES_MARKER_PARENT = DEFAULT_REDTEAM_MARKER.parent
        NOTES_MARKER_PARENT.mkdir(parents=True, exist_ok=True)
        DEFAULT_REDTEAM_MARKER.write_text(json.dumps({"seeded": added, "updated": updated, "version": DEFAULT_REDTEAM_SEED_VERSION, "fingerprint": expected_fingerprint}, ensure_ascii=False), encoding="utf-8")
        try:
            DEFAULT_REDTEAM_MARKER.chmod(0o600)
        except OSError:
            pass

    @app.get("/api/notebooks")
    def notebook_list(request: Request):
        require_local_auth(request)
        items = load_notebooks()
        return {"ok": True, "items": items, "count": len(items)}

    @app.post("/api/notebooks")
    async def notebook_create(request: Request):
        require_local_auth(request)
        body = await request.json()
        now = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        category = "redteam" if str(body.get("category") or "standard") == "redteam" else "standard"
        item = {
            "id": uuid.uuid4().hex,
            "title": str(body.get("title") or ("未命名红队笔记" if category == "redteam" else "未命名记事本"))[:200],
            "content": str(body.get("content") or ""),
            "category": category,
            "ai_skill": bool(body.get("ai_skill", category == "redteam")),
            "created_at": now,
            "updated_at": now,
        }
        items = load_notebooks()
        items.insert(0, item)
        save_notebooks(items)
        return {"ok": True, "item": item, "count": len(items)}

    @app.put("/api/notebooks/{notebook_id}")
    async def notebook_update(notebook_id: str, request: Request):
        require_local_auth(request)
        body = await request.json()
        items = load_notebooks()
        for item in items:
            if item.get("id") == notebook_id:
                if "title" in body:
                    item["title"] = str(body.get("title") or "未命名记事本")[:200]
                if "content" in body:
                    item["content"] = str(body.get("content") or "")
                if "ai_skill" in body:
                    item["ai_skill"] = bool(body.get("ai_skill"))
                item["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
                save_notebooks(items)
                return {"ok": True, "item": item, "count": len(items)}
        return JSONResponse({"ok": False, "error": "notebook not found"}, status_code=404)

    @app.delete("/api/notebooks/{notebook_id}")
    def notebook_delete(notebook_id: str, request: Request):
        require_local_auth(request)
        items = load_notebooks()
        remaining = [item for item in items if item.get("id") != notebook_id]
        if len(remaining) == len(items):
            return JSONResponse({"ok": False, "error": "notebook not found"}, status_code=404)
        save_notebooks(remaining)
        return {"ok": True, "count": len(remaining)}

    @app.get("/api/ai-guide-context")
    def ai_guide_context(request: Request):
        require_local_auth(request)
        active_server, human_token = active_config()
        parsed = urllib.parse.urlparse(active_server)
        worker_token = ""
        approval_token = ""
        try:
            worker_token = str(json.loads((ROOT / "ai" / "config.json").read_text(encoding="utf-8")).get("token", ""))
        except Exception:
            pass
        try:
            approval_token = str(json.loads((ROOT / "ai" / "approval_config.json").read_text(encoding="utf-8")).get("token", ""))
        except Exception:
            pass
        return {
            "server_url": active_server,
            "server_scheme": parsed.scheme or "http",
            "server_host": parsed.hostname or "127.0.0.1",
            "server_port": parsed.port or 18080,
            "local_web_url": "http://127.0.0.1:8765",
            "human_token": human_token,
            "ai_worker_token": worker_token,
            "ai_approval_token": approval_token,
            "ai_client": str(ROOT / "ai" / "client_ai.py"),
            "project_dir": str(ROOT.parent),
        }

    @app.post("/api/config")
    async def save_config(request: Request):
        body = await request.json()
        supplied = request.headers.get("x-pyexec-auth", "")
        candidate = str(body.get("token", ""))
        if not candidate or not supplied or not hmac.compare_digest(supplied, candidate):
            raise HTTPException(status_code=401, detail=None)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            cfg_path.chmod(0o600)
        except OSError:
            pass
        return {"ok": True}

    @app.post("/api/connect")
    async def connect(request: Request):
        body = await request.json()
        server = str(body.get("server", "")).rstrip("/")
        token = str(body.get("token", ""))
        if not server or not token:
            return JSONResponse({"ok": False, "error": "server and token are required"}, status_code=400)
        req = urllib.request.Request(
            server + "/api/session",
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                raw = response.read()
            data = json.loads(raw.decode("utf-8"))
            return {"ok": True, "role": data.get("role"), "approval_mode": data.get("approval_mode"), "server": server}
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                # Return a normal application response so the login form can
                # display the rejection without a browser resource error.
                return JSONResponse({"ok": False, "error": "Token 无效，服务端拒绝了连接"}, status_code=200)
            return JSONResponse({"ok": False, "error": f"服务端返回 HTTP {exc.code}"}, status_code=502)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"无法连接服务端: {exc}"}, status_code=502)

    @app.get("/api/local/history")
    def local_history(request: Request, limit: int = 200):
        require_local_auth(request)
        rows = []
        for path in sorted(HISTORY_DIR.glob("*.json"), reverse=True)[:max(1, min(limit, 2000))]:
            try:
                rows.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        return {"ok": True, "items": rows, "dir": str(HISTORY_DIR)}

    @app.post("/api/local/history")
    async def save_local_history(request: Request):
        require_local_auth(request)
        body = await request.json()
        command = str(body.get("command", "")).strip()
        if not command:
            return JSONResponse({"ok": False, "error": "command is required"}, status_code=400)
        entry = {
            "id": uuid.uuid4().hex,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "command": command,
            "beacon_id": str(body.get("beacon_id", "")),
            "beacon_host": str(body.get("beacon_host", "")),
            "kind": str(body.get("kind", "command")),
        }
        path = HISTORY_DIR / f"{int(time.time() * 1000)}_{entry['id']}.json"
        path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "item": entry, "file": str(path)}

    @app.delete("/api/local/history")
    def clear_local_history(request: Request):
        require_local_auth(request)
        count = 0
        for path in HISTORY_DIR.glob("*.json"):
            path.unlink(missing_ok=True)
            count += 1
        return {"ok": True, "deleted": count}

    @app.get("/api/local/templates")
    def local_templates(request: Request):
        require_local_auth(request)
        items = [template_record(path) for path in sorted(TEMPLATE_DIR.glob("*.py"))]
        items.sort(key=lambda item: item["updated_at"], reverse=True)
        return {"ok": True, "items": items, "dir": str(TEMPLATE_DIR)}

    @app.post("/api/local/templates")
    async def save_local_template(request: Request):
        require_local_auth(request)
        body = await request.json()
        source = str(body.get("source", ""))
        name = safe_template_name(str(body.get("name", "")))
        if not source.strip():
            return JSONResponse({"ok": False, "error": "source is required"}, status_code=400)
        path = TEMPLATE_DIR / f"{name}.py"
        path.write_text(source, encoding="utf-8")
        return {"ok": True, "template": template_record(path), "file": str(path)}

    @app.delete("/api/local/templates/{name}")
    def delete_local_template(name: str, request: Request):
        require_local_auth(request)
        path = TEMPLATE_DIR / f"{safe_template_name(name)}.py"
        if not path.exists():
            return JSONResponse({"ok": False, "error": "template not found"}, status_code=404)
        path.unlink()
        return {"ok": True, "deleted": path.stem}

    @app.post("/api/action")
    async def action(request: Request):
        require_local_auth(request)
        body = await request.body()
        active_server, active_token = active_config()
        req = urllib.request.Request(
            active_server + "/api/action",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {active_token}", "X-PyExec-Origin": "ai-agent"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                data = response.read()
                return Response(data, status_code=response.status, media_type="application/json")
        except urllib.error.HTTPError as exc:
            return Response(exc.read(), status_code=exc.code, media_type=exc.headers.get("content-type", "application/json"))
        except Exception as exc:
            return JSONResponse({"status": "error", "error": str(exc)}, status_code=502)

    @app.get("/api/session")
    def session(request: Request):
        require_local_auth(request)
        active_server, active_token = active_config()
        req = urllib.request.Request(active_server + "/api/session", headers={"Authorization": f"Bearer {active_token}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return Response(response.read(), media_type="application/json")
        except urllib.error.HTTPError as exc:
            return Response(exc.read(), status_code=exc.code)
        except Exception as exc:
            return JSONResponse({"status": "error", "error": str(exc)}, status_code=502)

    seed_default_redteam_notes()
    if DIST.exists():
        app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
    else:
        @app.get("/")
        def missing():
            return JSONResponse({"error": "Web build missing. Run npm install && npm run build in clients/web."}, status_code=503)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="PyExec2 local web client")
    parser.add_argument("--server", default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server, token = load_config(args)
    print(f"Local web client: http://{args.host}:{args.port}")
    print(f"Remote server: {server}")
    uvicorn.run(create_local_app(server, token, args.config), host=args.host, port=args.port, log_level="info", server_header=False, date_header=False)


if __name__ == "__main__":
    main()
