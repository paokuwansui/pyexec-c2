# Web 前端 / 任务插件 / 本地 Web 后端 只读代码审计报告

> Post-audit status (2026-11-25): several findings in this report were remediated after the audit. See `docs/FULL_SYSTEM_TEST_REPORT.md` for the final pass/fail matrix, fixes and remaining limitations. This file is retained as the original read-only audit evidence.


- 审计对象：`clients/web/src/App.jsx`（1216 行）、`clients/web/src/styles.css`（469 行）、`clients/web/src/main.jsx`、`clients/web_backend.py`（220 行）
- 交叉验证（只读）：`server_core/runtime.py`、`server_core/task_engine.py`、`server_core/app.py`
- 审计方式：只读代码审计 + 调用链静态核对；未修改任何代码、未杀进程、未清理数据
- 严重级别：Critical / High / Medium / Low / Info
- 结论：**Web 前端自带 XSS 面很窄（全量 React 转义、无 dangerouslySetInnerHTML），真正的风险集中在"本地 Web 后端 = 无鉴权 + 0.0.0.0 + 明文回吐 Token + CSRF 可写模板"这条链上；功能性缺陷集中在命令参数解析、审批闭环、任务超时/取消、文件下载循环、模板改名。**

---

## 0. 风险总览

| 编号 | 级别 | 标题 | 位置 |
|---|---|---|---|
| W-01 | Critical | 本地 Web 后端无鉴权且默认监听 0.0.0.0，`/api/config` 明文回吐 C2 Token，`/api/action` 变成本地免鉴权代理 | `web_backend.py:24-38,66-70,165-182,210,216` |
| W-02 | High | 本地 API 无 CSRF/Origin/Content-Type 校验，任意网页可用 `text/plain` 简单请求写入恶意 Python 模板（模板投毒→下发即目标 RCE） | `web_backend.py:71-76,146-155`；`App.jsx:1010-1016` |
| W-03 | Medium | Token 落盘为 0644 世界可读，且 `GET /api/config` 同时回吐配置文件绝对路径 | `web_backend.py:66-76` |
| W-04 | Medium | 无 Host 头校验，存在 DNS rebinding / localhost 跨站读取面（与 W-01、W-02 组合放大） | `web_backend.py:197-216` |
| W-05 | Medium | 载荷 Token 在界面明文常驻显示并可被一键复制（含 `/p/token` URL），肩窥/截图/本地历史泄露 | `App.jsx:302,306` |
| W-06 | Medium | `mv`/`cp` 参数解析死分支：通用分支先命中，目标路径被丢弃（按钮/命令实际无效） | `App.jsx:363,370-374` |
| W-07 | Medium | 审批闭环断裂：`action()` 抛 `ApprovalRequiredError`，多处 `status === 'approval_required'` 判断是死代码；控制台不跳转/不刷新审批队列 | `App.jsx:19-31,777-784,1133-1160` |
| W-08 | Medium | 任务等待固定 60s（120×500ms）且不取消：慢回连（slow_interval 可达 30s+）必"超时"，服务端任务残留、状态不同步 | `App.jsx:436-446`；`server_core/task_engine.py` |
| W-09 | Medium | 高危操作一键生效无二次确认：全部放行/全部拒绝、切 all_allow、清空历史、删除模板、覆盖写目标文件 | `App.jsx:861-864,1163-1165` |
| W-10 | Medium | 文件下载 `while(true)` 无上限：服务端重复返回同一 chunk 则无限循环 + 内存增长 | `App.jsx:720-752` |
| W-11 | Low | 插件改名保存不删旧文件（无 rename 语义），产生幽灵插件/重名遮盖 | `App.jsx:1076-1080` |
| W-12 | Low | 正则筛选：每条输出每渲染重编译、无长度/超时上限，灾难性回溯可冻结页面 | `App.jsx:457-512` |
| W-13 | Low | 非 UTF-8 模板文件使 `GET /api/local/templates` 500，连带 Beacon 控制台初始化失败 | `web_backend.py:47-54`；`App.jsx:623-624` |
| W-14 | Low | `download_url` 直接进 `<a href>`，未校验 scheme（`javascript:` 可执行于本地源） | `App.jsx:306` |
| W-15 | Low | 本地历史明文落盘（含 exec/python 原文与 beacon 主机名），权限 0644 | `web_backend.py:114-130` |
| W-16 | Low | Beacon 备注保存失败提示写在被遮挡的列表 Banner 里；备注/设置 dirty 后 5s 轮询永久停止刷新 | `App.jsx:190-201,591-608` |
| W-17 | Low | 会话信息获取失败被吞，403/401 时界面仍显示 `role=human` | `App.jsx:1191` |
| W-18 | Low | 统计口径不同步：监听器数取 `status.listeners`，列表取 `listeners.length` | `App.jsx:196-198` |
| W-19 | Info | 无 CSP / X-Content-Type-Options 等安全响应头；前后端同源，缺纵深 | `web_backend.py:197,216` |
| W-20 | Info | `styles.css` 无 `@import`/外链/`expression()`，样式面未发现注入或外带 | `styles.css` 全文 |

