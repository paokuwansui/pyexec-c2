# PyExec2 Rebuild — Implementation Status

## Implemented

- Python 3.12+ FastAPI server on configurable `0.0.0.0:<port>`.
- Token authentication; empty 401 body for invalid/missing token.
- File database under `data/` with atomic JSON writes and JSONL audit events.
- Server hot comment-stripping pipeline for all Python code sent to implants.
- Plugin loader for `implant_plugins/`, `server_plugins/`, `transport_plugins/`.
- Web plugin editor APIs: list/show/save/reload.
- Single-stage payload generation with direct echo, curl, and obfuscated short downloader.
- Pure-Python ChaCha20-Poly1305 envelope encryption.
- UDP, TCP, HTTP, HTTPS, and DNS transport plugins.
- Implant runtime: pull model, parallel tasks, task result queue, 5 second result aggregation window, adaptive heartbeat, best-effort task cancellation.
- Protocol upgrade control task and 30-failure fallback.
- Every implant command has both `l*` Linux and `w*` Windows plugins. Users enter base names (`cd`, `ls`, `cat`, `mkdir`, `ps`, `sysinfo`) and the task engine resolves the platform-specific file.
- Server plugin example: server report.
- SOCKS5 gateway started on demand by the Beacon terminal command `proxy start [port]`, authenticated and task-relayed through an implant.
- Local React web client with listeners, payloads, beacons, file browser/editor, command terminal with autocomplete/history, regex view filtering, plugins, tasks, audit. Proxy is managed from the Beacon terminal, not a separate page.
- One-shot AI client `clients/ai/client_ai.py` with JSON output and optional `--wait`.
- Automated pytest coverage for sanitizer, crypto, auth, plugin platform commands, payload generation, and task source sanitization.

## Known v1 limits

- ICMP is intentionally disabled.
- Server-side permission/trust model is intentionally simple: plugin directory is trusted; actions default to all-allow or per-action approval.
- Proxy is task-relayed, so it has high latency compared with a native reverse tunnel.
- Large-file transfers use 1 MB chunks but the current Web upload path sends one in-memory base64 block; the transport supports chunking for future UI streaming.
- DNS transport is a small TXT/base32 implementation optimized for control-sized frames.
- No automatic result/artifact cleanup by design.

## Manual End-to-End Verification

- Generated single-stage UDP payload downloaded from `/p/<token>` and executed.
- Beacon registered over UDP, TCP, HTTP, HTTPS, and DNS listeners.
- `lsysinfo`, `lps`, and `lls` tasks returned full results.
- Live protocol upgrade from UDP to TCP was executed through a control task; the beacon's reported protocol changed to TCP.
- SOCKS5 gateway started with `proxy start`, authenticated with beacon ID + proxy password, and relayed an echo payload through the implant; `proxy stop` closed it.
- Server plugin `server_report` was loaded and invoked.
- Implant plugin source was saved through the plugin editor API and hot-reloaded.
- Per-action approval mode intercepted a task creation; approving the request executed it.
- Payload and task source were verified to contain no comment-only lines.


## Command Compatibility Additions

- Added Python-native command plugins for common Linux/Windows operations.
- All command families use `l`/`w` prefixes: `lcd/wcd`, `lls/wls`, `lcat/wcat`, `lmkdir/wmkdir`, `ltee/wtee`, `ldd/wdd`, `lsysinfo/wsysinfo`, and so on.
- Common commands were split into Linux and Windows implementations.
- Added `ping` host-liveness probe using TCP ports.
- Added `nmap` concurrent TCP port scanner.
- Web command parser supports single quotes, double quotes, backslash escaping and history navigation.
- `lexec` and `wexec` are explicit dangerous shell-capability plugins; they are not used by the core.
- Verified `lexec` through the implant with quoted arguments.

## Proxy Command Correction

- Removed the separate proxy configuration page from the Web client.
- Proxy is now a Beacon terminal command plugin: `proxy start [port]`, `proxy stop`, `proxy info`.
- `socks` is accepted as an alias.
- The server SOCKS5 listener is not started at server boot; it is created only by `proxy start`.
- Verified starting and stopping the proxy entirely from the Beacon terminal.


## Plugin Studio Categories and Creation

- Web plugin studio now has two explicit category boxes: `植入插件` and `服务端插件`.
- The list only shows the selected category.
- Manual creation via `＋ 新建插件` creates and validates a Python template, then opens it in the editor.
- Added `plugin.create` API for humans, scripts, and external AI clients.
- Verified category filtering and manual template creation through the browser UI.


## Human/AI Parity and Approval

