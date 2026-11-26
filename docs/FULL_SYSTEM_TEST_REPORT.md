# PyExec2 Rebuild — Full-System Test & Repair Report

Date: 2026-11-25
Scope: server API, local Web client, payload generation, transports, implant runtime, task engine, plugins, AI approval, persistence and failure paths.

## 1. Executive Summary

The system was tested across authentication, five transport protocols, payload delivery, DH key agreement, encrypted polling, command execution, large result transfer, file operations, task cancellation, AI approval, restart/reconnect and Web UX.

Result: **the core C2 path is functional end-to-end**, but the audit also found several real security and logic defects. The most important ones were fixed:

- public payload download contained raw source and a reusable symmetric key;
- payload download and control APIs had authentication gaps;
- large results could overflow UDP and stall a Beacon;
- large task payloads could overflow the outbound UDP path;
- AI approval token could approve its own operation;
- `mv`/`cp` Web argument parsing dropped the target path;
- file download loop had no failure/limit guard;
- plugin rename left orphan files;
- local Web backend leaked the control token and allowed unauthenticated proxying.

## 2. Final Test Matrix

### 2.1 Authentication / API Boundary

| Test | Expected | Result |
|---|---|---|
| `GET /` no token | empty 401 | ✅ |
| `GET /health` no token | empty 401 | ✅ |
| wrong token | empty 401 | ✅ |
| human token root | empty 204 | ✅ |
| human session role | `human` | ✅ |
| AI worker role | `ai` | ✅ |
| AI approval role | `ai_approval` | ✅ |
| `GET /p/<valid token>` without control token | launcher bytes, no empty-body block | ✅ |
| `GET /p/<invalid token>` | empty 404 | ✅ |
| local `GET /api/config` | server address only, no token | ✅ |
| local `/api/action` no `X-PyExec-Auth` | 401 | ✅ |
| local `/api/session` no auth | 401 | ✅ |
| local config file permissions | 0600 | ✅ |

### 2.2 Transport Matrix

| Protocol | Listener | Payload online | `pwd` task | Result |
|---|---|---|---|---|
| UDP | ✅ | ✅ | ✅ succeeded | ✅ |
| TCP | ✅ | ✅ | ✅ succeeded | ✅ |
| HTTP | ✅ | ✅ | ✅ succeeded | ✅ |
| HTTPS | ✅ | ✅ | ✅ succeeded | ✅ |
| DNS | ✅ | ✅ | ✅ succeeded | ✅ |
| ICMP | rejected as disabled | n/a | n/a | ✅ expected |

Evidence: `docs/test-evidence/transport_matrix_dh.json`, `.log`, `transport_matrix_dh.txt`.

### 2.3 Payload Delivery / Crypto

| Test | Result |
|---|---|
| `/p/<token>` works via `curl | python3` | ✅ |
| Payload is not raw readable source | ✅ compressed/base64 launcher |
| Launcher compiles as Python | ✅ |
| Launcher contains only public DH material, no `dh_private` | ✅ |
| Traffic uses ChaCha20-Poly1305 AEAD | ✅ |
| Manual DH first poll decrypts successfully | ✅ |
| Replay of same sealed poll rejected | ✅ TimeoutError/no response |
| Tampered/invalid envelope rejected | ✅ empty 400/no result |

Key model:

```text
Server per payload: DH private + DH public
Payload: ephemeral client DH private/public
First poll: payload sends client public value
Both sides derive: shared = pow(peer_public, own_private, RFC3526 prime)
AEAD key = SHA-256(shared || "pyexec2-dh-v1" || beacon_id)
```

This removes the pre-shared symmetric key from the downloaded payload. The payload token is still a bearer value and must be protected.

### 2.4 Task Lifecycle

| Test | Result |
|---|---|
| task created on online Beacon | ✅ queued |
| Beacon claim | ✅ dispatched |
| terminal status | ✅ succeeded/failed/cancelled |
| task creation on offline Beacon | ✅ rejected |
| long output > 24 KB | ✅ full reassembly |
| `exec seq 1 20000` | ✅ 108,895 chars complete |
| `grep` output 270,893 chars | ✅ complete |
| Web status trail | ✅ 已下发 → Beacon 已获取任务 → 已完成 |
| multiple concurrent task results | ✅ chunked and acked |
| cancel CPU loop | ✅ `cancelled` |
| cancel `exec sleep` subprocess | ✅ child terminated, task `cancelled` |
| `tasks` plugin | ✅ lists task id/plugin/elapsed/mode |
| `killtask` plugin | ✅ resolves to `l*`/`w*` implementation |

### 2.5 Command Matrix

15/15 commands succeeded against an online Linux Beacon:

```text
pwd, ls, ps, sysinfo, whoami, env, cat, tail,
find, grep, df, free, ping, nmap, exec
```

Evidence: `docs/test-evidence/command_matrix.json` and `.log`.

### 2.6 File Operations

