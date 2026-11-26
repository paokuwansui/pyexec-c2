# PyExec2 Integration Matrix

This matrix records how the server, Web client, AI client, payload and implant are connected.

| Capability | Server | Human Web | AI client | Payload/implant link | Status |
|---|---|---|---|---|---|
| Create/stop listeners | `listener.create/stop` | Listeners page | `--action listener.*` | Payload binds to listener protocol/host/port | Done |
| Generate payload | `payload.generate` | Payload workshop form | `--action payload.generate` | Config embedded in source; methods echo/curl/short downloader | Done |
| Payload interval settings | payload options | fast/slow/finish/jitter/concurrency fields | same JSON args | `CONFIG` in payload, heartbeat telemetry | Done |
| Beacon overview | `beacon.list/show` | Overview table; no separate Beacon page | `--action beacon.*` | Beacon record updated on every poll; stale heartbeats become offline | Done |
| Beacon runtime settings | `beacon.settings` → `control.set_runtime_settings` | Beacon info/settings panel | `--action beacon.settings` | Implant updates `CONFIG` and live heartbeat fields | Done |
| Protocol upgrade | `protocol.upgrade` | Beacon protocol upgrade row | `--action protocol.upgrade` | Control task changes host/port/protocol; fallback retained | Done |
| Task dispatch | `task.create` | Command terminal, Python editor | `--action task.create --wait` | Queue → poll → thread execution → result queue | Done |
| Result aggregation | result state | Output in terminal/editor | task.show/--wait | 5s configurable finish window | Done |
| File list/read/write | `file.*` | File editor page | `--action file.*` | maps to `lls/wls`, `lcat/wcat`, `ltee/wtee` | Done |
| Chunked transfer | `file.upload_chunk/download` | 1 MB browser upload loop; chunked download | `--action file.*` | `dd` read/write with offsets | Done |
| Python script delivery | `script.run` | Python editor | `--action script.run` | comment stripping → in-memory execution | Done |
| Command history | local Web backend files | Local history panel | N/A | `clients/local_data/history/*.json` | Done |
| Python templates | local Web backend files | Template save/load | N/A | `clients/local_data/templates/*.py` | Done |
| Plugin creation | `plugin.create/ai_create` | Plugin studio tabs/forms | `--action plugin.create` | Implant plugin loaded on next task | Done |
| Plugin hot reload | `plugin.save/reload` | Plugin editor | `--action plugin.save` | Server hot reload; implant plugin source resolved per task | Done |
| Proxy | `proxy.start/stop/info` | Beacon terminal `proxy start` | `--action proxy.start` | Server SOCKS5 gateway → `proxy` implant plugin tasks | Done |
| Human/AI approval | role-aware `handle_action` | Human bypasses approval; approval page decides | AI actions governed by policy | approval record actor=ai | Done |
| Code sanitization | `CodeDeliveryPipeline` | all Python sends | all Python sends | plugins/scripts/control/payload comments stripped | Done |

## Intentional v1 limits

- ICMP is disabled.
- Proxy is task-relayed, so it is slower than a native persistent tunnel.
- Hard kill is best effort.
- Payloads are transient and not saved as history; server restart invalidates active payload tokens.
- Web upload currently sends one request in the browser path; the `dd` protocol supports offsets for future streaming UI.