- Added `server.capabilities`, enumerating every action available to the authenticated token.
- Added `approval.pending`, `approval.show`, `approval.approve_all`, and `approval.reject_all`.
- Added a Web `审批` page for viewing/filtering approvals, approving/rejecting single items, bulk approval/rejection, and switching approval mode.
- Added AI CLI flags: `--list-actions`, `--pending`, `--show-approval`, `--approve`, `--reject`, `--approve-all`, `--reject-all`, `--wait-task`.
- Verified AI can create a pending action, list it, approve it, reject it, and bulk-approve pending operations using the same token and API as the Web client.
- Verified the Web approval page can release a pending operation.


## Plugin Naming Policy

- Plugin filenames and command names use Linux command names where a Linux command exists.
- Platform-specific implementations use the `l` and `w` prefix: `lls/wls`, `lcat/wcat`, `lpwd/wpwd`, `lwhoami/wwhoami`, `lenv/wenv`, `lusers/wusers`, `ldf/wdrives`, `lfree/wmem`, `lfind/wfind`, `lgrep/wgrep`, `lkill/wkill`, `lps/wps`, `lnetstat/wnetstat`, `lexec/wexec`, `luname/wsysteminfo`.
- Cross-platform implementations use one command name: `mkdir`, `rm`, `mv`, `cp`, `tail`, `tee`, `dd`, `ping`, `nmap`, `python`.
- Duplicate `fs.*` plugin files were removed. The higher-level `file.*` server actions remain API conveniences and automatically map to `lls/wls`, `lcat/wcat`, `tee`, and `dd` based on the target platform.
- The implant plugin catalog contains no `fs.list`, `fs.read`, `fs.write`, `fs.upload`, or `fs.download`.


## Beacon Workspace Redesign

- Beacon click now opens the command workspace first.
- Added top tabs `命令界面` and `文件编辑界面`.
- Command page contains a command terminal, Python script editor, module-based quick actions, and file-backed command history.
- Python scripts can be sent directly to the implant and saved as local templates under `clients/local_data/templates/`.
- Command history is stored as one JSON file per command under `clients/local_data/history/`.
- File editor page uses a left directory browser and right viewer/editor; text files support view/edit/save, binary files support preview/download.
- Local Web backend exposes `/api/local/history` and `/api/local/templates` file APIs.
- Fixed approval-required handling in the Web action helper so queued approvals do not break file browsing or terminal actions.
- Verified command terminal, Python script send, template saving, local history, directory browsing, and README viewing.


## Payload Shell Quoting Fix

- Removed the old `'"'"'` host-quote escaping pattern from generated payload methods.
- Direct echo and short downloader now put double-quoted Python string literals inside a single-quoted shell wrapper.
- Generated methods contain no interleaved single/double quote sequences.
- Curl payload uses a double-quoted URL.
- Added a regression assertion that generated methods never contain the `'"'"'` sequence.


## Overview, Beacon Telemetry, and Payload Settings

- Removed the separate Beacon list page; Beacons are opened directly from the overview table.
- Removed the overview right-side recent-task queue.
- Added Beacon telemetry fields: current heartbeat interval, fast/slow bounds, jitter, result finish delay, max concurrent tasks, idle rounds, dispatch total, failures, last poll, next poll.
- Added `beacon.settings` action and implant `set_runtime_settings` control operation.
- Beacon workspace now exposes live telemetry and editable runtime settings.
- Added configurable payload options: `fast_interval`, `slow_interval`, `finish_delay`, `jitter`, `max_concurrent_tasks`.
- Payload history is no longer persisted to disk; active payloads are held in server memory only.
- Verified heartbeat settings are reported by a running implant and updated through `beacon.settings`.


## Human/AI Approval Policy

- Added separate Human (`data/server_token.txt`), AI worker (`data/ai_token.txt`), and AI approval (`data/ai_approval_token.txt`) tokens.
- `/api/action` resolves authenticated roles as `human`, `ai`, or `ai_approval`.
- Human-role actions always bypass approval policy, including in `per_action` mode.
- AI worker actions are governed by the current `all_allow` / `per_action` mode.
- AI worker tokens cannot decide approvals.
- AI approval-token holders can approve/reject AI worker operations.
- This supports a two-AI workflow: one AI works, another AI approves.
- AI-created approval records include `actor: ai`.
- Server startup prints all three tokens.


## Final Integration Audit

- Added `docs/INTEGRATION_MATRIX.md` mapping server actions, Web UI, AI client, payload and implant behavior.
- Payload runtime settings are configurable at generation time and can be changed later through `beacon.settings`.
- Beacon workspace displays heartbeat telemetry and allows human runtime setting changes.
- AI client has documented payload settings, beacon settings and protocol upgrade actions.
- Added protocol upgrade control to the Beacon workspace.
- Added heartbeat-age-based offline detection for stale Beacons.
- Verified a fresh payload reports its configured heartbeat fast/slow intervals, jitter, aggregation window and max concurrency.


