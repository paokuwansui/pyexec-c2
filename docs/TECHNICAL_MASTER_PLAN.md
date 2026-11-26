# PyExec2 技术实现总纲 v1.0

> 文档性质：技术实现总纲。  
> 输入依据：
> - `docs/IMPLANT_TOTAL_THOUGHT.md`
> - `docs/SERVER_TOTAL_THOUGHT.md`
> - `docs/CLIENT_TOTAL_THOUGHT.md`
> - `docs/PLUGIN_TOTAL_THOUGHT.md`
>
> 本文件回答：
> - 采用什么技术；
> - 为什么这样选；
> - 各模块怎么开发；
> - 开发过程如何推进；
> - 如何验证；
> - 如何进行验收；
> - 哪些思想问题必须先由你拍板。
>
> 当前不写实现代码。思想文档优先于本文；本文与思想文档冲突时，以思想文档为准，冲突项进入 `docs/DECISION_REGISTER.md`。

---

## 0. 技术目标

把四份思想文档落成一个可运行、可验证、可维护的系统：

1. 服务端文件化存储，不依赖真实数据库；
2. 服务端运行期不提供本地控制输入；
3. 所有控制动作从客户端 TCP 控制面发起；
4. 植入物通过拉取代码、内存 `exec`、并行执行、结果回传工作；
5. 所有业务能力插件化；
6. 平台差异用 `l` / `w` 命令拆分；
7. 支持多协议插件，起始协议由监听器和载荷决定；
8. 支持协议升级、回退、随机选择；
9. 支持文件浏览、编辑、上传、下载、代理、Python 文件下发；
10. Web 界面向 Cobalt Strike 工作流看齐，但不复制其资产；
11. AI 使用一次性客户端 `client_ai.py`；
12. 结果不截断，人机共用能力与审计。

---

## 1. 技术栈总览

### 1.1 推荐技术栈

| 层 | 推荐技术 | 用途 |
|---|---|---|
| 服务端语言 | Python 3.12+ | 与现有代码一致，插件语言统一 |
| 服务端异步 | `asyncio` | TCP Gateway、任务调度、事件流 |
| 服务端 Web/API | FastAPI + Uvicorn | 控制 API、静态资源、WebSocket |
| 服务端校验 | Pydantic v2 | 动作参数、插件 manifest、消息 schema |
| 植入物运行时 | Python 3.8+（待确认） | 目标端兼容性，内存 exec |
| 植入物并发 | `threading` + 任务注册表 | 插件并行、无默认超时 |
| 文件数据库 | `pathlib` + JSON/JSONL + 二进制文件 | 替代 SQLite |
| 原子写 | `tempfile` + `os.replace` + `fsync` | 崩溃一致性 |
| 文件锁 | `fcntl` / `msvcrt` 封装 | 单写者与跨进程保护 |
| 加密封装 | 待定（见决策 D-03） | 应用层加密和完整性 |
| 传输插件 | Python `socket` / `ssl` / `asyncio` | TCP/UDP/HTTP/HTTPS/DNS/ICMP |
| Web 前端 | React 19 + Vite 7 | 现有技术栈延续 |
| Web 语言 | TypeScript（建议） | 复杂状态与协议类型安全 |
| Web 样式 | 原生 CSS / CSS Modules | 控制体积，保持定制科技感 |
| 代码编辑器 | CodeMirror 6（待确认） | 文件编辑与语法高亮 |
| AI 客户端 | Python 单文件 `client_ai.py` | 一次性调用、JSON 输出 |
| 测试 | pytest + pytest-asyncio + httpx | 服务端与协议测试 |
| E2E | Playwright | Web 工作台与授权流程验证 |
| 前端测试 | Vitest + Testing Library | 组件和交互测试 |
| 代码质量 | Ruff + 可选 mypy | Python 静态检查 |
| 构建 | `pyproject.toml` + npm | 服务端与 Web 构建 |

### 1.2 明确不采用的技术

默认不采用：

- SQLite / PostgreSQL / MySQL 作为主存储；
- Redis / Kafka / RabbitMQ；
- Electron（除非以后需要原生 TCP 桌面壳）；
- 前端大型组件库；
- 目标端 pip 安装依赖；
- 目标端 Shell 调用；
- 目标端临时脚本文件；
- 目标端第三方数据库。

### 1.3 技术选型原则

1. 能用标准库就不用第三方；
2. 能用一个进程解决就不引入额外服务；
3. 能把复杂逻辑留在服务端，就不放到植入物；
4. 能插件化就不写死；
5. 能在测试中模拟的，就不依赖外部环境；
6. 每增加一个依赖，都必须说明必要性、体积、安装方式和失败回退。