---

## W-01（Critical）本地 Web 后端完全无鉴权 + 默认 0.0.0.0 + Token 明文回吐

**位置**
- `clients/web_backend.py:24-38` `load_config()`：token 直接来自 CLI/`config.json`
- `clients/web_backend.py:66-70` `GET /api/config`：`return {"server": ..., "token": active_token, "config_path": ...}`
- `clients/web_backend.py:165-182` `POST /api/action`：用 `active_token` 转发到服务端，**不校验调用方身份**
- `clients/web_backend.py:210` `--host default="0.0.0.0"`；`:216` `uvicorn.run(..., host=args.host, ...)`
- `clients/web_backend.py:197` 静态站点挂在 `/`

**问题**
1. 本地 8765 端口没有任何认证（无 cookie/session/CSRF/口令），但它是 C2 的**完整控制面代理**：`/api/action` 可调用 `task.create`、`script.run`、`file.write`、`plugin.save`、`server.config.set` 等全部动作。
2. `GET /api/config` 把 Human/AI Token 明文返回给任何能访问该端口的人。
3. 默认监听 `0.0.0.0`，同网段任何人都能直接拿到 Token 并驱动 C2（=`script.run` → 目标主机任意代码执行）。

**复现（只读、无破坏）**
```bash
# 1) 起客户端（默认就是 0.0.0.0）
python3 clients/web_backend.py --config clients/config.json --port 8765
# 2) 任意同网段主机（或在浏览器地址栏）直接读取配置
curl -s http://<客户端IP>:8765/api/config        # 返回 server + token + config_path
# 3) 用泄露的 token 直接驱动控制面（此处仅列只读动作）
curl -s -X POST http://<客户端IP>:8765/api/action \
  -H 'Content-Type: application/json' \
  -d '{"action":"beacon.list","args":{}}'
curl -s -X POST http://<客户端IP>:8765/api/action \
  -H 'Content-Type: application/json' \
  -d '{"action":"server.status","args":{}}'
```
预期：无需任何凭据即返回 JSON 数据；把 `beacon.list` 换成 `task.create`/`script.run` 即为对目标的远程代码执行。

**建议修复**
1. `--host` 默认改 `127.0.0.1`；确需远程访问时强制 HTTPS + 独立面板口令。
2. 增加本地会话：首次启动生成 32B 随机 session secret，登录后发 `HttpOnly; SameSite=Strict` cookie；`/api/*` 全部校验。
3. `GET /api/config` 只返回 `server`（host/port），**永不回吐 token**；token 仅由用户输入并用一次性加密保存在服务端内存/Keychain。
4. `/api/action` 加动作白名单 + 角色绑定（human/ai/ai_approval），拒绝跨角色越权。

---

## W-02（High）本地 API 无 CSRF 防护，模板投毒 → 目标 RCE

**位置**
- `clients/web_backend.py:71-76` `POST /api/config`：`body = await request.json()` 后**原样写入** `config.json`
- `clients/web_backend.py:146-155` `POST /api/local/templates`：`body = await request.json()` → `path.write_text(source)`
- `clients/web_backend.py:114-130` `POST /api/local/history`：同上，可无限写文件
- 消费端：`App.jsx:1010-1016` 模板可"下发 Python 脚本"到任意 Beacon