## Chunked File Transfer Integration

- Added `file.upload_chunk` server action.
- Web file upload now splits files into 1 MB chunks and waits for each `dd` write task.
- Web file download now loops over `file.download` chunks until `eof` and assembles the result locally.
- Verified a two-chunk upload (`hello ` + `world`) produced `hello world` on the target.
- `dd` supports offset and start/append modes for future resume UI.


## Payload History Removal

- Removed legacy `data/payloads` storage.
- Removed legacy `data/beacons/*/payload.json` files on startup.
- Removed `payload.list`, `payload.show`, and `payload.delete` actions.
- Payload workshop no longer renders a payload history list.
- Generated payloads remain only in server memory for the current process so `/p/<token>` can serve them.


## AI Plugin Generation Removed

- Removed the `AI 生成插件` button and modal from the plugin studio.
- Removed `plugin.ai_create` and its OpenAI-compatible generator from the server.
- Manual plugin creation and the `plugin.create` API remain available.


## Beacon Control Separate Page

- Moved `Beacon 信息与回连设置` out of the command page into its own `Beacon 控制` tab.
- Beacon workspace tabs are now: `命令界面`, `文件编辑界面`, `Beacon 控制`.
- Command page only contains command/Python/quick actions/history.
- Beacon telemetry, runtime settings and protocol upgrade controls live on the Beacon control page.


## Overview Consolidation

- Moved listener management into the overview page.
- Moved payload workshop into the overview page.
- Removed separate Listener and Payload pages from navigation.
- Navigation now contains only Overview, Plugin Studio and Approval.
- Verified overview renders Beacon, listener factory/list and payload settings/delivery together.


## cd Command and Working Directory Telemetry

- Added `cd` common implant plugin backed by `os.chdir`.
- Added `cwd` to every Beacon heartbeat.
- Beacon control displays the current target working directory.
- Relative file operations honor the changed directory.


## Listener Removal

- Added `listener.remove` and `listener.delete` aliases.
- Removal stops an active listener, releases the socket, deletes the listener record, and writes an audit event.
- The overview listener list now exposes a `移除` button with confirmation.
- Verified the port is released and the listener disappears from `listener.list`.


## Web Visual Redesign

- Redesigned the Web shell with floating glass sidebar/main panels and a sci-fi command-console aesthetic.
- Added ambient grid and scanline layers, neon edge lighting, hex brand mark, animated signal indicator and status/role/clock header chips.
- Restyled metrics, tables, forms, terminal, Python editor, file editor, plugin studio, approval queue and modals.
- Preserved all existing functionality and navigation behavior.
- Browser smoke test completed with no console errors.


## Python Syntax Highlighting

- Replaced the plain plugin-editor textarea with a syntax-highlighted Python overlay editor.
- The Beacon Python script editor now uses the same component.
- Added syntax token colors for keywords, builtins, strings, numbers and comments.
- Added Tab indentation and synchronized editor scrolling.


## CodeMirror Editor and Cockpit HUD Upgrade

- Replaced the custom textarea overlay with CodeMirror 6 and the Python language extension.
- Plugin editor and Beacon Python editor now have line numbers, folding, bracket matching, autocompletion and syntax highlighting.
- Removed the overlay behavior that could produce misleading text underlines.
- Added a cockpit tactical radar, ring gauges, status annunciators, corner brackets and bottom annunciator strip.


## Parameterized Quick Operations and History Replay

- Added parameter forms to every quick-operation module: files, network, tools and proxy.
- Quick-action command previews update live from parameter fields.
- Added `再次下发` buttons to local command history entries.
- Verified changing the file path updates the generated `lls` command and replaying history starts a new task.


## Beacon Notes

- Added `beacon.note` server action and `note_updated_at` timestamp.
- Added a Beacon note editor on the `Beacon 控制` page.
- Notes are displayed under the hostname in the overview Beacon table.
- Verified UI save persists the note to the Beacon file record.


## Combined Listener and Payload Page

- Added a dedicated `监听与载荷` navigation page.
- Listener factory/list and payload workshop are combined on this page.
- Removed listener/payload modules from the overview; overview remains the cockpit dashboard.
- Navigation is now Overview, Deployment, Plugin Studio, Approval.


## Overview Renamed to Beacon

- Renamed the first navigation/page from `总览` / `COMMAND OVERVIEW` to `Beacon`.
- Page header now reads `Beacon` with Beacon fleet heartbeat/deployment subtitle.
- Topbar context is `BEACON OVERVIEW`.