| Test | Result |
|---|---|
| directory listing with permissions/size/mtime | ✅ |
| file read 202,000 bytes | ✅ complete, eof=true |
| multi-chunk upload 25,600 bytes / 8KB chunks | ✅ byte-for-byte equal |
| file download chunk | ✅ 8,192 bytes, eof=true |
| oversized task wire payload | ✅ rejected with 20KB guidance |
| Web upload loop | ✅ now uses 8KB chunks |
| Web download infinite-loop guard | ✅ max 4096 chunks + zero-progress abort |

### 2.7 AI Approval

| Test | Result |
|---|---|
| human bypass in per_action | ✅ |
| AI worker creates task | ✅ approval_required |
| AI worker attempts approval | ✅ rejected |
| separate AI approval token approves AI worker task | ✅ approved |
| bulk approve | ✅ |
| AI approval self-approval | ✅ rejected |
| Web approval page approves AI-created item | ✅ |

### 2.8 Persistence / Restart

| Test | Result |
|---|---|
| Beacon note survives server restart | ✅ note `重启持久化测试备注` preserved |
| active DH payload survives server restart | ✅ Beacon online + `pwd` succeeds |
| task history/results survive restart | ✅ |
| 24-hour stale Beacon soft removal | ✅ unit test |
| reactivation preserves note/history | ✅ unit test |
| stash/restore preserves record | ✅ unit test |
| clear fleet cancels queued tasks and activates payload tokens | ✅ |

### 2.9 Beacon Groups and Auto Task Sequence

| Test | Result |
|---|---|
| create group | ✅ |
| assign Beacon to group | ✅ |
| edit group auto tasks | ✅ |
| group filter dropdown | ✅ only selected group Beacons shown |
| per-Beacon auto task editor | ✅ saves command sequence |
| per-Beacon auto tasks trigger after reconnect | ✅ |
| global auto commands apply to all Beacons | ✅ |
| serial claim: one task at a time | ✅ |
| auto sequence completion before normal heartbeat | ✅ |
| group batch dispatch | ✅ |
| group manager UI | ✅ no browser native prompt |
| auto list direct/manual run | ✅ |

Evidence: `docs/test-evidence/auto_tasks.txt` and `group_ui_test` interaction.

### 2.10 Web UX

| Test | Result |
|---|---|
| first-visit connection gate | ✅ |
| token no longer prefilled from server | ✅ |
| bad token stays on gate | ✅ |
| correct token enters cockpit | ✅ |
| quick operations one scrollable list | ✅ 23 commands |
| quick search | ✅ e.g. “端口” → 3 |
| quick parameter modal + hints + preview | ✅ |
| execute quick command in terminal | ✅ |
| regex current/next/sticky | ✅ |
| regex clear + invalid syntax error | ✅ |
| note fonts enlarged | ✅ modal 14px / control 13px |
| file browser mode/time columns | ✅ |
| server serves no HTML Web UI | ✅ root 401/204 empty |

## 3. Bugs Found and Fixes

1. **Raw payload + embedded symmetric key**
   - Fixed: self-decoding compressed/base64 launcher over `/p/<token>`.
   - Fixed: per-payload DH key agreement; downloaded source has no `dh_private` or pre-shared key.
2. **Replayable poll messages**
   - Fixed: new payloads send `sent_at`/`nonce`, server rejects stale/replayed polls.
3. **Oversized UDP result stalls**
   - Fixed: 12KB result chunks, hash verification, server reassembly, chunk-level ack.
4. **Oversized task delivery**
   - Fixed: 20KB task wire guard; UI upload uses 8KB chunks.
5. **Local Web backend token leak**
   - Fixed: `/api/config` returns only server; local APIs require `X-PyExec-Auth`; token no longer prefilled from server.
6. **AI approval self-approval**
   - Fixed: approver actor tracked through dispatch; AI approval cannot approve its own request.
7. **`mv`/`cp` target dropped**
   - Fixed: removed from generic path branch; source/target now mapped correctly. Verified real `mv`.
8. **File download unbounded loop**
   - Fixed: max chunk count and zero-progress abort.
9. **Non-UTF8 template caused list 500**
   - Fixed: decode with replacement.
10. **Plugin rename left orphan file**
    - Fixed: `plugin.delete` action and rename cleanup.
11. **Listener public host mismatch**
    - Fixed: bind/public normalization and migration.
12. **Server error responses leaked exception class names**
    - Fixed: API errors now return plain messages.
13. **HTTPS payload accepted any certificate**
    - Fixed: payload pins the server certificate and requires verification (hostname check disabled for self-signed/local IP deployments).

## 4. Remaining Known Limitations

These are documented rather than falsely marked fixed:

- Payload URL/token is still bearer-only; no TTL, one-time download, IP/UA binding. If the URL leaks, an attacker can fetch the launcher and attempt impersonation.
- DH is finite-field per-payload; server DH private material is stored server-side (0600) and replay cache is memory-only across server restarts.
- DNS transport works on a local UDP path, but large queries/responses are not standard DNS-resolver-safe; no DNS fragmentation/retry layer.
- HTTPS uses a self-signed pinned certificate and disables hostname verification.
- Local Web UI uses `sessionStorage` for the client token; a same-origin XSS would expose it. No CSP is currently set.
- `all_allow` mode by design lets AI workers perform actions without approval. Use `per_action` for separation of duties.
- Arbitrary path file operations are intentional C2 capability; path policy is operator responsibility.
- Web uses polling, not WebSocket push.

## 5. Evidence Files

```text
docs/test-evidence/auth_payload_security.txt
docs/test-evidence/ai_approval.txt
docs/test-evidence/ai_self_approval.txt
docs/test-evidence/replay_test.txt
docs/test-evidence/transport_matrix_dh.json
docs/test-evidence/transport_matrix_dh.log
docs/test-evidence/transport_matrix_dh.txt
docs/test-evidence/command_matrix.json
docs/test-evidence/command_matrix.log
docs/test-evidence/file_operations.txt
docs/test-evidence/restart_and_commands.txt
```

Automated tests:

```text
30 passed
```

## 6. Ten-Point Self-Review

1. Did I test the auth boundary after adding 401 behavior? Yes: root/health/action/session, empty bodies, wrong token, local proxy.
2. Did I verify curl payload delivery still works through the public payload token? Yes: downloaded launcher and executed it.
3. Did I verify traffic is encrypted rather than only obfuscated? Yes: AEAD poll decrypted manually; replay rejected; no raw command is sent as the transport body.
4. Did I fix the key-exposure problem rather than only rename it? Yes: downloaded payload now carries DH public material, not the AEAD key/private value.
5. Did I test every supported transport, including HTTPS and DNS? Yes: UDP/TCP/HTTP/HTTPS/DNS all online and executed `pwd`; ICMP rejected.
6. Did I test long output and large files, not just small commands? Yes: 108,895-char and 270,893-char outputs; 202,000-byte file; chunked upload/download.
7. Did I test both operating sides of AI approval? Yes: AI worker creates, AI approval approves; worker cannot approve; self-approval rejected.
8. Did I test restart and persistence? Yes: Beacon note preserved, active payload reconnected, post-restart task succeeded.
9. Did I address human-facing failures rather than only backend errors? Yes: task status trail, quick parameter modal, regex fix, note errors, file metadata, connection gate.
10. Did I leave a clear list of remaining limitations? Yes: Section 4 lists bearer-token risk, DNS limits, pinned TLS caveat, sessionStorage risk, `all_allow` behavior and polling.

Conclusion: the tested core flows are closed end-to-end. Remaining items are architectural/security trade-offs or explicitly documented limitations, not hidden functional failures.


## 12. Payload Workshop Clipboard and Windows Loader Fix

| Test | Result |
|---|---|
| Copy payload command in browser | ✅ clipboard contains full command |
| Copy button feedback | ✅ changes to `已复制` |
| Clipboard fallback for HTTP/non-secure context | ✅ textarea + execCommand fallback |
| Short second-stage loader contains no `^` | ✅ |
| Short loader is plain base64 URL | ✅ decoded URL matches `/p/<token>` |
| Direct echo contains no `^` | ✅ |

The previous second-stage loader used XOR (`b ^ 0x5A`), which is a Windows `cmd` escape hazard. It is now plain base64 and contains no caret characters.

Automated tests remain: **30 passed**.


## 13. Runtime Settings Plugin

| Test | Result |
|---|---|
| `settings` resolves to `lsettings` / `wsettings` | ✅ |
| partial update with only `fast_interval` | ✅ other settings unchanged |
| partial update with `slow_interval` + `jitter` | ✅ other settings unchanged |
| Web parser `--min --max --current --jitter --finish --concurrency` | ✅ |
| quick-action modal six optional fields | ✅ |
| empty fields omitted from generated command | ✅ |

Verified Web command:

```text
settings --max 20 --min 4 --current 7 --jitter 0.1 --finish 2 --concurrency 3
```

Observed Beacon settings:

```text
fast=4.0  slow=20.0  jitter=0.1  finish=2.0  concurrency=3
```

Automated tests: **31 passed**.


## 14. Protocol Upgrade and Independent Fork

| Test | Result |
|---|---|
| `upgrade` resolves to `lupgrade/wupgrade` | ✅ |
| host/url + port + protocol parsing | ✅ |
| optional token/key flags | ✅ |
| UDP -> TCP protocol switch | ✅ |
| key rotation after sealed acknowledgement | ✅ |
| subsequent `pwd` over TCP | ✅ |
| `fork` resolves to `lfork/wfork` | ✅ |
| double-fork detaches with PPID 1 | ✅ |
| parent process killed, forked Beacon survives | ✅ |
| forked Beacon executes task after parent exit | ✅ |
| second fork blocked by one-fork guard | ✅ |

Evidence: `docs/test-evidence/upgrade_fork.txt`.