**问题**
Starlette 的 `Request.json()` 只解析 body，**不校验 Content-Type、不校验 Origin、无 CSRF token**。因此攻击者页面可用「简单请求」绕过预检：
```js
// 恶意页面，用户访问期间静默执行
fetch('http://127.0.0.1:8765/api/local/templates', {
  method: 'POST',
  mode: 'no-cors',
  headers: {'Content-Type': 'text/plain'},   // 不触发 preflight
  body: JSON.stringify({name: 'ui_smoke', source: 'import os\nos.system("id")\n'})
})
```
写入成功后，模板出现在控制台"选择本地模板"下拉里（`App.jsx:1012`），操作者一旦应用并下发，就在所有在线 Beacon 上执行——**从浏览器跨站直达目标 RCE**。同理可对 `POST /api/config` 投毒 `server`，把后续 `/api/action` 引向攻击者服务器，或在下次连接时骗取用户重新输入 token。

**复现（本机无破坏验证）**
```bash
# 模拟浏览器简单请求（不带 application/json，仍会被 request.json() 接受）
curl -s -X POST http://127.0.0.1:8765/api/local/templates \
  -H 'Content-Type: text/plain' \
  --data '{"name":"csrf_probe","source":"print(1)\n"}'
ls -l clients/local_data/templates/csrf_probe.py    # 预期出现文件（验证后手动删除）
```
浏览器侧：任意第三方页面执行上面等价的 `fetch(..., {mode:'no-cors'})` 即可。

**建议修复**
1. 所有写接口强制 `Content-Type: application/json` 且校验 `Origin/Referer` 同源。
2. 引入 CSRF token（双提交 cookie 或 header），写操作必须携带。
3. 模板/配置/历史写接口改成需要会话 cookie 的 POST，并对 `name` 做白名单（当前 `safe_template_name` 已防穿越，但仍允许任意文件覆盖）。
4. 模板落盘后计算哈希，下发前提示"模板被外部修改"。

---

## W-03（Medium）Token 落盘 0644 世界可读 + 泄露绝对路径

`clients/web_backend.py:75` `cfg_path.write_text(...)` 使用默认 umask（通常 022）→ `config.json` 为 `0644`，同机任意用户可读明文 `token`；`GET /api/config` 还回吐 `config_path`（`web_backend.py:69`），便于定位。
**复现**：`curl -s localhost:8765/api/config; ls -l clients/config.json`
**修复**：写前 `os.chmod(path, 0o600)`；token 不落盘（用 OS keyring / 系统凭据管理器）；`config_path` 不返回。

---

## W-04（Medium）无 Host 头校验，DNS rebinding 可读本地 API

`web_backend.py:197` 直接 `app.mount("/", StaticFiles(...))`，全站无 `TrustedHostMiddleware`，也无 `Host` 白名单。攻击者把 `evil.com` 解析到 `127.0.0.1` 后，同源策略被 rebinding 绕过，可**读取** `/api/config`（拿 token）并调用 `/api/action`。
**修复**：`TrustedHostMiddleware(allowed_hosts=["127.0.0.1","localhost"])`；校验 `Origin`；对 `/api/*` 要求自定义 header（如 `X-Requested-With`）。

---

## W-05（Medium）载荷 Token 明文常驻 + 可复制 URL

`App.jsx:302`：`载荷 Token：{generated ? generated.token : '—'}` 明文常驻；`App.jsx:306` 与 `CopyButton`（`:56-58`）把含 `/p/token/<token>` 的 curl/下载器命令原样显示并可复制。
风险：肩窥、截图外发、录屏、终端历史/代理日志留存 token；token 即载荷下载凭据。
**修复**：token 只显示一次并提供"复制"，之后打码（`abc***xyz`）；复制内容默认脱敏；提供"吊销 token"。

---

## W-06（Medium）`mv`/`cp` 解析死分支：目标路径被丢弃（功能不闭环）