---

## 2. 总体技术架构

```text
┌─────────────────────────────────────────────────────────────┐
│ Web Client (React/TS)              AI Client (client_ai.py) │
│         │ WebSocket/HTTP over TCP       │ TCP/HTTP over TCP │
└─────────┼───────────────────────────────┼───────────────────┘
          ▼                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Server Control Plane                                        │
│                                                             │
│ Client Gateway → Action Registry → Policy → Task Engine      │
│       │                 │             │                     │
│       ▼                 ▼             ▼                     │
│ Event Bus         Plugin Registry   File Store              │
│       │                 │             │                     │
│       └──────────┬──────┴─────────────┘                     │
│                  ▼                                          │
│ Transport Gateway Manager                                   │
│  ├── TCP Gateway                                            │
│  ├── UDP Gateway                                            │
│  ├── HTTP Gateway                                           │
│  ├── HTTPS Gateway                                          │
│  ├── DNS Gateway                                            │
│  └── ICMP Gateway                                           │
└──────────────────┬──────────────────────────────────────────┘
                   │ encrypted protocol frames
┌──────────────────▼──────────────────────────────────────────┐
│ Implant Runtime                                             │
│                                                             │
│ Bootstrap → Transport Kernel → Envelope → Task Fetch        │
│          → Task Registry → Parallel Executor → Result Queue │
│          → Runtime Globals / Task Locals → Plugin Exec      │
└─────────────────────────────────────────────────────────────┘
```

### 2.1 两条独立网络平面

- 客户端控制面：Web UI / AI ↔ Server。
- 植入物数据面：Implant ↔ Server Transport Gateway。

必须保持：

- 独立密钥域；
- 独立认证；
- 独立审计；
- 独立端口职责；
- 独立流量策略。

### 2.2 统一动作核心

服务端所有动作都进入同一个 `ActionRegistry`：

```text
action request
  → 参数 schema 校验
  → 身份与权限
  → 风险与审批
  → 路由到核心处理器或服务端插件
  → 写审计
  → 返回结构化响应
```

Web、AI、CLI 和自动化都只能走这个动作核心。

---

## 3. 代码仓库结构

建议重建为清晰的单体仓库：

```text
pyexec2/
├── pyproject.toml
├── README.md
├── server_core/
│   ├── bootstrap.py
│   ├── config.py
│   ├── runtime.py
│   ├── action_registry.py
│   ├── client_gateway.py
│   ├── auth.py
│   ├── policy.py
│   ├── audit.py
│   ├── event_bus.py
│   ├── file_store.py
│   ├── task_engine.py
│   ├── beacon_registry.py
│   ├── listener_manager.py
│   ├── payload_builder.py
│   └── plugin_loader.py
│
├── server_plugins/
│   ├── proxy_gateway/
│   ├── artifact_service/
│   ├── result_processor/
│   ├── regex_filter_presets/
│   ├── ai_tools/
│   └── maintenance/
│
├── transport_plugins/
│   ├── udp.py
│   ├── tcp.py
│   ├── http.py
│   ├── https.py
│   ├── dns.py
│   └── icmp.py
│
├── implant_plugins/
│   ├── common/
│   ├── linux/
│   └── windows/
│
├── clients/
│   ├── web/
│   │   ├── package.json
│   │   ├── vite.config.ts
│   │   └── src/
│   └── ai/
│       └── client_ai.py
│
├── data/
├── runtime/
├── logs/
├── config/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
└── scripts/
```

### 3.1 旧代码处理

旧项目中的：

- FastAPI 入口；
- React/Vite UI；
- 认证与授权码页面；
- 部分前端组件；
- 现有载荷生成与演示逻辑；

可以作为参考和素材来源。

旧项目中的：

- SQLAlchemy 模型；
- SQLite 持久化；
- 固定业务命令注册；
- 双阶段载荷残留；
- 全局命名空间直接 exec；
- 单协议 WebSocket 主通道；

不直接沿用，按四份思想文档重建。

---

## 4. 服务端技术实现方案

### 4.1 进程模型

推荐：

```text
一个服务端主进程
  ├── asyncio 主事件循环
  ├── TCP/HTTP/WebSocket 客户端入口
  ├── 各协议 Gateway 异步任务
  ├── 任务调度器
  ├── 文件存储异步包装
  └── 插件执行线程池
```

理由：

- 单进程部署简单；
- asyncio 适合大量网络连接；
- 文件 IO 和同步插件可交给线程池；
- 不引入额外的消息队列和数据库服务。

### 4.2 服务端启动

```text
python -m server_core.bootstrap --port 8080
```

启动过程：