## Beacon Collapse, Expiry and Restart Reconnect

- Added per-Beacon `收纳` / `恢复` controls and a separate collapsible stash roster.
- Added a custom centered note modal opened by the per-Beacon `备注` button; no browser prompt/dialog is used.
- Added 24-hour heartbeat expiry: stale Beacons are soft-removed from the active list, not deleted.
- Preserved Beacon notes, task/result history and metadata through removal.
- Reconnected removed Beacons are reactivated and show `reactivation_count` / `last_reactivated_at`.
- Persisted active payload runtime state outside the data history directory so payload tokens survive server/control restarts.
- Verified a live Beacon reconnected after a full server restart with its note and heartbeat telemetry intact.


## Offline Beacon Task Guard

- Added server-side online validation before `task.create`, `script.run`, file transfer and file-edit task creation.
- Offline/stale Beacons return a clear `task not dispatched until heartbeat returns` error.
- The Beacon workspace displays an offline warning banner.
- Verified a fresh online Beacon executes `lpwd` successfully.


## Plugin Catalog Audit and Transport Visibility Fix

- Confirmed plugin files were not deleted: 54 implant, 1 server, and 6 transport plugins exist.
- Fixed Plugin Studio filtering so server and transport plugins are visible together.
- Added distinct `服务端` / `传输` badges and separate counts.
- Added transport plugin creation support in the server category.
- Verified DNS/TCP/UDP/HTTP/HTTPS/ICMP entries are visible and a test transport plugin can be created.


## Server Is API-Only

- Removed server-served React root, `/app`, and `/assets` static mounts.
- Server root now returns JSON API metadata (`web_ui: not served by server`).
- Human Web UI is served only by `clients/web_backend.py` on the operator client.
- Added a regression test asserting the server never returns an HTML Web UI.


## No Unauthenticated Server Banner

- Removed the public JSON banner from `/`.
- Root now requires a valid role token; unauthorized requests return empty `401`; authorized root returns `204 No Content`.
- `/health` now also requires a valid token and returns empty `401` without one.
- Verified no token responses have zero-length bodies.


## Web First-Visit Connection Gate

- Added a mandatory local connection screen before the cockpit UI.
- Added local `/api/connect` validation endpoint using the supplied server URL and token.
- Config is saved only after successful remote authentication.
- Invalid tokens remain on the connection screen with an inline error.
- The Beacon/app UI is not mounted until connection succeeds.


## Task Result Transport Batching and UI Progress

- Fixed a stalled Beacon loop caused by oversized UDP poll payloads carrying accumulated task results.
- Replaced result shrinking with hashed 12 KB result chunks and server-side reassembly.
- Large outputs, directory listings and file contents now arrive complete rather than truncated.
- Added chunk-level acknowledgements so multi-chunk results can be sent over UDP safely.
- Added persistent task status under each terminal command: `已下发` → `Beacon 已获取任务` → `已完成`.
- Added the same progress feedback to file list/read/write operations.
- Fixed listener public-host normalization and payload target selection.
- Verified command execution and large-file viewing in the Web UI.


## Detailed Directory Listing Output

- Replaced the summary-only `lls/wls` output with a formatted permission/size/time/name table.
- Added `ctime` and `atime` to directory entry data and retained `mtime` for display.
- Added Web-side formatting fallback from `data.entries` for terminal output.
- Added mode and modification-time columns to the Web file browser.
- Verified terminal output contains permissions, timestamps and filenames.


## Regex Filter Fix

- Fixed `筛选当前屏幕` being ignored by the terminal renderer.
- Implemented current, next-result and sticky filter semantics.
- Added clear button, active filter indicator and regex syntax validation.
- Verified current-screen filtering hides non-matching lines and clear restores them.


## Quick Command Parameter Dialog

- Reworked quick actions into command definitions with per-command parameters and hints.
- Added centered parameter modal with command description, parameter help, live command preview and execute button.
- Execute switches to the command terminal and sends the command through the normal `runCommand` path.
- Verified `ls` modal parameter updates the preview and displays `bigtest.txt` in the terminal after execution.


## Complete Long Output Verification

- `exec seq 1 20000` produced 108,895 characters and displayed completely in the Web terminal.
- `/tmp/bigtest.txt` returned all 202,000 bytes with `eof: true`.
- Added a regression test that reassembles a 120 KB output plus 60 KB data payload without truncation.


## Running Task Management Plugins

- Added `ltasks/wtasks` for listing active Beacon tasks.
- Added `lkilltask/wkilltask` for force-cancelling a selected active task.
- Active task metadata now includes plugin, display name, mode and elapsed time.
- Added Web command parsing and quick-action entries for `tasks` and `killtask`.
- Verified a runaway Python task was listed, cancelled, and recorded as `cancelled`.


