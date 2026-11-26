# PyExec2 Rebuild — Full-System Test Plan

## 1. Purpose
This is the pre-test audit plan. It must be completed before code changes or runtime tests begin. The goal is to validate every externally visible function and every critical internal closure: authentication, transport, payload delivery, task execution, persistence, AI approval, plugin resolution, Web client behavior and restart/reconnect behavior.

## 2. Test Environment
- Server: Python 3.12+/3.13, FastAPI/Uvicorn, data under `data/`, runtime state under `runtime/`.
- Web client: local `clients/web_backend.py` + React build on port 8765.
- Server control API: port 18080.
- Test listeners: isolated high ports where possible.
- Transport tests: UDP, TCP, HTTP, HTTPS, DNS. ICMP is expected to be disabled.
- Browser: Playwright/Chromium headless.

## 3. Authentication and API Surface
### 3.1 Negative auth
- `GET /` without token → 401 with zero-length body.
- `GET /health` without token → 401 with zero-length body.
- `POST /api/action` without token → 401 with zero-length body.
- Wrong token → identical empty 401.
- Authorization header and `x-pyexec-token` compatibility.
- AI worker token must not be accepted as approval authority.
- AI approval token must be distinguishable from human.

### 3.2 Token roles
- Human: all actions, bypass approval.
- AI worker: actions subject to `all_allow`/`per_action`.
- AI approval: can approve/reject.
- Cross-role isolation and session role reporting.

### 3.3 Public payload endpoints
- `GET /p/<payload-token>` works without control token but only with a valid payload token.
- Invalid payload token → no script and no sensitive metadata.
- `GET /api/payloads/<id>/download` requires control token.
- `POST /api/implant/poll` requires valid payload token/envelope.

## 4. Transport Matrix
For each transport: create listener, start/restart/stop/remove, generate payload, download via curl, execute implant, verify heartbeat, execute command, restart server and verify reconnect.
- UDP: current primary transport; payload poll and command result.
- TCP: framed request/response; large result chunking.
- HTTP: `/poll` endpoint and response.
- HTTPS: TLS behavior and certificate handling; record expected verification behavior.
- DNS: DNS query/response encapsulation; size limits.
- ICMP: must be disabled and creation must fail cleanly.

## 5. Payload Delivery and Obfuscation
- Payload download via curl using only `/p/<token>`.
- Payload remains executable after server 401 enforcement.
- Verify payload source is comment-stripped.
- Verify payload source is compressed/base64 wrapped or otherwise not raw source.
- Verify token/key not exposed via control API without auth.
- Verify traffic is ChaCha20-Poly1305 sealed.
- Verify key lifecycle: key is generated per payload, embedded in payload config and stored server-side; no ECDH is claimed.
- Verify replay/tamper behavior at the sealed-envelope level.
- Verify public payload token rotation/unknown token rejection.

## 6. Task Lifecycle and Commands
- `task.create` on online Beacon → queued.
- status transition: queued → dispatched → succeeded/failed/cancelled.
- offline Beacon task creation → explicit error.
- command set: `pwd`, `ls`, `ps`, `sysinfo`, `whoami`, `env`, `cat`, `tail`, `find`, `grep`, `df`, `free`, `ping`, `nmap`, `exec`, `python` script.
- base commands resolve to `l*`/`w*` per Beacon platform.
- long output (>24 KB) must be reassembled completely, not truncated.
- multiple concurrent tasks and result batching.
- terminal and file-view task status trail.

## 7. Running Task Management
- `tasks` resolves to `ltasks/wtasks` and lists active tasks.
- `killtask <task_id>` resolves to `lkilltask/wkilltask`.
- cancellation of Python CPU loop and subprocess `exec sleep`.
- cancel self protection.
- final status must be `cancelled`.

## 8. File Operations
- `file.list`, `file.read`, `file.write`.
- large file read (>200 KB) complete.
- chunked `dd` upload/download.
- binary/text behavior.
- path traversal/symlink assumptions recorded.
- file browser metadata, task progress and truncation flags.

## 9. AI Approval
- `per_action`: AI task.create → approval_required.
- AI worker cannot approve.
- AI approval token can approve.
- Human bypasses approval in both modes.
- bulk approve/reject.
- approval action self-approval behavior.
- approval status visible to Web.

## 10. Beacon Lifecycle and Persistence
- note save/read, stash/restore, per-Beacon note modal.
- 24-hour soft removal and reactivation preserving notes/history.
- server restart; active payload state reload; Beacon reconnect.
- task history/results/notes persist.
- clear-all Beacons invalidates active payloads and cancels queued tasks.

## 11. Plugin System
- Linux/Windows/Server/Transport categories.
- 29 Linux + 29 Windows + 1 server + 6 transport expected at time of this test.
- edit/save/hot-reload plugin.
- create Linux/Windows/server/transport plugin templates.
- auto-resolve base command to platform plugin.
- autocomplete strips l/w prefix.

## 12. Web Client and Human Factors
- first-visit connection gate: scheme, IP, port, token; bad token remains on gate; good token enters app.
- no server Web UI; 18080 root/health require token.
- quick-operation unified list, search, parameter modal and terminal dispatch.
- regex current/next/sticky filters, clear, invalid regex feedback.
- file browser mode/time columns.
- history replay and quick buttons.
- no browser-native prompts for app flows.

## 13. Restart, Failure and Chaos Tests
- server restart during active payload.
- listener stop/restart.
- wrong listener public host.
- oversized result.
- invalid payload token.
- stale Beacon.
- duplicate/unknown chunk handling.
- task created for offline Beacon.

## 14. Evidence and Acceptance
For each item record: command, expected, observed, pass/fail, fix reference.
A final report must include:
- pass/fail matrix
- bugs found and fixes
- remaining limitations
- runtime flow diagram
- ten-point self-review.

## 15. Priority Order
1. Auth and payload download boundary.
2. Online Beacon command execution and result completeness.
3. Transport matrix (UDP/TCP/HTTP first, HTTPS/DNS next).
4. AI approval and restart persistence.
5. File operations, plugin resolution, Web UX.
6. Chaos and final self-review.