1. 解析启动参数；
2. 锚定启动目录；
3. 创建 `data/`、`runtime/`、`logs/`、`config/`；
4. 加载配置；
5. 验证插件签名与 hash；
6. 扫描并恢复文件数据库；
7. 重建内存索引；
8. 恢复监听器配置；
9. 启动客户端控制面；
10. 启动已启用的协议监听器；
11. 进入无本地输入的等待状态。

启动后不提供命令控制台。

### 4.3 客户端控制面

待决策 D-01。

推荐方案：

- 服务端使用 FastAPI + Uvicorn 暴露 HTTP/WebSocket；
- Web 浏览器使用 WebSocket over TCP 进行控制与事件；
- AI `client_ai.py` 使用一次性 HTTP JSON 请求，底层同样是 TCP；
- 两者统一使用 `ActionRequest` / `ActionResponse`；
- 不允许 Web 或 AI 直接读取服务端文件系统。

备选方案：

- 服务端额外开一个原生 framed TCP 控制端口；
- AI 客户端使用原生 TCP；
- Web 继续使用 WebSocket。

哪种方案由你拍板。

### 4.4 Action Registry

服务端使用统一动作注册表。

动作定义包含：

```text
name
description
input_schema
output_schema
handler
permission
risk
requires_approval
plugin_source
audit_fields
```

首批动作：

```text
listener.create
listener.list
listener.show
listener.stop
payload.generate
payload.list
payload.show
payload.delete
beacon.list
beacon.show
task.create
task.list
task.show
task.cancel
result.get
plugin.list
plugin.show
plugin.reload
approval.list
approval.approve
approval.reject
audit.tail
server.status
```

动作处理器可以来自：

- 核心；
- 服务端插件；
- 协议插件；
- AI 工具插件。

### 4.5 任务引擎

任务来自客户端动作，进入文件队列。

流程：

```text
task.create
  → 参数与权限校验
  → 风险与审批
  → 写 data/tasks/<task_id>/
  → 写 data/queues/<beacon_id>/pending.jsonl
  → 事件 task.created
  → 等待植入物拉取
  → 下发记录
  → 结果回收
  → 更新任务状态
  → 事件 task.completed/failed
```

### 4.6 文件数据库实现

使用 `FileStore` 统一封装：

- `ensure_dirs()`
- `read_json()`
- `write_json_atomic()`
- `append_jsonl()`
- `read_jsonl_tail()`
- `write_binary_atomic()`
- `copy_artifact()`
- `lock()`
- `recover_temp_files()`
- `scan()`
- `rebuild_indexes()`

原子写：

```text
write to .tmp
→ flush
→ fsync
→ os.replace
→ fsync parent directory
```

索引：

- 内存索引只用于加速；
- 启动时从文件重建；
- 索引损坏不影响数据；
- 所有索引文件都标记为可重建。

### 4.7 服务端插件运行时

服务端插件使用：

```text
compile(source)
→ exec(compiled, plugin_globals, plugin_locals)
→ 取得 PLUGIN 元数据和入口函数
→ 注册到 ActionRegistry / ResultProcessor / ProxyGateway 等
```

服务端全局运行时提供：

- `config`
- `workdir`
- `store`
- `events`
- `actions`
- `tasks`
- `beacons`
- `listeners`
- `plugins`
- `policy`
- `audit`
- `ai_tools`

插件可通过显式 API 修改运行时。

### 4.7.1 代码下发出口与注释剥离

新增模块：

```text
server_core/code_sanitizer.py
server_core/code_delivery.py
```

`code_sanitizer.py`：

- 使用 `tokenize.generate_tokens` 删除 COMMENT token；
- 保留 NEWLINE / NL / INDENT / DEDENT；
- 保护字符串、f-string、多行字符串中的 `#`；
- 返回 stripped source 和统计；
- 使用 `compile` 做最终语法校验；
- 解析失败直接拒绝下发。

`code_delivery.py`：

- 所有服务端到植入物的代码唯一出口；
- 输入来源：
  - implant plugin；
  - raw python script；
  - protocol upgrade script；
  - payload runtime code；
  - control script；
- 流程：

```text
source
→ strip_comments()
→ compile()
→ hash original/stripped
→ encrypt envelope
→ send
```

- 不允许任何其他模块直接构造下发代码 payload。
- 审计记录 original_hash、stripped_hash、source_type、task_id。

测试：
- 字符串中的 `#` 不删除；
- 三引号中的 `#` 不删除；
- 注释删除后仍可编译；
- 语法错误被拒绝；
- 上传脚本和插件走同一出口。

### 4.8 服务端插件安全