## Forced Cancellation Covers Subprocesses

- `lexec/wexec` now register their child process with the implant task runtime.
- `killtask` terminates the tracked subprocess, raises an async exception in the task thread and marks the task `cancelled`.
- Verified `exec sleep 20` was terminated after cancellation and reported `cancelled`.


## Unified Quick Command Browser and Aligned Layout

- Removed the quick-operation module dropdown.
- Flattened all 23 commands into a single scrollable list with category labels.
- Added quick-command search across labels, commands and descriptions.
- Reworked the command workspace into two grid rows so the Python delivery and command history panels align exactly.


## Full Audit and Verification Session

- Created `docs/FULL_SYSTEM_TEST_PLAN.md` before testing.
- Verified all supported transports (UDP/TCP/HTTP/HTTPS/DNS) with real payloads and command execution; ICMP remains disabled.
- Added DH key agreement, replayed-poll rejection, certificate pinning, result chunking and task wire-size guards.
- Fixed local Web auth/token leakage, AI self-approval, mv/cp parsing, file download guards, plugin rename cleanup and non-UTF8 templates.
- Added regression coverage and recorded evidence in `docs/test-evidence/`.
- Current automated suite: 28 passing tests.
- Full report: `docs/FULL_SYSTEM_TEST_REPORT.md`.
- Runtime flow diagrams: `docs/PROGRAM_FLOW.md`.


## Beacon Grouping and Serial Auto Task Sequences

- Added `group.*` actions for create/list/update/delete and group batch dispatch.
- Added per-Beacon `beacon.auto.set` and `beacon.auto.run`.
- Auto sequences are persisted in `queues/<beacon>/auto_state.json` and claim one task at a time.
- Added a global automatic command list that applies to every Beacon on reconnect, independent of group.
- Added inline group editor and global auto-command editor below the Beacon table.
- Added drag-and-drop/up/down ordering for global auto commands.
- Group commands are manual batch-only and use the `批量下发` button.
- Beacon table and stash roster now replace each other in the same visual slot.
- Regression tests for serial claiming and group CRUD/batch dispatch.
- Current automated suite: 30 passing tests.


## Payload Copy and Windows Loader Fix

- Added clipboard fallback for non-secure/local contexts.
- Added copy-state feedback in payload workshop.
- Replaced XOR-obfuscated second-stage loader with plain base64 URL encoding.
- Verified generated methods contain no `^` and clipboard receives the full command.


## Runtime Settings Plugin

- Added Linux `lsettings` and Windows `wsettings` plugins.
- Base command `settings` supports `--min/--fast`, `--max/--slow`, `--current`, `--jitter`, `--finish/--aggregate`, and `--concurrency/--workers`.
- Unspecified fields are omitted and keep their current Beacon values.
- Added Web command parsing and a `回连参数设置` quick-action modal with six optional fields.


## Protocol Upgrade and Independent Fork

- Added `lupgrade/wupgrade` with URL/host, port, protocol, optional token and 32-byte base64 key.
- Added pending upgrade handshake: ack sealed with old key, server rotates token/key, implant applies after ack.
- Added `lfork/wfork` with double-fork + setsid on POSIX and detached process fallback on Windows.
- Verified parent exit does not affect forked Beacon; one-fork guard prevents recursion.


## Command History Scroll Containment

- Constrained the history list to a 360px internal scroll viewport.
- Verified 40 history entries produce a scrollbar while the Python panel remains 442px high.
- Verified empty history preserves the normal bottom-row height.


## AI Tutorial Page

- Added an AI integration manual page below Approval in navigation.
- Includes API request format, token roles, action examples, approval workflow, task polling, platform command resolution, group/global-auto semantics, safety boundaries and prompt templates.
- Added a copy button; clipboard fallback works on local HTTP.
- Verified full guide text is copied to clipboard and button shows `已复制`.


## Quick Operation Panel Fill

- Changed quick command list to flex-fill the available panel height.
- Removed the previous fixed max-height that left a large blank area below the list.
- Verified list scrolls internally while the panel remains aligned with the terminal.


## Parameterless Quick Actions

- Quick actions with `params: []` now execute immediately without a modal.
- Parameterized quick actions continue to use the parameter dialog.
- Verified no-parameter `tasks` dispatch and parameterized `settings` modal behavior.


## Dynamic AI Guide Context

- Added protected local `/api/ai-guide-context`.
- AI guide dynamically replaces server URL, scheme, host, port, local Web URL, project directory, AI client path and Human/AI Worker/AI Approval tokens.
- Verified all three current tokens and server address appear in the rendered and copied guide; unresolved placeholders are absent.