`App.jsx:363` 通用分支已包含 `'mv','cp'` 并 `return`；`:370` 的 `if (cmd === 'mv' || cmd === 'cp')` 永不执行。
结果：`mv /a /b` 只发送 `args.path="/a"`，`target` 丢失（`args.target` undefined）→ 移动/复制要么失败要么行为不可预期。同分支还会把 `rm -r /x` 解析成 `path="-r"`、`tail -f log` 解析成 `path="-f"`（`App.jsx:363-378`）。
**复现**：在 Beacon 控制台输入 `mv /tmp/a /tmp/b`，观察下发 JSON（可用 DevTools Network 抓 `/api/action`）只有 `{"path":"/tmp/a"}`。
**修复**：把 `mv/cp` 从通用列表移除，提前到专门分支；通用分支先剥离 `-*` 选项再取 path；`rm -r` 用独立 flags 字段。

---

## W-07（Medium）审批闭环断裂（死代码 + 无反馈）

- `App.jsx:19-31`：`action()` 在 `status==='approval_required'` 时**抛异常**。
- `App.jsx:777-784`（proxy/socks）与 `:1133-1160`（Approvals 的 resolve/setMode）又判断 `data?.status === 'approval_required'` —— 永远不可达。
- 控制台 `runTaskAndWait` 被拒后只把 `err.message` 写进输出（`App.jsx:786-800`），既不切换"审批"页、也不刷新审批队列；用户只看到"需要审批：<id>"，无操作入口。

**复现**：把服务端切到 `per_action`（`Approvals` 页点"逐条审批"），在控制台执行 `exec id`：输出出现"需要审批"文本，但审批页列表需手动点刷新，且没有跳转提示。
**修复**：`action()` 不抛异常而返回结构化 `{status:'approval_required', approval}`；全局统一处理器：Toast + 自动刷新审批队列 + 提供"去审批"按钮；`ApprovalRequiredError` 保留但必须被 catch 后驱动 UI。

---

## W-08（Medium）等待固定 60s、不可取消，任务状态不同步

`App.jsx:436-446` `waitTask()`：`for (i<120)` × `500ms` = **固定 60s**，每 500ms 调一次 `task.show`；超时返回 `timedOut`。
- 载荷的 `slow_interval` 在界面可配到 30s+（`App.jsx:300`），Beacon 空闲期根本来不及领取 → 必然"等待超时"。
- 超时后前端不再跟踪，服务端任务仍在 `queued`（`task_engine.py` 状态机），无 `task.cancel` 调用 → 任务堆积、UI 与账本不同步。
- 高频轮询（2 req/s/任务）在并发任务下放大负载。

**复现**：设置 `slow_interval=60`，生成载荷并上线（或直接把 Beacon 置忙），执行 `ps`：约 60s 后提示"等待超时"，服务端 `task.list` 仍能看到 queued 任务。
**修复**：按 `max(slow_interval*2, 90s)` 动态计算超时；轮询间隔指数退避（1s→2s→5s）；超时提供"取消任务"（调用 `task.cancel`）；或改用服务端 SSE/WebSocket 推送。

---

## W-09（Medium）高危操作一键生效，无二次确认

- `App.jsx:1165`：`全部放行` / `全部拒绝` 一键批量处理审批（无确认、无数量提示）。
- `App.jsx:1163`：`全部放行` 模式切换一键把审批关掉（安全控制降级）。
- `App.jsx:861-864` + `:1023`：`清空` 本地历史 → `DELETE /api/local/history` 删除所有记录（不可恢复、无确认）。
- `App.jsx:1012` 删除模板；`:1038` 保存到目标（覆盖写 Beacon 文件）；`:1046` 执行快速操作。
**修复**：统一 `confirm()`/二次弹窗；批量操作显示"将放行 N 条（含 script.run）"；删除类操作要求输入确认词；模式切换记录审计事件。

---

## W-10（Medium）文件下载 `while(true)` 无上限