- manifest 校验；
- 签名校验；
- 能力声明；
- 禁止 Shell；
- 禁止未授权文件路径；
- 高风险调用审批；
- 加载失败隔离；
- 版本不可变；
- 吊销机制。

---

## 5. 植入物技术实现方案

### 5.1 目标端运行模型

推荐：

```text
主线程：连接 / 拉取 / 回传 / 调度
任务线程池：并行执行插件
共享：runtime globals
隔离：每任务 local dict
队列：task registry / result queue
```

### 5.2 单阶段载荷

生成物是一段 Python 源码。

投递方式：

- `echo "...python..." | python`
- `curl "...url..." | python`
- 短加载器下载并执行

执行方式：

- 读取源码；
- 解密、校验；
- `exec` 在内存中；
- 不生成 `.py`；
- 不生成 `__pycache__`；
- 不调用 Shell。

### 5.3 全局运行时与局部命名空间

技术形态：

```python
exec(plugin_source, runtime_globals, task_locals)
```

- `runtime_globals` 是共享字典，保存协议对象、密钥、任务表、结果队列、回连参数等；
- `task_locals` 是每个任务独立字典；
- 普通赋值写入 `task_locals`；
- 插件使用 `global` 或运行时 API 才能修改共享字典；
- 运行时对象可读、可调用、可按权限修改。

### 5.4 任务执行

每个任务：

1. 创建 task_id；
2. 校验插件平台；
3. 创建 task_locals；
4. 注入 runtime window；
5. 捕获 stdout/stderr；
6. 执行；
7. 记录结果；
8. 更新 task registry；
9. 写入 result queue；
10. 触发结果聚合窗口。

### 5.5 并行与取消

- 任务使用线程池并行；
- 默认不设执行超时；
- 任务注册表记录运行状态；
- 控制代码可以查看任务；
- 控制代码可以设置取消标记；
- 插件需要周期性检查取消标记；
- 对无法协作取消的阻塞任务，设计上保留“强制隔离/终止”扩展点，但默认不承诺安全硬杀。

### 5.6 回连调度器

状态：

- `last_dispatch_at`
- `dispatch_window`
- `dispatch_count`
- `last_result_at`
- `result_finish_delay_ms`（默认 5000）
- `fast_interval_ms`（默认 5000）
- `slow_interval_ms`（默认 600000）
- `jitter_ratio`
- `next_connect_at`

行为：

- 首个结果完成启动 5 秒聚合窗口；
- 窗口内新结果完成则重置窗口；
- 窗口安静到期后回连；
- 有运行中任务时按默认回连周期继续回连；
- 任务下发次数增加时缩短间隔；
- 一段时间无任务下发时延长间隔；
- 实际等待加随机抖动。

### 5.7 协议插件

统一接口思想：

```text
start(config)
poll()
send(frame)
close()
health()
```

具体协议：

- UDP；
- TCP；
- HTTP；
- HTTPS；
- DNS；
- ICMP。

协议插件只负责传输，不负责业务。

### 5.8 协议升级

- 服务端下发 `protocol.upgrade` 任务；
- 植入物加载新协议插件；
- 新协议探测连接；
- 验证任务拉取和结果上传；
- 成功后更新全局协议策略；
- 失败回滚旧协议；
- 旧协议保留为备用或按策略关闭。

---

## 6. 通信协议技术方案

### 6.1 统一消息信封

建议字段：

```text
version
message_type
session_id
request_id
task_id
seq
nonce
key_id
compression
payload_len
payload_ciphertext
tag
padding
```

### 6.2 消息类型

- hello
- auth
- register
- heartbeat
- task_fetch
- task_batch
- result_upload
- result_ack
- control
- protocol_upgrade
- event
- error

### 6.3 分帧

- TCP：长度前缀 + envelope；
- UDP：消息 ID + 分片头 + envelope；
- HTTP/HTTPS：HTTP body 携带 envelope，支持批量；
- DNS：标签编码 + 分片序号；
- ICMP：Echo 载荷分片。

### 6.4 加密与压缩

待决策 D-03。

推荐方向：

- 服务端可用 `cryptography`；
- 植入物侧允许携带纯 Python 加密实现；
- 使用 AEAD；
- 压缩使用 `zlib`；
- 所有传输统一应用层加密；
- 协议外观单独处理。

### 6.5 重放保护

- 单调序号；
- 会话 nonce；
- request_id 去重；
- 结果 chunk 去重；
- 未确认结果重传。

---

## 7. 文件传输技术方案

### 7.1 上传

```text
Web 客户端选择文件
→ 服务端接收 artifact
→ 计算 hash
→ 任务拆分为若干 chunk
→ 植入物 fs.upload 插件接收
→ 写目标路径
→ 校验 hash
→ 返回结果
```