## Comment Stripping Coverage

- Confirmed script and plugin sources are comment-stripped by the delivery pipeline.
- Added stripping for inline Python `args.code`.
- Kept shell `exec` command strings verbatim because shell comments are semantic.
- Regression test covers inline Python comments; suite now 32 passing tests.


## AI Guide Python Execution Focus

- Added a detailed `script.run` delivery/execution tutorial with JSON examples and expected result fields.
- Added approval, offline, timeout, output and error handling guidance.
- Added Python-specific AI prompt templates and curl/AI client examples.
- Verified dynamic copy contains the full section and actual environment values.


## Beacon Page Scroll Preservation

- Added a page scroll ref and layout-effect restoration in Overview.
- Verified scrollTop remains 1082 after a 6-second auto-refresh.
- Verified scrollTop and an in-progress group-name edit survive a refresh while focused.


## Auto-Task History Visibility

- Marked auto-sequence tasks in task records with `auto_sequence=true`.
- Beacon terminal now loads recent `task.list` history for that Beacon and displays it alongside live entries.
- Auto-task entries show `AUTO` status and historical timestamp.
- Verified the command interface shows auto sysinfo/pwd history after Beacon reconnect.


## Beacon Drag Ordering

- Added `beacon.order.set` and persistent `data/beacon_order.json`.
- `beacon.list` sorts by manual order before heartbeat time.
- Added drag handles and drop targets for online Beacon rows; dragging persists the order and refreshes the list.
- Verified first two rows swap and API order changes accordingly.
- Automated suite: 33 passing tests.


## Full Outage / Restart Persistence Test

- Stopped server and Web backend completely; verified all service/listener ports closed.
- Restarted both; 20 Beacon processes reconnected.
- Verified note, task history, task output, listeners, group and global auto commands persisted.
- Web UI displayed the note and preserved task history after restart.


## Kill Beacon Plugin

- Added `lkillbeacon/wkillbeacon` with delayed self-termination after result acknowledgement.
- Added Web command parsing and command help.
- Verified result is delivered before process exit; Beacon becomes offline after timeout.


## Beacon Notes in Group Picker

- Added inline Beacon note labels beside hostnames in the group membership picker.
- Empty notes render as `无备注`; long notes are ellipsized.
- Verified a saved note appears in the group settings list.


## Beacon List Internal Scrolling

- Set the Beacon fleet table to a 489px viewport and normalized every Beacon row to 46px, so exactly ten rows are visible before scrolling.
- Right-side scrollbar appears for long fleets; mouse wheel scrolls the list without scrolling the whole page.
- Made the Beacon table header sticky.
- Verified 21 rows: client height 520, scroll height 835, scrollbar enabled.


## Built-in AI Agent Mode

- Added `AI 模式` navigation page with model setup, role prompt and thinking strength; moved `AI 教程` below AI mode.
- Added local `/api/ai-agent/config`, `/api/ai-agent/memory` and `/api/ai-agent/chat` endpoints.
- Implemented OpenAI-compatible tool-calling loop with `c2_action` and `remember`.
- Added 200-entry durable memory with add/edit/delete UI; memory is stored separately from chat context.
- Verified setup screen, config masking, memory CRUD, mock tool-call loop and UI trace display.


## Arbitrary-Server Protocol Upgrade Form

- Replaced listener selection with protocol, IP/URL, port, Token and key inputs in Beacon control.
- URL targets (including embedded port) are supported; plain host/IP targets use the port field.
- Upgrade dispatches the base `upgrade` plugin with pending key/token rotation.
- Verified task success and UDP -> TCP protocol transition through the UI form.


## Editable AI Tutorial Template

- Added edit/save/cancel/reset controls to the AI tutorial.
- Edit mode displays raw template placeholders; view mode and clipboard copy resolve them with current environment values.
- Verified placeholders are visible only in edit mode, saved edits persist after reload, and reset removes test edits.


## AI Model Auto-Discovery and Connection Test

- Added `/api/ai-agent/models` and `/api/ai-agent/test`.
- Simplified provider format selector to exactly two modes: `OpenAI` and `Anthropic`.
- OpenAI uses Chat Completions; Anthropic uses Claude Messages.
- Setup UI now supports model autofetch, test status, actual AI reply display and a polished two-column layout.
- Success requires the model to actually reply with `连接成功`; a different reply is shown as a failed test.


## AI Setup Alignment

- Removed the 1080px width cap from the AI connection configuration panel.
- The panel now spans the full content width and its right edge aligns with the `连接 AI 模型` hero/header (both 1162px in the desktop test viewport).