`App.jsx:720-752`：循环调用 `file.download`，仅当 `data.eof || !data.length` 退出；`offset += Number(data.length || 0)` 若服务端返回 `length>0` 但 `eof` 恒 false（或 offset 不前进），则**无限循环**并持续 `chunks.push` → 内存耗尽/浏览器卡死。
**修复**：限制最大迭代（`ceil(fileSize/chunk)+2`）与最大总字节；每轮校验 `offset` 必须严格递增；允许用户中止（AbortController）。

---

## W-11（Low）插件改名不删旧文件

`App.jsx:1076-1080` 保存时用当前 `name` 与 `source` 调 `plugin.save`；编辑器里改了名字也只新增/覆盖新名字文件，旧文件残留 → 目录重复、热重载后出现"幽灵插件"，甚至同名覆盖他人插件。
**修复**：保存时带 `original_name`，服务端执行 rename（先写新、再删旧）；或在 UI 明确"另存为"。

---

## W-12（Low）正则筛选性能/ReDoS

`App.jsx:457-512`：`apply()` 只用 `new RegExp` 做语法校验；`filterText()` 在**每次渲染、每条输出**重新编译并对整段文本逐行 `test`。用户可输入 `(a+)+$` 之类灾难性回溯表达式，配合大文件/大输出冻结页面。`LineFilter` 对非法正则有提示，但 `filterText` 的 `catch` 静默返回原文（`:509-511`），行为不一致。
**修复**：编译一次缓存；限制 pattern 长度与文本长度；用 Web Worker + 超时；非法/超时给出可见提示。

---

## W-13（Low）模板目录存在非 UTF-8 文件时列表 500

`web_backend.py:47-54` `template_record()` 直接 `path.read_text(encoding="utf-8")`；`GET /api/local/templates` 遍历 `*.py` 无 try/except（`:140-144`）。一个 GBK/二进制 `.py` 即让接口 500；前端 `loadTemplates()` 在 BeaconConsole 初始化 `useEffect` 里与 `loadHistory()` 同批（`App.jsx:623-624`），失败会导致控制台首屏异常。
**复现**：`printf '\xff\xfe' > clients/local_data/templates/bad.py; curl -s localhost:8765/api/local/templates`
**修复**：`read_text(errors="replace")` 或捕获异常返回占位记录；前端对失败做兜底并提示。

---

## W-14（Low）`download_url` 未校验 scheme

`App.jsx:306`：`<a className="link" href={generated.download_url}>payload.py</a>`。React 不会拦截 `javascript:` 协议；若服务端/中间人被篡改返回 `javascript:alert(document.domain)`，点击即在**本地客户端源**执行（该源可读 `/api/config` token）。
**修复**：仅允许相对路径或 `http(s)://`；用 `new URL(url, location.origin)` 校验 `protocol ∈ {http:,https:}`；必要时加 `rel="noopener noreferrer"`。

---

## W-15（Low）本地历史明文落盘 0644

`web_backend.py:114-130`：记录 `command`（含 `exec ...`、`python ...` 完整原文）、`beacon_id`、`beacon_host` 到 `clients/local_data/history/*.json`，默认 0644；命令里常带口令/路径等敏感信息。
**修复**：目录 0700、文件 0600；对命中 `password/token/key` 的命令做脱敏；提供"不记录"开关。

---

## W-16（Low）备注保存失败无可见反馈 + 轮询被 dirty 永久冻结

- `App.jsx:190-201`：`saveNote` 失败把错误写进 `fleetMsg`（页面 Banner），但备注弹窗仍覆盖在上层 → 用户看不到失败。
- `App.jsx:591-608`：`loadBeaconInfo` 只在 `!noteDirty` / `!settingsDirty` 时覆盖本地值；一旦用户改过又未保存，5s 轮询**永久**不再更新备注/设置（直到保存），多标签页协作时表现为"状态不同步"。
**修复**：错误显示在弹窗内部；dirty 时保留草稿但单独展示"服务端值已变更"提示；保存失败保留草稿并允许重试。

---

## W-17（Low）/ W-18（Low）会话与统计口径