### 7.2 下载

```text
植入物 fs.download 读取目标文件
→ chunk 化
→ 服务端 artifact 拼装
→ 客户端下载
```

### 7.3 文件编辑

```text
Web 文件浏览器
→ 打开文件
→ CodeMirror/编辑器
→ 保存
→ fs.write 任务
→ 原子写回
→ 返回新 hash
```

保存前校验：

- 文件 hash；
- 文件 mtime；
- 编码；
- 冲突提示。

### 7.4 大文件

- 分块大小可配置；
- 支持断点续传；
- hash 校验；
- 不把整个大文件读入内存；
- 服务端 artifact 作为文件数据库对象。

---

## 8. Web 客户端技术方案

### 8.1 技术结构

```text
clients/web/
  src/
    app/
    connection/
    actions/
    components/
    pages/
      listeners/
      payloads/
      beacons/
      beacon-console/
      tasks/
      plugins/
      approvals/
      audit/
      settings/
    console/
    history/
    editor/
    filters/
    styles/
```

### 8.2 状态管理

建议：

- 使用 React 原生 state + context；
- 复杂事件流使用 reducer；
- 不引入 Redux 等重状态库；
- 服务端是权威状态；
- 前端只缓存视图状态和本地命令历史。

### 8.3 连接层

- WebSocket 长连接；
- 自动重连；
- 消息序号；
- 请求超时；
- 事件订阅；
- 错误和断线可视化。

### 8.4 命令输入

- 动作/插件补全；
- 参数提示；
- Tab 补全；
- ↑/↓ 历史；
- 独立历史面板；
- 搜索、过滤、重放。

### 8.5 正则筛选

- 当前输出筛选；
- 下一条结果筛选；
- 持续筛选；
- 保留原始结果；
- 捕获组和高亮；
- 过滤只影响视图。

### 8.6 文件编辑器

- CodeMirror 6（待确认）；
- 文本文件；
- 二进制文件只读/下载；
- 保存冲突检测；
- 完整内容。

### 8.7 不做图表

- 不做仪表盘；
- 不做趋势图；
- 以工作台、列表、终端、文件、结果为核心。

---

## 9. AI 客户端技术方案

### 9.1 `client_ai.py`

- 单文件；
- 无交互；
- 一次调用；
- JSON 输出；
- 认证令牌从环境变量/安全文件读取；
- 支持 `--action` 与 `--request`；
- 返回 request_id、status、data、error。

### 9.2 连接方式

待决策 D-01。

候选：

1. HTTP JSON over TCP（推荐，stdlib 可直接实现）；
2. WebSocket over TCP（与 Web 同协议）；
3. 原生 framed TCP（需要独立端口或协议复用）。

### 9.3 AI 的任务模型

- AI 通过服务端动作目录操作；
- 高风险动作返回 `approval_required`；
- AI 不能自审批；
- 长任务返回 `task_id`，AI 可轮询；
- 一次性调用默认不等待长任务完成。

---

## 10. 开发过程

### 10.1 总体开发原则

1. 先做核心骨架，不做页面堆叠；
2. 先做文件数据库，不做 SQLite 临时方案；
3. 先做协议抽象，不先写死 UDP；
4. 先做插件加载与执行，再写业务插件；
5. 先做无 Shell/无盘审计，再扩展功能；
6. 每个阶段都要有可执行验收点；
7. 不用“后面再补测试”的方式开发。

### 10.2 阶段划分

#### Phase 0：决策冻结

产出：

- 技术总纲确认；
- `DECISION_REGISTER.md` 全部拍板；
- 仓库结构确认；
- Python 版本与依赖策略确认。

验收：

- 所有阻塞项有明确选择；
- 无“先做再说”的关键安全决策。

#### Phase 1：仓库与基础骨架

任务：

- 初始化项目；
- 建立目录结构；
- 配置 Ruff/pytest/TypeScript/Vite；
- 建立最小启动入口；
- 建立测试基线。

验收：

- 空服务端可启动；
- 空 Web 可构建；
- 测试命令可运行。

#### Phase 2：文件数据库

任务：

- `FileStore`；
- 原子写；
- 目录锁；
- 事件 JSONL；
- 任务/Beacon/监听器/结果目录；
- 启动恢复和索引重建。

验收：

- 断电模拟后数据可恢复；
- 并发写不产生半文件；
- 索引删除后可重建。

#### Phase 3：服务端动作核心

任务：

- ActionRegistry；
- 认证与会话；
- 权限与审批；
- 审计；
- 客户端控制接口；
- 服务端状态查询。

验收：