## AI Tutorial Markdown Rendering

- Integrated `react-markdown`, `remark-gfm` and `remark-breaks`.
- View mode starts in raw-text mode with a `Markdown 渲染` button; clicking it renders Markdown and changes the button to `显示原文`.
- Edit mode intentionally shows only the raw textarea/placeholders, with no Markdown preview.
- Default Chinese numbered sections are displayed as H2 headings.
- Verified edit-mode Markdown (`# heading`, bold, inline code, lists) renders correctly and reset restores the default guide.


## Local Notebook

- Added protected notebook CRUD endpoints under `/api/notebooks`.
- Added notebook list, title/content editor, save/delete and Markdown preview.
- Verified create/update/list persistence and UI Markdown rendering; test notebooks were cleaned up.


## Notebook Layout Alignment

- Set notebook sidebar width to 236px and stretched both panels to the same height/top alignment.
- Verified 15 saved notebooks: list viewport 702px, content 1103px, internal scrollbar enabled.


## AI Defaults

- Changed AI setup defaults to DeepSeek official API (`https://api.deepseek.com`) and model `deepseek-flash`.
- Kept OpenAI-compatible Chat Completions format and `max` thinking strength; API key remains unset until entered.


## Standard and Red-Team Notebooks

- Added `category` and `ai_skill` fields to notebook records.
- Split notebook list into standard and red-team sections with independent scrolling.
- Added a creation chooser modal for standard vs red-team notes.
- Enabled red-team notes are injected into the built-in AI Agent system prompt as skills.
- Verified UI creation, AI skill toggle and real mock-LLM system-prompt injection.


## AI Mode Layout

- Removed the left settings sidebar from the main AI mode view.
- Placed Agent chat on the left and durable memory on the right.
- Moved provider/model/role/thinking settings into a header-launched modal.
- Verified chat x=291 and memory x=1123 with no sidebar settings panel and a working settings modal.


## AI Reset and Skills Configuration

- Added protected `/api/ai-agent/config/reset`; deletes saved model/API-key configuration without touching memories or notebooks.
- Added `回退基础设置` confirmation modal and setup-screen return.
- Added `AI 配置` modal with role prompt and red-team notebook Skill toggles.
- Verified API key invalidation, setup-screen return, Skills visibility/toggle and memory preservation during reset.


## AI Chat Markdown and Titled Memory

- Added default-on Markdown rendering toggle to Agent chat.
- Upgraded memory schema to `title` + `content` with migration from old `text` entries.
- Added title-only memory list and centered view/edit modal with Save/Delete.
- Updated the AI `remember` tool to accept title and content.
- Verified rendered strong/list Markdown, raw toggle, hidden memory content in the list and persisted edits.


## Sidebar Navigation Order

- Reordered sidebar to Beacon, 监听与载荷, AI 模式, 记事本, 审批, 插件, AI 教程.
- Plugin Studio remains directly accessible before the AI tutorial.


## Agent Tool Budget

- Removed the fixed tool-call iteration limit; the agent loop now continues until the model returns a final response.
- Updated the system prompt to request efficient calls and a final summary when complete.
- Verified a normal tool-call sequence still returns successfully with unlimited loop mode.


## Encrypted AI Configuration Persistence

- Added Fernet encryption-at-rest for AI configuration with a 0600 local key file.
- Added atomic encrypted writes and migration from legacy plaintext config.
- Verified the saved API key/model/role prompt survive a Web backend restart and the UI opens directly into Agent chat.


## AI Thinking / Queue / Interrupt / Stop / Approval

- Added provider reasoning extraction (`reasoning_content`, Claude thinking blocks, Gemini thought parts).
- Added separate styled thinking blocks and Markdown final responses.
- Added default bottom queue plus one-click emergency stop next to the Send button with tracked queue cancellation.
- Added `approval_mode` config (`human` / `ai` / `none`) and human approval modal before tool execution.
- Verified queue auto-dispatch, interrupt replacement, human approval resume and separate thinking rendering.


## Human Approval and Emergency Stop Verification

- Human approval mode pauses before tool execution and shows the tool name, arguments and current reasoning.
- Approval resumes the run; denial feeds a denial result back to the model.
- Emergency stop cancels task IDs created by the active run; verified a real `exec sleep 20` task became `cancel_requested`.
- Queue mode runs the next queued user message after completion; interrupt mode appends an interruption marker and starts the inserted message immediately.


## AI Git-Style Execution Trace

- Moved durable memory to a full-width bottom panel.
- Added right-side vertical timeline for user input, AI output, system events, tool calls and live status.
- Tool call args/results render as complete scrollable JSON; thinking remains separately styled.
- Verified trace layout and full command content with a mock C2 tool call.