- `App.jsx:1191`：`fetch('/api/session').then(setSession).catch(()=>{})`，401/502 时 `session` 为错误体或空，`:1211` 仍渲染 `ROLE human`，footer 同理（`:1211`）。
- `App.jsx:196-198`：监听器数用 `status?.listeners`，Beacon 页用 `listeners.length`；数据源不同步时两个数字会互相矛盾。
**修复**：会话请求失败显式显示"未连接/无权限"；统计统一从 `listeners` 数组派生。

---

## W-19（Info）缺少安全响应头 / CSP

`web_backend.py:197,216` 未设置 `Content-Security-Policy`、`X-Content-Type-Options: nosniff`、`Referrer-Policy`、`X-Frame-Options`。当前前端无内联事件处理器，但加 CSP 能显著降低 W-02/W-14 的利用面（例如禁止 `unsafe-inline`、限制 `connect-src`）。
**修复**：加中间件统一注入安全头；`frame-ancestors 'none'`。

---

## W-20（Info）`styles.css` 未发现注入/外带面

全量检查：无 `@import`、无 `url(http...)` 外链、无 `expression()`/`behavior:`；长行仅为压缩后的样式规则。样式表本身不构成安全问题（仅 `backdrop-filter`/`mask-image` 等纯视觉效果）。前端全量使用 JSX 文本插值，未发现 `dangerouslySetInnerHTML`/`innerHTML`/`eval`/`new Function`，**无存储型/DOM 型 XSS sink**；唯一可疑点是 W-14 的 `href`。

---

## 附：已核对但判定为"非问题"的点

1. `safe_template_name()`（`web_backend.py:40-45`）剥离 `[^A-Za-z0-9_.-]` 并 `strip("._-")`，`../` 穿越不成立；空名回退 `template_<ts>`。
2. `file.upload_chunk` 返回 `{"task":...}`，前端 `result.task.id`（`App.jsx:713`）**与实现一致**；`file.list/read/write/download` 返回任务记录本身，前端 `taskRecord.id` 也一致。
3. `normalizeTaskData()` 兼容 `result.data` 与 `data`，后端 `task_engine` 成功结果符合该结构。
4. React 对所有 `{b.hostname}`、`{b.note}`、`{a.action}`、`{a.args}` 均转义，Beacon 名称/备注/审批参数注入 HTML 不成立。
5. `plugins` 平台解析：`beacon.platform === 'windows' ? 'w' : 'l'`（`App.jsx:547`）对未知平台一律按 Linux，属**降级策略**而非漏洞；但若后端新增平台（如 `darwin`），插件会错配，建议改为显式映射表 + 未知平台提示。
6. 审批动作列表渲染使用 `JSON.stringify(a.args).slice(0,90)`，仅显示不执行，无注入面。

---

## 建议修复优先级

1. **P0（立即）**：W-01 绑定 127.0.0.1 + 本地会话鉴权 + 不回吐 token；W-02 强制 JSON/Origin/CSRF。
2. **P1（本迭代）**：W-03 权限 0600；W-04 TrustedHost；W-05 token 打码；W-06 mv/cp 解析；W-07 审批闭环；W-08 超时/取消。
3. **P2（下一迭代）**：W-09 二次确认；W-10 下载上限；W-11 插件改名；W-12 正则防护；W-13~W-18 体验与健壮性。
4. **P3**：W-19 安全响应头/CSP。

## 审计证据（commandId）

| 用途 | commandId |
|---|---|
| 目录/文件规模与版本 | c92、c93、c100 |
| `web_backend.py` 全文（两段） | c101、c104 |
| 前端高危 sink 快速定位 | c105 |
| `App.jsx` 分段通读（1-2/3-4/5/末段） | c108、c109、c112、c113、c116、c117 |
| 按钮/属性、mv-cp 死分支、suggestion | c120 |
| `styles.css` 外链/表达式检查 | c121 |
| `file.*` 返回结构核对（runtime.py） | c124、c127 |
| 审批/任务状态机核对 | c125 |
| 精确行号提取 | c129 |

> 本报告为只读审计结论，未执行任何写操作、未改动被测代码、未终止进程、未清理数据。W-02 的复现命令会写入一个探针模板文件，如已执行请手动删除 `clients/local_data/templates/csrf_probe.py`。
