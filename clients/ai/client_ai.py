#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def load_config(path: str) -> dict:
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def request(server: str, token: str, action: str, args: dict, timeout: float) -> dict:
    payload = json.dumps({"action": action, "args": args}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        server.rstrip("/") + "/api/action",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"status": "error", "http_status": exc.code, "error": exc.read().decode("utf-8", "replace")}
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    parser = argparse.ArgumentParser(description="PyExec2 one-shot AI client")
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.json")))
    parser.add_argument("--server", default=os.environ.get("PYEXEC2_SERVER", ""))
    parser.add_argument("--token", default=os.environ.get("PYEXEC2_TOKEN", ""))
    parser.add_argument("--approval-token", default=os.environ.get("PYEXEC2_AI_APPROVAL_TOKEN", ""), help="AI approval token used for approval decisions")
    parser.add_argument("--action", default="")
    parser.add_argument("--args", default="{}", help="JSON object")
    parser.add_argument("--request", default="", help="JSON request file")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--wait", action="store_true", help="wait for task result via polling")
    parser.add_argument("--wait-task", default="", help="wait for an existing task id")
    parser.add_argument("--list-actions", action="store_true", help="show every action available to this token")
    parser.add_argument("--pending", action="store_true", help="list pending approvals")
    parser.add_argument("--approve", default="", help="approve an approval id")
    parser.add_argument("--reject", default="", help="reject an approval id")
    parser.add_argument("--approve-all", action="store_true", help="approve every pending approval")
    parser.add_argument("--reject-all", action="store_true", help="reject every pending approval")
    parser.add_argument("--show-approval", default="", help="show one approval by id")
    ns = parser.parse_args()
    cfg = load_config(ns.config)
    server = ns.server or cfg.get("server", "http://127.0.0.1:18080")
    token = ns.token or cfg.get("token", "")
    if not token:
        print(json.dumps({"status": "error", "error": "token missing"}, ensure_ascii=False))
        return 2
    if ns.request:
        req_obj = json.loads(Path(ns.request).read_text(encoding="utf-8"))
        action = req_obj.get("action", "")
        args = req_obj.get("args", {})
    else:
        action = ns.action
        try:
            args = json.loads(ns.args or "{}")
        except json.JSONDecodeError as exc:
            print(json.dumps({"status": "error", "error": f"invalid --args JSON: {exc}"}, ensure_ascii=False))
            return 2
    # AI control shortcuts: every human approval/control operation has a
    # first-class command-line path, not just the generic --action call.
    if ns.list_actions:
        action, args = "server.capabilities", {}
    elif ns.pending:
        action, args = "approval.pending", {}
    elif ns.show_approval:
        action, args = "approval.show", {"approval_id": ns.show_approval}
    elif ns.approve:
        action, args = "approval.approve", {"approval_id": ns.approve}
    elif ns.reject:
        action, args = "approval.reject", {"approval_id": ns.reject}
    elif ns.approve_all:
        action, args = "approval.approve_all", {}
    elif ns.reject_all:
        action, args = "approval.reject_all", {}
    elif ns.wait_task:
        action, args = "task.show", {"task_id": ns.wait_task}

    def wait_for_task(task_id: str):
        deadline = time.time() + ns.timeout
        current = None
        while time.time() < deadline:
            time.sleep(0.5)
            current = request(server, request_token, "task.show", {"task_id": task_id}, ns.timeout)
            status = ((current.get("data") or {}).get("status") or "")
            if status in {"succeeded", "failed", "cancelled"}:
                return current
        return current or {"status": "error", "error": "task wait timeout"}

    if not action:
        print(json.dumps({"status": "error", "error": "action is required"}, ensure_ascii=False))
        return 2
    approval_actions = {"approval.approve", "approval.reject", "approval.approve_all", "approval.reject_all"}
    request_token = ns.approval_token if action in approval_actions and ns.approval_token else token
    result = request(server, request_token, action, args, ns.timeout)
    if (ns.wait or ns.wait_task) and result.get("status") == "ok":
        data = result.get("data") or {}
        task_id = ns.wait_task or (data.get("id") if isinstance(data, dict) else None)
        if task_id:
            result = wait_for_task(task_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