## Top-Right Memory Manager

- Moved memory access to a `查看记忆 (N)` header button and centered two-column manager modal.
- Left column lists memory titles; right column edits title and full content with save/delete.
- Removed the bottom memory panel while retaining the Git-style AI execution trace on the right.
- Verified title selection, content edit persistence and modal reopen behavior.


## Emergency Queue Stop

- Added `beacon.stop_queue` and `TaskEngine.purge_queued`; only status=queued tasks are cancelled, dispatched tasks are untouched.
- Added command-screen 急停 and control-screen queue viewer/clear button.
- AI stop now clears queued tasks for run-created Beacons through the same server action.
- Verified three queued tasks cancelled, queue file emptied, and AI-created queued task cancelled.


## Automatic AI Session Entry

- Changed AI-mode gating to depend only on `api_key_set`; Base URL is defaulted server-side.
- Split config loading from memory/notebook loading so config errors do not masquerade as unconfigured setup.
- Added retry/error state for actual config-load failures.
- Verified a stored API key opens Agent chat immediately and survives browser reload.


## Editable Bottom AI Queue

- Replaced the send-mode selector with a default queue behavior.
- Added a bottom queue list with inline editing and per-item `↑` promote-to-interrupt controls.
- Promoted item aborts the active run and starts immediately; remaining queue entries are preserved.
- Verified two queued items, inline edit, promotion marker and one remaining queue item.


## AI Stop Button Position

- Removed the AI emergency-stop button from the chat panel header.
- Placed `发送` and `急停` together at the right side of the chat input area.
- Markdown rendering toggle remains in the chat panel header.


## Queue Panel Below Agent Chat

- Moved queue conversations out of the chat panel into a separate full-width Panel below the AI grid.
- Added per-item delete controls and retained inline editing and `↑` promote-to-interrupt.
- Capped queue viewport to about ten rows with internal scrolling.
- Verified chat height remains 820px with 12 queued messages; deleting one reduced to 11.


## AI Agent Navigation Persistence and Audit

- Mounted AI Agent in a persistent hidden page container so page navigation no longer clears chat/queue state.
- Added `X-PyExec-Origin: ai-agent` on local AI tool C2 requests; runtime audit events include `origin` alongside actor and args.
- Verified user message, final answer and thinking persisted across navigation; AI `server.capabilities` appeared in audit.tail with origin ai-agent.


## Real-Time AI Agent SSE

- Added SSE streaming endpoints and event emission for status/reasoning/tool call/tool result/partial output.
- Replaced frontend chat requests with a streaming reader; right trace updates while the Agent is running.
- Verified mid-run thinking/tool/result visibility, final Markdown output, human approval resume and emergency stop during a stream.


## AI Live Output Auto-Follow

- Added per-panel follow-bottom state for the Agent chat and execution trace.
- User scroll-up disables follow until they return to the bottom; programmatic follow does not disable it.
- Verified live output following, stay-at-top while running, and resuming follow after scrolling back down.


## Default Red-Team Notes

- Added a manifest-driven default note pack under `clients/default_redteam_notes/` (index + chapters 1-15).
- Added one-time seeding into the notebook store with `builtin=true` and `source=system-default`.
- Verified 16 red-team notes on first and second load with no duplicates.
- Notes are disabled as AI Skills by default to avoid prompt bloat; operators can enable them in AI configuration.


## AI Agent Server Approval Integration

- Routed AI Agent `c2_action` calls through the AI Worker token for server-side approval enforcement.
- Added AI approval-required handling to tool results and system prompt.
- Verified pending `task.create` with actor=ai in approval.pending and the Approval UI; human approval executed the action.
- Kept emergency queue purge on the human token for immediate operation.


## Red-Team Notes v2

- Expanded chapters 1-15 with command quick-reference blocks, parameter hints, and expected paths.
- Added a chapter-to-tool index and placeholder glossary.
- Added fingerprint-based seed refresh for built-in notes.
- Verified notebook UI renders the expanded chapter commands and tool index.


## AI Approval Wait/Resume

- Added server-approval polling inside the AI agent tool loop.
- SSE events `approval_wait` / `approval_resolved` drive an AI-page banner and direct navigation to approvals.
- Approved tool results are returned to the AI and the original run resumes.
- Failed approved actions are marked `failed` so the agent receives an error instead of waiting forever.


## Payload Obfuscation

- Added per-row `混淆模式` toggle to the payload delivery panel.
- Added `payload.obfuscate` action with random XOR + zlib + Base64 launcher generation.
- Reordered delivery methods to Direct Echo, Short Python Downloader, Curl.
- Updated the served payload source and persisted active payload when obfuscation toggles.