- AI 客户端和 Web 客户端都能调用同一动作；
- 服务端没有本地控制输入；
- 所有动作有审计。

#### Phase 4：插件运行时

任务：

- 插件 manifest；
- 签名与 hash；
- 平台校验；
- 全局运行时；
- 局部命名空间；
- 服务端插件加载；
- 植入物插件加载。

验收：

- `lps` 不能下发到 Windows；
- 插件写全局必须在审计中出现；
- 插件异常不拖垮运行时。

#### Phase 5：植入物运行时

任务：

- 单阶段载荷；
- 拉取/执行/回传；
- 全局运行时与任务局部变量；
- 并行任务；
- 任务注册表；
- 结果聚合窗口；
- 自适应回连；
- 控制代码查看/取消任务。

验收：

- 多任务并行；
- 5 秒窗口重置；
- 下发次数影响回连间隔；
- 结果未确认重传。

#### Phase 6：传输插件

任务：

- UDP；
- TCP；
- HTTP；
- HTTPS；
- DNS；
- ICMP；
- 统一信封；
- 路由选择；
- fallback/random/weighted；
- 协议升级。

验收：

- 同一任务语义跨协议；
- 协议切换 Beacon ID 不变；
- 升级失败回滚；
- 随机策略可复现测试。

#### Phase 7：Web 工作台

任务：

- 登录；
- 监听器；
- 载荷；
- Beacon；
- 任务；
- 结果；
- 插件；
- 审批；
- 审计；
- 命令补全；
- 历史；
- 正则筛选；
- 文件浏览/编辑；
- 上传/下载。

验收：

- Playwright 端到端流程；
- 页面无控制台错误；
- 结果不截断；
- 正则过滤只影响视图。

#### Phase 8：AI 客户端

任务：

- `client_ai.py`；
- 动作调用；
- JSON 输出；
- 错误码；
- 审批阻塞；
- token 安全传入。

验收：

- AI 一次调用可完成 `beacon.list`；
- 高风险动作返回 `approval_required`；
- AI 无自审批路径。

#### Phase 9：代理与文件传输增强

任务：

- SOCKS5；
- 端口转发；
- 上传/下载；
- 断点续传；
- artifact；
- 文件编辑冲突处理。

验收：

- 代理会话可建立和关闭；
- 上传/下载 hash 一致；
- 文件编辑冲突可检测。

#### Phase 10：硬化与验收

任务：

- 安全审计；
- 性能测试；
- 模糊测试；
- 恢复测试；
- 文档；
- 演示环境；
- 验收报告。

验收：

- 验收矩阵全部通过；
- 无高危未决问题；
- 有完整运行手册。

---

## 11. 验证策略

### 11.1 单元测试

覆盖：

- 文件原子写；
- JSONL 追加；
- 锁；
- 路径校验；
- 插件 manifest；
- 平台前缀；
- 动作参数；
- 权限；
- 风险；
- 正则过滤；
- 加密信封；
- 回连算法；
- 结果聚合窗口。

### 11.2 集成测试

覆盖：

- 服务端启动；
- 文件数据库恢复；
- 动作调用；
- WebSocket 会话；
- AI 一次性请求；
- 插件加载；
- 监听器创建；
- 载荷生成；
- 任务下发；
- 结果回收；
- 代理建立；
- 上传/下载；
- 协议切换。

### 11.3 端到端测试

使用 Playwright：

- 登录；
- 创建监听器；
- 生成载荷；
- 查看 Beacon；
- 执行命令；
- 文件浏览；
- 文件编辑；
- 正则筛选；
- 审批；
- 审计。

### 11.4 协议测试

- 编码/解码；
- 分片/重组；
- 重放；
- 损坏包；
- 乱序；
- 超长字段；
- 多协议统一语义；
- 协议切换。

### 11.5 安全测试

- 未授权动作；
- CSRF/会话；
- AI Token；
- 插件签名；
- 路径穿越；
- Shell 调用扫描；
- 写盘扫描；
- 日志泄漏密钥；
- 正则拒绝服务；
- 大结果内存压力。

### 11.6 文件数据库恢复测试

- 写到一半崩溃；
- 临时文件残留；
- 索引损坏；
- JSON 损坏；
- 结果分块缺失；
- 未确认任务恢复；
- 重启后继续运行。

---

## 12. 验收标准

### 12.1 功能验收

必须通过：

1. 服务端启动后无本地控制输入；
2. Web 与 AI 都能通过 TCP 控制面调用；
3. 监听器可由客户端创建；
4. 载荷由协议插件生成；
5. 植入物起始协议由载荷/监听器决定；
6. 植入物无默认协议；
7. `lps` / `wps` 平台命令隔离；
8. 插件可签名、可版本化、可吊销；
9. 文件数据库可恢复；
10. 文件浏览器可用；
11. 文件编辑可保存；
12. 上传/下载 hash 一致；
13. 代理隧道可建立；
14. 本地 `.py` 可下发并内存执行；
15. 正则可筛选当前结果；
16. 正则可筛选下一结果；
17. 正则可持续筛选；
18. 结果不截断；
19. 5 秒聚合窗口可重置；
20. 任务下发频率影响回连间隔；
21. 协议可升级；
22. 协议可 fallback/random；
23. AI 高风险动作需审批；
24. 所有动作有审计；
25. 下发 Python 代码全部经过服务端注释剥离；
26. Web 无 console error；
27. 服务端重启后状态可恢复。

### 12.2 非功能验收

- 无必要不落盘检查通过；
- 无必要不 Shell 检查通过；
- 插件平台校验通过；
- 加密和混淆测试通过；
- 结果完整性测试通过；
- 文件数据库恢复测试通过；
- 大文件/大结果测试通过；
- 断线重连测试通过；
- 并发任务测试通过；
- 文档与代码一致。

---

## 13. 技术权衡摘要

| 决策点 | 方案 A | 方案 B | 当前倾向 |
|---|---|---|---|
| Web 控制通道 | WebSocket over TCP | 原生 TCP + 本地桥 | A，但需你确认 |
| Server 框架 | FastAPI/Uvicorn | 纯 asyncio/stdlib | A |
| 存储 | 文件 JSON/JSONL | SQLite | 文件 |
| 植入物加密 | `cryptography` | 纯 Python AEAD | 待决策 |
| 任务执行 | 线程池 | 进程池 | 线程池，待确认硬取消 |
| 插件签名 | HMAC-SHA256 | Ed25519 | 待决策 |
| Web 编辑器 | CodeMirror 6 | textarea | CodeMirror，待确认依赖 |
| AI 连接 | HTTP JSON over TCP | WebSocket | 待决策 |
| 结果过滤 | 客户端视图 | 服务端持久派生结果 | 客户端为主，服务端存规则 |
| 文件数据库索引 | 内存重建 | 持久索引 | 内存重建 + 可重建快照 |

---

## 14. 需要你敲定的问题

详细问题、选项与影响见：

```text
docs/DECISION_REGISTER.md
```

必须先确认的高优先级问题：

1. Web 是否接受 WebSocket over TCP，还是必须原生 TCP 桌面桥？
2. 植入物是否必须 stdlib-only？是否允许携带纯 Python 加密库？
3. 服务端是否可以使用 FastAPI/Uvicorn、Pydantic 等依赖？
4. 目标端最小 Python 版本是多少？
5. 无超时任务的并发上限和硬取消策略是什么？
6. 文件数据库的目标规模是多少？
7. 插件签名用 HMAC 还是非对称签名？
8. AI 一次性客户端用 HTTP JSON 还是 WebSocket/原生 TCP？
9. 是否需要 macOS 目标？
10. 代理隧道是否需要暴露给外部本地程序？
11. 文件编辑是否允许 CodeMirror 等前端依赖？
12. ICMP 是否必须进入 v1？
13. 协议随机策略是每轮连接随机还是按周期随机？
14. “任务下发次数”按单次动作还是按代码段计数？
15. 旧项目是否立即删除，还是保留作为参考分支？

---

## 15. 已确认决策应用后的技术修订

> 本节记录 2026-11-24 用户回答后的实施口径。冲突项仍以 `docs/DECISION_REGISTER.md` 的 C-01 到 C-16 待确认为准。

### 15.1 客户端与团队拓扑

- Web 客户端运行在操作员本地；server 运行在云端。
- Web 端不再使用用户名/密码 + 授权码登录。
- Web 与 AI 都使用 Token。
- server 启动时在终端打印 Token。
- Web 首次连接填写 server IP、客户端端口、Token，并在本地生成 `config.json`。
- 无效 Token 直接拒绝且不返回任何可识别内容。
- AI Token 不绑定具体操作员。
- Web 允许使用本地 Python 后端桥接浏览器与云端 server；不要求纯浏览器实现全部功能。
- Web 底层使用 WebSocket over TCP；AI 一次性客户端使用 HTTP JSON over TCP。

### 15.2 ICMP 与协议策略

- v1 不实现 ICMP；保留 `transport_plugins/icmp.py` 接口位，但不纳入首批可用协议。
- v1 不做 random / weighted-random。
- v1 只实现：
  - 由载荷/监听器决定初始协议 A；
  - 服务端显式下发任务升级到 B；
  - B 连续失败或连续断开达到心跳阈值后自动回退 A。
- 回退阈值：B 连续失败/断开 30 次心跳后回退 A。

### 15.3 任务计数与回连

- 每个代码段算 1 次任务下发。
- 观察窗口为 30 分钟。
- 5 秒结果聚合窗口保留：5 秒内新任务完成则重置，结果一起回传。

### 15.4 并发与硬终止

- 每个 Beacon 默认最大并发 8，可单独配置。
- 不实现内存/输出硬上限。
- 客户端结束任务时要求硬终止。
- 采用协作取消 + best-effort 强杀；硬杀后的线程资源不保证完全干净。

### 15.5 文件数据库与保留

- Beacon 上限 50。
- 每日任务数量 100。
- 上传/下载最大文件 1 GB。
- 结果与 Artifact 永久保留，不自动删除。
- 文件数据库仍使用 JSON/JSONL + 二进制文件 + 原子写。

### 15.6 插件与热重载

- v1 不做插件签名、信任链、多发布者。
- 插件目录即信任边界。
- 启动或热重载时只要文件存在就尝试加载。
- 加载失败打印错误；保留旧版本继续运行。
- 客户端可以请求服务端插件目录、读取/修改/替换插件，并触发热重载。
- 插件之间不做权限区分。
- 审批接口保留，但 v1 默认放行。

### 15.7 代理与文件传输

- 由服务端创建隧道，植入物反向连接形成隧道。
- 客户端访问服务端 SOCKS 端口进入植入端网络。
- SOCKS5：端口 1080，绑定 0.0.0.0，启用用户名/密码 + 来源 IP 白名单，允许多隧道，断开不自动重建。
- 上传/下载：
  - 最大文件 1 GB；
  - 分块 1 MB；
  - 支持断点续传；
  - 覆盖必须显式确认；
  - 备份可选。

### 15.8 AI 客户端

- `client_ai.py` 使用 HTTP JSON over TCP。
- 长任务默认只返回 `task_id`。
- AI 可以一次下发多个任务，之后统一查询结果。
- Web 与客户端需要提供历史命令/结果查看功能。
- 客户端目录提供 AI 教程和 `config.json`。

### 15.9 客户端本地形态

- 不做桌面客户端壳。
- 采用：本地 Python 后端 + 本地静态页面，浏览器只访问 localhost。
- 本地后端负责：
  - 提供静态页面；
  - 保存 `config.json`；
  - 桥接 WebSocket/TCP；
  - 代理本地 SOCKS 相关操作（若需要）。
- 新建独立重建目录；旧项目保留只读参考。

### 15.10 默认审批

- 审批只有两种模式：
  1. 逐条审批：全部动作拦截，人工逐条放行后才执行；
  2. 全部放行：只记录审计，不拦截。
- 两种模式均可配置。
- 人工审批界面保留。

### 15.11 服务器平台

- 服务端主要运行平台：Linux。
- 交付形式：Python 包 + 启动脚本。
- 运行时依赖：FastAPI、Uvicorn、Pydantic。
- 不依赖数据库服务。

### 15.12 决策冻结结果

所有此前的 C-01 到 C-16 冲突均已关闭：

- 插件不做签名与信任机制；
- 上传/下载最大文件 1 GB；
- 硬终止采用协作取消 + best-effort 强杀；
- 每日任务 100；
- SOCKS5 端口 1080，绑定 0.0.0.0，用户名/密码 + IP 白名单；
- B 连续失败 30 次心跳后回退 A；
- 任务下发观察窗口 30 分钟；
- Web 采用本地 Python 后端 + 本地静态页面；
- 新建独立重建目录，旧项目只读保留；
- Web 插件编辑器 + 保存后立即热重载；
- 审批只有逐条审批 / 全部放行两种模式；
- 结果与 Artifact 永久保留。

技术方案已进入“可执行冻结”状态。

---

## 16. 最终技术结论


技术上建议采用：

```text
Python 3.12+ 服务端
+ asyncio + FastAPI/Uvicorn
+ 文件 JSON/JSONL 数据库
+ React 19 + Vite + TypeScript 工作台
+ Python 单文件 client_ai.py
+ 线程池植入物执行器
+ 可插拔传输协议
+ 签名 Python 插件
+ 端到端 Playwright + pytest 验收
```

但以下问题不能由技术侧替你拍板：

- 加密依赖策略；
- Web 的 TCP 语义；
- 无超时下的资源边界；
- 文件数据库规模；
- 插件签名信任模型；
- AI 客户端连接方式；
- 是否删除旧项目。

这些必须先在 `docs/DECISION_REGISTER.md` 中逐项确认，再进入实现。
