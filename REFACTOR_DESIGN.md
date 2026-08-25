# PyExec-C2 重构设计文档

> 本文件是本次重构的活文档，随讨论逐步推进。每一步完成都会更新「文档状态」。
> 现状代码：`/home/clay64/Desktop/pyexec-c2-main`

---

## 文档状态

- [x] **Step 1 — 现状通读与问题盘点**（2026-08-05）
- [x] **Step 2 — 重构目标确认**（2026-08-05，用户拍板）
- [x] **Step 3 — 目标架构设计**（2026-08-05，草案 + 模块化边界清单）
- [x] **Step 4 — 协议设计**（2026-08-05，见第 7 章）
- [x] **Step 5 — 模块系统设计**（2026-08-05，D1-D4 全部确认，见第 5 章）
- [x] **UpLevel 升级与 Proxy 兼容层设计**（2026-08-05，U1-U4 全部确认，见第 6 章）
- [x] **Step 6 — 实施计划与任务队列**（详细版已出：P0-P8 共 40 任务，见第 8 章）
- [x] **补充设计**（2026-08-05：1 headless+端口密钥分离 已定 / 2 任务状态追踪 已否 / 3 日志审计 已定 / 4-5 已定，见第 10 章）
- [x] **实施完成**（2026-08-05：P0-P8 全部 41 任务验收通过，161 测试全绿 ×3 稳定；见第 8 章任务状态）

---

## 1. 现状通读

### 1.1 代码规模

| 目录 | 行数 | 说明 |
|------|------|------|
| core/ | ~240 | 协议、加密、配置（零依赖基础设施） |
| server/ | ~1800 | 主入口、handler、console、模块加载、11 个植入模块、server 端模块 |
| client/ | ~190 | CLI 入口 + 加密通信层 |
| implant/ | 42 | 单行 Beacon 模板（压缩代码） |
| build.py | 131 | 生成单行部署命令 |
| **合计** | **~2400** | 纯 Python 3 stdlib，零第三方依赖 |

### 1.2 实体与数据流

```
操作员 ──(明文命令)──> Client ──加密TCP──> Server :9001
                                            │ 任务队列 / 审计日志 / 模块库
                                            ├──> Beacon A（定时回连，exec() 执行）
                                            └──> Beacon B
```

三种实体：
- **Server**：单端口监听；每连接一个 HandlerThread；交互式控制台是主线程，也是整个进程的生命周期中枢。
- **Beacon（植入体）**：`echo '<bootstrap>' | python3` 单行部署；随机 ID（token_hex(8)，每次进程重启换新）；定时回连，注册 → 取任务 → exec() → 回传结果 → 收 pong 断开。
- **Client**：操作员 ↔ Server 的透明管道，注册时带 `is_client: true`，之后走「逐行纯文本」协议，Server 端由 `console.execute()` 处理并回传输出。

### 1.3 有线协议（现状）

帧格式：`[4B BE 长度头][Base85(XOR(zlib(payload)))]`，最大 512KB。

| type | 方向 | 现状 |
|------|------|------|
| `register` | → Server | 仅带 id / is_client，无版本、无会话 |
| `task` | Server → | 下发 Python 代码 |
| `result` | → Server | 回传 output/error |
| `pong` | Server → | 无任务，结束本次连接 |
| `disconnect` | Server → | README 有提及，**代码中未实现** |

两条并存的连接协议：
1. **Beacon 协议**（JSON 帧）：register → task/result 循环 → pong。
2. **Client 协议**（纯文本行帧）：register → 裸文本命令行 → `{"status":"ok","output":...}` JSON 响应。

### 1.4 模块系统（现状）

- **植入模块**（server/modules/*.py）：docstring 里写 `@module/@desc/@params` 元数据；每个模块必须定义 `name_linux / name_windows / name_mac / name_all` 四个变体函数（`pass` 表示该平台无实现）；下发时按 Beacon 平台裁剪并拼装成可 exec() 的代码字符串。
- **JSON 序列模块**（*.json）：steps 列表串联多个模块，Server 端去重内联代码后串行调用。
- **Server 端模块**（server/server_modules/*.py）：动态 import + 每次执行 reload，调用 `run(*args)`。现有 proxy.py 用于生成密钥转换中继（UpLevel 兼容层）。
- 隐含契约：`set_host / set_interval / set_key` 直接改写 exec() 环境中预定义的全局变量 `_H/_P/_I/_J/_K`。

### 1.5 加密（现状）

`zlib → XOR(32B key) → Base85`，声明为「混淆层」而非密码学安全。XOR key 以 64 字符 hex 明文存在 server/client 的 config.json 里。

---

## 2. 问题盘点

按层分类，作为重构输入。标 ⚠️ 的为建议优先处理。

### 2.1 协议层

| # | 问题 | 位置 |
|---|------|------|
| P1 ⚠️ | 无握手/版本协商：任何持有 XOR key 的端都能注册任意角色，无服务端 banner、无协议版本号 | handler.py `_handle_one_connection` |
| P2 ⚠️ | Beacon 与 Client 两套协议并存（JSON vs 纯文本行），解析与错误处理完全分离 | handler.py `_task_loop` / `_command_loop` |
| P3 ⚠️ | 消息类型硬编码字符串散落各 if/elif，无集中定义；`disconnect` 定义了却没用 | handler.py、implant_template.py |
| P4 | Beacon ID 进程重启即变，无持久身份，`use/show` 对重启后的 beacon 失效 | implant_template.py `token_hex(8)` |
| P5 | 注册即信任：无认证握手，无会话令牌；`is_client: true` 可被任意端伪造（拿到 key 即可） | handler.py |
| P6 | socket 写路径无超时，对端不读会挂住线程 | protocol.py `send_frame` |
| P7 | 无 TLS（README 已声明 XOR 为混淆层，属设计取舍，需确认是否升级） | — |

### 2.2 服务端结构

| # | 问题 | 位置 |
|---|------|------|
| S1 ⚠️ | HandlerThread 职责过重：`_send_and_wait` 一个方法混合了传输、任务生命周期、结果存储、sysinfo 解析、控制台打印 | handler.py |
| S2 ⚠️ | Console 既是命令引擎又是 UI：handler 的 Client 路径直接调 `console.execute()`；Server 启停都以 `console._running` 为生命中枢 | server.py、handler.py、console.py |
| S3 ⚠️ | 重复代码三处：① 模块参数解析 `_parse_module_params` / `_parse_param_names`；② sysinfo 代码生成 `_build_auto_task` / `_cmd_sysinfo`；③ 模块→参数→代码构建逻辑（auto task / _exec_module / broadcast 各写一遍） | handler.py、console.py |
| S4 | `HandlerThread.run` 吞掉全部异常，无错误日志 | handler.py |
| S5 | `ClientManager.list_clients()` 返回可变引用，console 在锁外读字段，存在竞态 | client_manager.py |
| S6 | `TaskResult` 列表无限增长，无上限/归档 | client_manager.py |
| S7 | `TaskQueue` 用 `list.pop(0)` O(n) 出队；断线重排回队尾语义不精确 | task_queue.py |
| S8 | `server.py stop()` 直接访问 `self._console._running` 私有字段；`_ensure_xor_key` 裸 `except Exception: pass` 改写配置文件 | server.py |
| S9 | 清理线程 / 监听线程 / handler 生命周期互相缠绕，退出路径不清晰 | server.py |

### 2.3 模块系统

| # | 问题 | 位置 |
|---|------|------|
| M1 ⚠️ | docstring 正则解析元数据（`@desc/@params`），脆弱且无校验 | module_loader.py |
| M2 ⚠️ | 强制四个变体函数，缺一个**静默跳过整个模块**（无警告、无日志） | module_loader.py `_load_py_module` |
| M3 | `pass` 体判定靠启发式（`_is_pass_body`），缩进/注释变化即误判 | module_loader.py |
| M4 ⚠️ | `set_*` 模块依赖 exec 环境隐式全局变量 `_H/_P/_I/_J/_K`，与 implant 模板耦合，无文档无校验 | modules/set_*.py + implant_template.py |
| M5 | `break` 模块四个变体全 pass，纯占位死代码 | modules/break.py |
| M6 | JSON 序列模块引用不存在的模块或嵌套 JSON 模块时**静默失败**（`[module X not found]`） | module_loader.py `_build_json_task` |
| M7 | 平台命名不一致：函数变体叫 `_mac`，控制台命令用 `macos`，需要转换 | module_loader.py / console.py |
| M8 | 代码生成靠字符串拼接 + repr()，无参数校验、无生成代码大小限制 | module_loader.py |

### 2.4 客户端 / 构建

| # | 问题 | 位置 |
|---|------|------|
| C1 ⚠️ | `_BOOTSTRAP` 模板在 build.py 与 server_modules/proxy.py 各有一份，且 build.py 硬编码 `%32`（key 长度），proxy 用 `len(key)`，两份已不一致 | build.py、proxy.py |
| C2 | implant 模板内联重复了 crypto/framing 逻辑（单行部署的取舍，但无测试保护） | implant_template.py |
| C3 | `RemoteClient.send()` 与 `send_line()` 逻辑几乎相同 | remote_client.py |
| C4 | remote_client 用 `print + sys.exit(1)` 处理配置错误——库代码不应退出进程 | remote_client.py |

### 2.5 工程化

| # | 问题 | 位置 |
|---|------|------|
| E1 ⚠️ | README 声称 `tests/ 11 个文件 153 用例`，**仓库中实际没有 tests 目录** | — |
| E2 | 无日志框架，print 满天飞；handler 异常全部静默 | 全局 |
| E3 | `server_modules/output/` 与 `c2_audit_history.log` 等运行产物/密钥文件提交在仓库里 | — |
| E4 | 服务端/客户端配置混在一个 `Config` dataclass；未知 key 静默过滤；xor_key 明文 | core/config.py |
| E5 | audit_logger 每行打开一次文件，无缓冲 | audit_logger.py |
| E6 | `chdir` 到脚本目录的启动方式导致从任意路径运行行为不一致 | server.py / client.py |

---

## 3. 重构目标（已确认 2026-08-05）

**用户拍板：**

> 1. **优先解耦**。
> 2. **核心原则：server 端凡是能写成模块的业务逻辑，一律不留在 server 集成代码中**（server.py / handler.py / console.py 只保留框架性编排）。

由此推导的目标架构（Step 3 草案）：

```
pyexec2-c2/
├── core/                        # 基础设施（框架层，非业务模块）
│   ├── crypto.py                # 加密管道
│   ├── protocol.py              # 帧协议 + 消息类型常量
│   ├── config.py                # 配置加载（server/client 分拆）
│   ├── log.py                   # [新增] 统一日志（logging 封装）
│   └── events.py                # [新增] 审计事件类型常量（消灭散落字符串）
│
├── server/
│   ├── server.py                # 薄启动器：装配 + 生命周期（仅进程级编排）
│   ├── listener.py              # [新增] 网络层：accept → Connection → 会话分发
│   ├── sessions/
│   │   ├── __init__.py
│   │   ├── beacon.py            # [新增] Beacon 会话（注册/任务循环/结果）
│   │   └── client.py            # [新增] Client 会话（命令通道）
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── dispatcher.py        # [新增] 命令引擎（纯逻辑，无 I/O）
│   │   └── commands/            # [新增] 每个命令一个模块（注册式）
│   │       ├── beacon.py  use.py  show.py  modules.py  info.py
│   │       ├── raw.py  broadcast.py  platform.py  result.py
│   │       ├── log.py  reload.py  config.py  help.py  exit.py
│   │       └── server_exec.py   # 调用 server_modules 的命令
│   ├── infra/                   # 基础设施（框架层）
│   │   ├── task_queue.py        # deque 化 + 任务状态机
│   │   ├── client_manager.py    # 注册表（快照接口，消除锁外读）
│   │   └── audit_logger.py
│   ├── modules/                 # 植入模块（下发到 Beacon 执行）
│   │   ├── sysinfo.py           # [新增] 从 handler/console 硬编码中剥离
│   │   ├── ls.py  ps.py  ...    # 现有 11 个
│   ├── server_modules/          # Server 端模块（本机执行，已有机制）
│   │   ├── proxy.py
│   │   ├── build.py             # [迁移] 原顶层 build.py 并入（生成部署命令）
│   │   └── keygen.py            # [新增] 随机生成密钥并自动写入 config.json
│   └── ui/
│       └── console.py           # [改造] 纯 UI：读输入/渲染输出，逻辑全走 dispatcher
│
├── client/                      # 操作员端（协议升级后复用统一 JSON 帧）
├── implant/                     # Beacon 模板
└── tests/                       # [新增] pytest 套件
```

### 模块化边界清单（核心决策）

**留在集成代码中的（框架职责，不属于"业务"）：**

| 职责 | 位置 |
|------|------|
| 进程生命周期、socket 监听、线程编排 | server.py |
| 传输层帧收发、消息类型常量 | core/protocol.py |
| 连接 → 会话分发（每连接一个会话线程） | listener.py |
| 任务队列 / 客户端注册表 / 审计日志 | server/infra/ |
| 命令引擎骨架（注册表 + 分发，不含具体命令） | engine/dispatcher.py |
| Beacon/Client 会话协议流程（注册→任务→结果→pong） | sessions/ |

**必须拆成模块的（业务逻辑，逐项对号入座）：**

| 现状硬编码位置 | 业务 | 目标归宿 |
|---------------|------|----------|
| handler.py `_build_auto_task` 中 sysinfo 特殊分支 | sysinfo 代码生成 | server/modules/sysinfo.py（普通植入模块） |
| console.py `_cmd_sysinfo` 内联代码 | 同上 | 同上（console 内置命令删除，走模块管线） |
| client_manager.py `set_sysinfo` 平台字符串判定 | 平台检测 | core 工具函数或 sysinfo 模块逻辑 |
| handler.py / console.py 模块参数解析（两份） | 命令→参数映射 | engine/dispatcher.py 统一实现 |
| handler.py auto_commands 命令→Task 构建 | 命令→任务构建 | engine/dispatcher.py（handler 只调用，不含模块知识） |
| console.py 全部 `_cmd_*` 内置命令 | 命令实现 | engine/commands/ 每命令一模块 |
| console.py `_exec_module` / broadcast 模块构建 | 模块命令执行 | dispatcher 统一入口 |
| handler.py 结果打印 / 上线横幅 | 输出渲染 | 交给 UI 回调（session 只产生事件，不打印） |
| server.py `_ensure_xor_key` 密钥管理 | 密钥生命周期 | server_modules/keygen.py（随机生成写回 config.json）+ server 启动兜底（缺 key 自动生成，正规化） |

**会话层与 UI 解耦方式（Q6 已定）：** Beacon/Client 会话不再直接调 console.safe_print，改为把「上线 / 任务结果 / 断开」事件写入统一事件文件（JSONL，同时充当审计日志）；Console 的后台转发线程轮询文件增量并打断渲染；未来 API 层 tail 同一文件实现多 UI。

## 4. 待决问题

> 每轮讨论的结论记录在此，形成决策记录。

**已确认：**
- Q1（优先级）：**优先解耦**。在此基础上再谈协议/工程化。
- Q4 变体（模块化边界）：**server 端能写成模块的业务一律不留集成代码**——该原则已扩展到命令层（内置命令也注册化）。
- Q2（零依赖）：默认保持纯 stdlib（无反对意见）。
- Q3（兼容性）：默认不强制兼容旧部署，协议可改。
- Q5（测试）：默认补全测试套件为验收标准。

**待细化：**
- Q4 原问题（植入模块机制）：四变体 + docstring 解析是否重做，还是先保持、只做边界拆分？（Step 5 再定）
- Q6（**已确认**）：**文件事件流**（用户提出）。会话事件（上线/结果/断开）由会话线程写入统一事件文件（JSONL，一行一事件），文件既是事件总线又是审计日志；console 起后台转发线程轮询文件增量并打断渲染到屏幕（保留现有实时 UX）；未来 API/Web 各自 tail 同一文件。完整结果仍存内存 ClientRecord.results，事件文件只存概要行防膨胀。
- Q7（**已确认**）：**模块声明元数据标记 + 结果处理器做成 server 端模块**。植入模块在 `MODULE` dict 里声明 `result_processor` 处理器名；Task 携带该标记；结果回来后框架按标记查 server_modules 处理器，调用 `run(output, error) -> dict`，返回值按 ClientRecord 元数据字段白名单回填。解析逻辑、平台判定全部在模块内，框架零业务知识，不硬编码模块名。

---

## 5. 模块系统设计（Step 5）

### 5.1 植入模块 v2 格式

```python
# server/modules/ps.py
"""列出进程"""
import os

MODULE = {
    "desc": "列出进程",
    "params": [],                    # [(参数名, 提示), ...]
    "result_processor": "",          # 可选：结果处理 server 模块名（Q7）
}

def run_linux():
    ...   # /proc 实现

def run_windows():
    ...   # tasklist 实现

def run():
    ...   # 可选：跨平台兜底
```

规则：

1. **元数据集中到顶层 `MODULE` 字面量 dict**，AST 解析（`ast.literal_eval` 校验），彻底替换 docstring 正则（解决 M1）。
2. **入口函数为 `run()` 或 `run_<platform>()`，全部可选**，不再强制四变体（解决 M2：缺实现就少写一个函数，没有 pass 占位；`_is_pass_body` 启发式整体删除，解决 M3）。
3. **平台选择**：`run_<platform>` 已定义 → 调用；否则 `run()` 已定义 → 调用；否则显式 ValueError + 日志（不再静默）。
4. **下发内容**：整个模块源码（去掉 `if __name__` 块）+ 选中入口调用语句 + `print(result)`。与现状一致——payload 本来就包含全部变体，平台裁剪只发生在调用点。
5. **`params` 结构化**：`[(name, hint)]`，参数名直接取自元数据，消灭 handler/console 里两份参数解析（解决 S3）。
6. **加载失败显式化**：语法错误 / MODULE 非法 / 未知键 → 记录日志并跳过（解决 M1 补强）。

### 5.2 结果处理器（Q7 落地）

- 植入模块声明 `MODULE["result_processor"] = "sysinfo_parse"`。
- dispatcher 构建任务时：`Task(code=..., result_processor=<标记>)`。
- 会话收到 result 后：按标记查 server_modules 处理器，`run(output, error) -> dict`；返回值与 ClientRecord 元数据字段白名单（`sys_user` / `sys_os` / `sys_platform`）比对后回填，未知键告警丢弃。
- 删除 handler 的 `is_init` 标志与 `_cache_sysinfo_from_result`。
- 平台判定（windows/linux/darwin 字符串匹配）从 client_manager 迁入 sysinfo_parse 模块。
- 新增模块（如 whoami）复用同一处理器或自建，框架零改动。

### 5.3 参数与大小校验

- dispatcher 构建任务前校验：参数个数与 `params` 声明不符 → 拒绝并提示。
- 生成代码长度 > 配置新增项 `max_task_code_size` → 拒绝。

### 5.4 JSON 序列模块

- 保留 steps 串联；加载时**显式校验**：step 引用的模块必须存在且为 python 类型，否则加载报错并列出（解决 M6）。
- 嵌套 JSON 模块：加载时拒绝，防止隐式递归。

### 5.5 set_* 与 implant 全局契约

- 保留 exec 环境全局变量机制，**保持短变量名 `_H/_P/_I/_J/_K` 不变**（D2 决策：极致缩小载荷体积，implant 模板维持压缩风格；另预留 `_T` 传输钩子、`_B` 退级标志）。
- 契约文档化：implant 暴露的全局变量写入模块开发文档（`server/modules/README.md`），set_* 模块引用即契约。

### 5.6 Server 端模块 v2

- 元数据与植入模块统一：顶层 `MODULE` dict + AST 解析（替换 docstring 解析）。
- 执行机制不变：import + reload + `run(*args)`。
- 结果处理器成为 server_modules 的一等公民：`run(output, error) -> dict`。
- 执行异常增加 logging 输出（不再只返回 traceback 字符串）。

### 5.7 共享解析基础设施

- 新增 `server/module_meta.py`：纯函数（`parse_meta / extract_code / list_funcs`），AST 实现，可单测。
- module_loader 与 server_module_loader 共用（消灭两份解析代码）。

### 5.8 删除项

- ~~`break` 模块~~（D3 已否：保留，作为退级信号，见 6.12）。
- docstring 解析器、`_is_pass_body`、`_parse_module_params` / `_parse_param_names`。

### 5.9 影响面

- `server/modules/` 11 个模块全部改写为 v2 格式。
- 新增 `server/modules/sysinfo.py`、`server/server_modules/sysinfo_parse.py`。
- module_loader.py 重写解析与构建逻辑。
- handler.py 的 sysinfo 特殊分支与参数解析删除，改走 dispatcher。

### 5.10 待确认（D1-D4）

- **D1**：模块格式 v2（MODULE dict + 可选平台入口函数）——**已确认**。
- **D2**：~~全局变量改名~~ **已否**（2026-08-05）：保持 `_H/_P/_I/_J/_K` 短名，极致缩小载荷体积。
- **D3**：~~删除 break~~ **已否**（2026-08-05）：保留，作为退级信号（见 6.12）。
- **D4**：`server/module_meta.py` 共享 AST 解析层——**已确认**。

---

## 6. UpLevel 升级与 Proxy 兼容层设计

### 6.1 目标与场景

基础载荷（XOR+TCP）上线后，通过 `uplevel` 命令升级通信通道：

- **协议可切换**：TLS / HTTPS / DNS 等，由传输层抽象支持（密钥/加密方式随协议一起变）。
- **可指定新地址**：载荷转到 proxy 通信，proxy 再连 server——载荷不再直连 server。
- **proxy 是一句话 Python**：自包含单行代码（`echo '...' | python3`），可运行在任意非 server 机器，不依赖 server 代码库。
- **升级后身份延续**：同一 beacon 的任务队列 / 元数据 / 结果历史不丢。

```
                    初始: XOR+TCP 直连
  implant ────────────────────────────> Server:9001
     │  uplevel tls <proxy_host> <proxy_port>
     ▼
  implant ──(TLS/HTTPS/DNS)──> proxy ──(XOR+TCP)──> Server
  （一句话代码，               （一句话代码，
   密钥 = proxy_key）          密钥 = server_key）
```

### 6.2 传输层抽象（协议升级的地基）

现状协议是固定管道（zlib+XOR+Base85 over TCP）。升级必须把「传输通道」抽象出来：

```
消息层（不变）  : JSON 帧 {type: register|task|result|pong}
帧层（不变）    : [4B BE 长度头][载荷]
传输层（可替换）: Transport 接口
                   connect() / send(data) / recv() -> data / close()
   实现:
     TcpXorTransport  —— 现状（zlib+XOR+Base85）
     TlsTransport     —— ssl 自签证书 + 指纹 pin
     HttpsTransport   —— HTTP POST 轮询（半双工）
     DnsTransport     —— DNS 查询/响应编码（半双工）
```

要点：

1. **消息语义与传输解耦**：register/task/result/pong 在任意传输上语义不变。
2. **implant 现有模型天然适配**：当前是「一连接一周期」（连→注册→取任务→结果→pong→断开→sleep→重连）。HTTPS/DNS 的请求-响应轮询 = 一次 HTTP 请求/DNS 查询完成一个周期，无任务时响应体为空（替代 pong）。
3. **升级只换传输层**：帧协议与消息层不动，升级 = 下发新 Transport 实现 + 切换全局参数。

### 6.3 协议实现代码按需下发

**基础载荷保持最小**（只内置 TcpXorTransport），协议实现代码按需下发：

- server 端生成器模块：`server/server_modules/transport_tls.py`、`transport_https.py`、`transport_dns.py`，各暴露 `run(...) -> str` 生成可 exec 的传输实现代码（符合 Step 5 的 server 模块 v2 格式）。
- implant 模板预留钩子：全局 `_T`（当前 Transport 工厂）与参数 `_H/_P/_K`；升级代码 exec 后覆盖 `_T` 与参数，implant 断开旧连接，下一周期用新传输重连。
- 好处：单行部署命令不膨胀；新协议 = 新增一个 server 生成器模块，框架零改动。

### 6.4 uplevel 命令（双层模块化）

uplevel 需要 server 端生成器参与（植入模块是纯文本下发，无 server 端知识），因此设计为**注册式控制台命令 + server 端生成器**：

- `engine/commands/uplevel.py`：`uplevel <beacon_id> <protocol> <host> <port>`
  1. 按 protocol 查 server_modules 的 transport 生成器；
  2. 组装升级任务：传输实现代码 + 设置 `_H/_P/_K/_T` + 断开重连；
  3. 下发 Task，审计事件 `UPLEVEL_INITIATED`。
- 与 `set_host / set_key / set_interval` 的关系：set_* 保留为手动微调（不换协议）；uplevel 是协议级一键升级。
- `break` 模块：**保留**（D3 决策），作为退级信号——升级进入增强会话后，执行 break 退出并退回基础 beacon 循环（见 6.12）。

### 6.5 Proxy 生成器重做（server_modules/proxy.py）

现状 proxy.py 只做密钥转换且生成逻辑内联。重做后：

- 签名扩展：`run(host, port, key_hex, protocol="tls", ...)` → 生成：
  - **proxy 一句话部署命令**（自包含：server 侧 TcpXor 客户端 + implant 侧 `<protocol>` 服务端 + 转发主循环）；
  - **proxy_key**（implant↔proxy 段，proxy 自动生成，返回给操作员）；
  - **TLS 证书 + 指纹**（protocol=tls 时，自签）；
  - **server_key** 沿用（proxy↔server 段，来自参数）。
- proxy 代码 = 模板拼接（现有 `_PROXY_TEMPLATE` 模式扩展为多协议模板）；生成逻辑保持为 server 端模块，符合"能模块化的不留集成"。
- proxy 自身也是单行自包含代码，运行在任意机器，与 server 代码库零依赖（现状已是如此，保持）。

### 6.6 密钥与信任体系

- 两段密钥：implant↔proxy 用 proxy_key；proxy↔server 用 server_key（现状已是）。
- **proxy 是信任边界（解密点）**：proxy 代码由操作员自己生成部署，天然可信；server 永远不需要知道 proxy_key。
- TLS：自签证书 + 证书指纹 pin（stdlib `ssl` + `hashlib` 可行，零依赖）；指纹烧进 proxy 与升级指令。
- 升级指令内嵌 proxy_key（hex/base64）——指令本身走加密通道下发，泄露面可控。

### 6.7 身份延续（替代 px_ 前缀）

现状 proxy 以 `px_<id>` 注册 → server 端是全新 beacon，队列/结果全丢。新设计：

- register 消息增加可选字段 `"via": "proxy"`；proxy 转发时**保留原始 id**。
- server 端 ClientRecord 增加 `via` 字段；register 同 ID → 复用记录，任务队列/元数据/结果历史延续。
- 冲突防护：同 ID 但 via/来源不同 → 告警日志（正常升级场景下旧连接已断）。

### 6.8 升级端到端流程

1. **生成 proxy**：`server_exec proxy <proxy_host> <port> tls <server_key_hex>` → 输出一句话部署命令 + proxy_key + 证书指纹。
2. **部署 proxy**：在非 server 机器执行 proxy 命令 → proxy 监听新协议端口。
3. **下发升级**：console `uplevel <beacon_id> tls <proxy_host> <proxy_port>`。
4. **组装任务**：server 查 transport_tls 生成器 → 升级任务（传输实现 + 设置 `_H/_P/_K/_T` + 断连）。
5. **载荷切换**：implant exec 升级代码 → 更新 `_T` 与参数 → 断开旧连 → 用 TLS + proxy_key 连 proxy。
6. **代理注册**：proxy 收 implant（TLS）→ 连 server（XOR+TCP, server_key）→ 转发 register（原 id, via=proxy）。
7. **身份复用**：server 识别同 ID → 延续 ClientRecord → 继续下发原队列任务。
8. **结果回传**：implant → proxy（TLS）→ server（XOR）。

### 6.9 边界情况

- **升级失败（U4 决策：必须回退）**：升级任务两阶段执行——先尝试新通道连接 + 握手验证，**成功才提交新参数；失败保留旧参数**，implant 继续走旧通道回连，并把失败详情回传 server。不存在失联窗口。
- **proxy 掉线**：implant 重连失败 → 退避重试（现有 sleep 逻辑）；proxy 重启后恢复。
- **HTTPS/DNS 半双工**：轮询模式下无任务 = 响应体为空；implant 等下一周期。
- **多级 proxy**：proxy 的 server 段协议同样可升级（不在 v1 范围，传输抽象已为其铺路）。

### 6.10 与模块系统设计的关系

- `transport_*` 生成器 = server_modules 新成员，复用 v2 格式（MODULE dict + run()）。
- `uplevel` = engine/commands/ 注册式命令。
- set_host/set_key/set_interval 保留；break 保留为退级信号（见 6.12）。
- implant 模板重构时预留传输钩子 `_T`（当前 Transport）与参数 `_H/_P/_K/_I/_J`（协议由 `_T` 隐式表达，保持短名，与 5.5 一致）。

### 6.11 载荷编码：base85 → base64（用户决策）

- 全部载荷编码（core/crypto.py 的 encode/decode、build.py bootstrap、proxy 生成模板、implant 模板）从 Base85 改为 **Base64**。
- 理由：Base64 字符集（`A-Za-z0-9+/=`）在单引号 shell 部署命令、JSON、URL 等场景完全兼容；Base85 虽省约 7% 体积，但经 zlib 压缩后实际差异有限。
- 体积策略（与 D2 一致）：极致缩小靠 zlib 压缩 + 短变量名/压缩代码风格，不靠编码格式。

### 6.12 增强会话模式（break 的用途，D3 决策）

- uplevel 升级除换传输外，可切换运行模式：
  - **代理模式（默认）**：仅换通道，保持基础回连循环；
  - **交互模式（可选）**：如交互 shell——升级任务内嵌长连接循环，implant 保持连接，逐条接收命令执行并回传（stdin/stdout 转发）。
- 交互模式下执行 `break`：break 模块 v2 格式为 `MODULE={"desc": "退出增强会话，退回基础 beacon", "params": []}` + `def run(): global _B; _B = True`；交互循环检测 `_B` 退出，implant 退回基础回连循环（走当前生效的通道参数）。
- 交互循环代码同样按需下发（U2），基础载荷不含。

### 待确认（U1-U4）

- **U1**：身份延续用 `via` 字段 + 原 ID 复用（替代现状 px_ 前缀）——**已确认**。
- **U2**：协议实现按需下发（载荷保持最小，新协议=新增 transport 生成器模块）——**已确认**。
- **U3**：TLS 用自签证书 + 指纹 pin（零依赖方案）——**已确认**。
- **U4**：~~v1 升级失败不回退~~ **已否**（2026-08-05）：升级必须回退，两阶段切换（见 6.9）。

---

## 7. 协议设计（Step 4）

### 7.1 目标

- 统一 Beacon 与 Client 两条连接协议为同一 JSON 帧协议（解决 P2）。
- 握手 + 版本协商 + 显式角色声明 + 服务端 banner（解决 P1、P5）。
- 消息类型集中定义与校验（解决 P3）。
- 错误显式化：error 消息替代静默断开（解决 P4 相关）。
- 兼容半双工传输（HTTPS/DNS 轮询，见 6.2）。

### 7.2 帧格式（保持，编码改 base64）

`[4B BE 长度头][Base64(XOR(zlib(payload)))]`，最大 512KB。

- 编码：base85 → **base64**（6.11 决策）。
- 写路径超时：socket timeout 同时约束 send/recv，传输层统一设置并文档化（P6）。

### 7.3 消息类型常量（core/protocol.py）

```python
REGISTER = "register"   # → Server：注册即握手（带 version/role/id/via）
WELCOME  = "welcome"    # Server →：握手成功 + 服务端 banner
TASK     = "task"       # Server →：下发代码（task_id/code）
RESULT   = "result"     # → Server：执行结果（task_id/output/error）
PONG     = "pong"       # Server →：无任务，结束本周期
COMMAND  = "command"    # Client 通道（新）：命令文本
RESPONSE = "response"   # Client 通道（新）：命令输出
ERROR    = "error"      # 新：错误消息（code/message），发送后断开
```

+ `validate_message(msg) -> Optional[str]` 校验函数（返回错误描述或 None）。

### 7.4 握手（单帧注册即握手）

register 扩展：

```json
{"type": "register", "version": 1, "role": "beacon"|"client", "id": "...", "via": "proxy"(可选)}
```

- Server 兼容 → `{"type": "welcome", "version": 1, "server": "pyexec-c2/1.0"}`。
- 版本不兼容 → `{"type": "error", "code": "VERSION_MISMATCH", "message": "..."}` 后断开。
- `role` 显式枚举（替代 `is_client` 布尔），未来可扩展（如 `relay`）。
- `via` 字段：proxy 转发保留原 id（U1 决策）。

### 7.5 角色会话分发

Server 收到 register 后按 `role` 分发到 BeaconSession / ClientSession（第 3 章架构），handler 中不再有 if/elif 分流：

- **Beacon 会话**：task/result 循环 → pong（现状语义不变）。
- **Client 会话**：COMMAND/RESPONSE 循环
  - 请求：`{"type": "command", "line": "<命令文本>"}`
  - 响应：`{"type": "response", "status": "ok"|"error", "output": "..."}`
  - 现状「纯文本行」协议废弃，remote_client 同步改造。

### 7.6 错误与边界

- 帧超限 / JSON 解析失败 / 未知 type → error 消息 + 断开（不再静默）。
- 半双工传输（HTTPS/DNS）：请求-响应模型，响应体为空 = pong 语义；帧与消息语义不变（6.2）。
- 每周期一连接模型不变（Beacon 现状），为半双工轮询留好适配面。

### 7.7 兼容性

- 协议版本 v1 起步；version 字段为后续演进预留。
- 旧部署不兼容（Q3 决策），build.py 重新生成部署命令。

---

## 8. 实施计划与任务队列（Step 6，详细版 2026-08-05）

> **实施状态（2026-08-05）**：P0-P8 全部任务完成 ✅。验收 = 161 个测试全绿
> （含真 implant 部署端到端、UpLevel TLS 升级/回退端到端），连续 3 次全量
> 回归稳定。实施过程中修正的三处实现级问题（非设计变更）：
> ① Linux 阻塞 accept 不受 close(fd) 打断 → Listener 停止标志 + 端口释放
> ≤1s 窗口（测试容忍）；② 升级任务执行后同周期结果回传误用新密钥 →
> implant 帧加解密改用连接级 `_CK`（连接建立时锁定，任务改 `_K` 不影响
> 本周期回传）；③ proxy 压缩代码参数名 `d` 遮蔽 `base64 as d` 模块别名 →
> 参数改名 `q`。

> **总原则**：每个任务完成 = 代码 + 测试 + 验收三项齐。推荐 TDD 节奏（先写测试后实现）。
> 每阶段结束时系统保持可运行（增量迁移，不一次性重写）。
> 解耦红线：业务逻辑永远在模块层（modules/、server_modules/、engine/commands/、sessions/），集成代码（server.py、listener、dispatcher 骨架）只做编排。

### 8.1 总览

| 阶段 | 任务 | 内容 | 依赖 | 阶段验收 |
|------|------|------|------|----------|
| P0 | T0.1 | 测试基座 | — | pytest 可运行 |
| P1 | T1.1-T1.6 | core 层改造（base64/常量/config/events/log） | P0 | build 生成的 implant 可连 server |
| P2 | T2.1-T2.6 | 模块系统 v2 | P1 | modules 正常，sysinfo 回填 |
| P3 | T3.1-T3.4 | 命令引擎 | P2 | 命令行为与旧版一致 |
| P4 | T4.1-T4.8 | 会话/网络/headless | P3 | 双端口双 key 跑通，事件流 |
| P5 | T5.1-T5.3 | Client 端 | P4 | client 远程操作可用 |
| P6 | T6.1-T6.3 + T6.1b | 构建/密钥模块与 implant | P4 | 新 implant 部署回连，keygen 写回 config |
| P7 | T7.1-T7.6 | UpLevel | P6 | 升级+回退端到端通过 |
| P8 | T8.1-T8.3 | 收尾 | 全部 | 全新 clone 可用 |

> 关键路径：P0 → P1 → P2 → P3 → P4 → P6 → P7；P5 与 P6 可并行。
> 测试分层：单元（纯函数）→ 集成（真 socket 回环）→ 端到端（build + uplevel）。

### 8.2 详细任务队列

#### 阶段 P0：测试基座

**T0.1 测试骨架**
- 目标：建立 tests/ 目录、pytest 配置与共享夹具。
- 文件：`tests/conftest.py`、`tests/__init__.py`、`pytest.ini`、`.gitignore`（补测试产物）。
- 实现要点：
  - conftest 提供：临时目录 fixture（配置/事件文件/日志）、本地空闲端口 fixture、假 beacon/client socket 辅助类（用 core.crypto 编解码帧）、Config 构造工厂；
  - 注明 pytest 为 dev-only 依赖（运行时仍零依赖，见 10.4）。
- 测试：`tests/test_smoke.py`（全包 import 不报错）。
- 验收：`python3 -m pytest tests/ -v` 通过。

#### 阶段 P1：core 层改造

**T1.1 crypto.py 编码改造（base85 → base64）**
- 目标：6.11 决策落地。
- 文件：`core/crypto.py`（encode/decode 改 b64）；**同步**：`build.py _encode_payload`、`implant/implant_template.py` 内联编码——否则 P1 后 build 出的 implant 连不上 server（保持阶段可运行）。
- 实现要点：直接切换（Q3 不兼容旧部署，测试锁定新行为）；保留 XOR+zlib 顺序不变。
- 测试：随机数据往返、空 key ValueError、损坏数据 ValueError、输出字符集断言（`A-Za-z0-9+/=` 子集）。
- 验收：单测通过；build.py 生成的 payload 为 base64。

**T1.2 protocol.py 消息常量 + 校验 + 错误码**
- 目标：P3 解决 + 10.4 错误码。
- 文件：`core/protocol.py`。
- 实现要点：消息类型常量（7.3 全表）+ 错误码常量（10.4 全表）+ `validate_message(msg) -> Optional[str]`（返回错误码）；`send_frame/recv_frame` 签名不变（帧传输与消息语义解耦）。
- 测试：validate_message 对各类型缺字段/未知 type/非法值的判定；错误码常量唯一性。
- 验收：单测通过。

**T1.3 config.py 分拆与校验**
- 目标：E4 解决 + 10.1 端口/密钥分离的配置面。
- 文件：`core/config.py`、`server/config.json`、`client/config.json`。
- 实现要点：
  - ServerConfig 字段：server_host/server_port/implant_key（沿用 xor_key 名或改名）/client_port（新，默认 9002）/client_key（新）/socket_timeout/modules_dir/event_file/log_file/max_frame_size/max_result_size/max_task_code_size（新）/max_tasks_per_client/max_results_per_beacon（新，默认 200）/max_connections（新，默认 256）/client_timeout/auto_commands；
  - ClientConfig 字段：server_host/client_port/client_key；
  - `validate()`：端口范围、大小上限正数、key 为 64 hex（空则告警）；
  - 未知 key 告警而非静默过滤；路径基于配置文件目录解析（不 chdir，E6 解决）。
- 测试：缺省值、未知 key 告警、validate 非法值、相对路径解析。
- 验收：单测通过；server/client 配置互相独立。

**T1.4 core/events.py 事件常量**
- 目标：10.3 事件类型集中。
- 文件：`core/events.py`（新增）。
- 实现要点：EVT_CONNECT / EVT_DISCONNECT / EVT_TASK_SENT / EVT_TASK_RESULT / EVT_UPLEVEL / EVT_AUTO_CMD_SENT / EVT_SERVER_START / EVT_SERVER_STOP 常量集。
- 测试：常量唯一性。
- 验收：单测通过。

**T1.5 core/log.py 统一日志**
- 目标：E2 解决。
- 文件：`core/log.py`（新增）。
- 实现要点：`setup_logging(level, file=None)`；格式 `[时间] [级别] [模块] 消息`；headless 时输出文件（10.1）；返回模块级 logger。
- 测试：stderr/文件输出、级别过滤。
- 验收：单测通过。

**T1.6 handler 字符串 → 常量（过渡改造）**
- 目标：P3 正式落地前先消除散落字符串（最小侵入，保持可运行）。
- 文件：`server/handler.py`。
- 实现要点：类型字符串换常量引用；register 容忍缺 version（视为 v1，过渡期——P6 的 implant 才带 version）。
- 测试：P0 冒烟 + 假 beacon 注册取任务不回归。
- 验收：server 可启动，假 beacon 可完成一周期任务。

#### 阶段 P2：模块系统 v2（行为变化最大之一）

**T2.1 server/module_meta.py 共享解析层（D4）**
- 目标：AST 解析统一。
- 文件：`server/module_meta.py`（新增）。
- 实现要点：`parse_meta(source) -> dict`（ast.literal_eval 解析顶层 MODULE，未知键告警）、`extract_code(source) -> str`（去 if __name__ 块）、`list_funcs(source) -> set[str]`（顶层 FunctionDef）；纯函数无 I/O。
- 测试：MODULE 合法/非法/缺省、未知键、嵌套 def 不影响、多函数提取。
- 验收：单测通过。

**T2.2 module_loader.py v2（D1）**
- 目标：模块格式 v2 落地。
- 文件：`server/module_loader.py`（重写解析/构建）。
- 实现要点：
  - 加载：module_meta 解析 MODULE（desc/params/result_processor）+ 函数清单；语法错误/MODULE 非法 → logging 告警并跳过（显式，不静默）；
  - `get_module` 返回结构化元数据（params 为 [(name, hint)]）；
  - `build_task(name, platform, **kwargs)`：平台选择 run_<plat> > run()，无实现显式 ValueError；params 校验（个数/未知参数）；生成代码 = 完整模块代码（去 __main__）+ 调用 + print(result)；代码长度 > max_task_code_size 拒绝；
  - JSON 序列模块：step 校验（模块存在且为 python 类型，嵌套 JSON 拒绝），加载时列出错误（M6 解决）。
- 测试：加载成功/失败显式化、平台选择矩阵（linux/windows/mac/未知/无平台）、params 校验、json 序列（合法/缺模块/嵌套）、大小上限。
- 验收：单测通过。

**T2.3 server_module_loader.py v2**
- 目标：元数据统一 + result_processor 一等公民（Q7）。
- 文件：`server/server_module_loader.py`。
- 实现要点：list/get 元数据改用 module_meta 读 MODULE；支持处理器形态 `run(output, error) -> dict`；返回字段白名单（sys_user/sys_os/sys_platform）回填，未知键告警丢弃；执行异常 logging。
- 测试：列表/获取、处理器调用、白名单回填、异常路径。
- 验收：单测通过。

**T2.4 植入模块改写 v2（11 个）**
- 目标：D1 全量落地。
- 文件：`server/modules/{ls,ps,netstat,exec,cat,kill,pwd,set_host,set_interval,set_key,break}.py`。
- 实现要点：
  - 元数据迁入 MODULE dict（desc/params 结构化）；
  - 变体改名：`*_all` → `run()`，`*_linux/_windows/_mac` → `run_linux/run_windows/run_mac`；无实现的平台不写函数（消灭 pass 占位）；
  - set_* 保持引用 `_H/_P/_I/_J/_K`（D2 短名契约）；
  - break 实现 `def run(): global _B; _B = True`（6.12）；
  - 保留 `if __name__` 自测块。
- 测试：逐模块 build_task 生成代码可 compile()；set_* 生成代码在模拟 exec 环境（预置 `_H/_P` 等）行为正确；break 置 `_B`。
- 验收：11 个模块全部加载无告警。

**T2.5 sysinfo.py + sysinfo_parse.py（Q7 落地样例）**
- 目标：S3 ③ sysinfo 硬编码剥离。
- 文件：`server/modules/sysinfo.py`（新增）、`server/server_modules/sysinfo_parse.py`（新增）。
- 实现要点：sysinfo 模块 MODULE 声明 `result_processor="sysinfo_parse"`；run() 输出 JSON（user/os）；处理器解析并返回 {sys_user, sys_os, sys_platform}（平台判定逻辑从 client_manager 迁入此处）。
- 测试：处理器正常/异常输出、平台判定矩阵（linux/windows/darwin）。
- 验收：单测通过。

**T2.6 删除旧解析代码**
- 目标：5.8 清理。
- 文件：module_loader.py（_parse_docstring/_is_pass_body 等）、console.py（_parse_param_names，P3 一并）、handler.py（_parse_module_params，P3 一并）。
- 实现要点：确认无引用后删除；grep 检查零残留。
- 测试：全量单测回归。
- 验收：grep docstring 解析逻辑零残留。

#### 阶段 P3：命令引擎

**T3.1 engine/dispatcher.py**
- 目标：命令入口收敛（补 9 项）。
- 文件：`server/engine/__init__.py`、`server/engine/dispatcher.py`（新增）。
- 实现要点：
  - 命令注册表 name → handler；模块命令动态注册（ModuleLoader 模块清单 → 统一入口 `_exec_module`）；
  - 统一参数映射（params 来自 MODULE dict，消灭两份解析，S3 ②）；
  - 依赖注入：dispatcher 持有 mgr/tq/logger/config/modules/smods 引用（可测）；
  - `execute(line) -> str` 兼容 console 与 Client 通道；
  - 任务构建统一入口 `build_task_for(client_id, name, args)`（auto_commands / 模块命令 / broadcast 共用，S3 ③）。
- 测试：注册/分发/未知命令/模块命令参数映射/上下文隔离。
- 验收：单测通过。

**T3.2 内置命令迁移 engine/commands/**
- 目标：console _cmd_* 全部注册化（每命令一模块）。
- 文件：`server/engine/commands/{beacon,use,show,modules,info,raw,broadcast,platform,result,sysinfo,log,reload,config,help,exit,server_modules,server_exec}.py`（新增）+ `commands/__init__.py`（自动扫描注册）。
- 实现要点：每个命令模块导出 `run(ctx, args) -> str`；sysinfo 命令改为走模块管线（删除内联代码）；行为与旧版逐条对齐。
- 测试：表驱动命令行为测试（假 mgr/tq）。
- 验收：命令输出与旧版一致（同一组命令新旧对比）。

**T3.3 console.py 瘦身**
- 目标：S2 解决（引擎/UI 分离）。
- 文件：`server/ui/console.py`（从 server/console.py 迁移改造）。
- 实现要点：console 只做读行（readline 历史/补全保留）、调 dispatcher.execute、打印输出；删除全部 _cmd_* 与模块构建逻辑；safe_print 保留给事件转发线程（T4.6）。
- 测试：输入输出转发冒烟。
- 验收：console 无任何业务逻辑。

**T3.4 auto_commands 走 dispatcher**
- 目标：S3 ①③ 收尾。
- 文件：`server/handler.py`（或 P4 的 BeaconSession）。
- 实现要点：首次上线自动命令 → 调 dispatcher.build_task_for 逐条构建下发；sysinfo 特殊分支删除（走 sysinfo 模块）。
- 测试：auto_commands=["sysinfo","set_interval 5"] 构建的任务代码正确。
- 验收：与旧行为一致。

#### 阶段 P4：会话/网络/headless（行为变化最大之二）

**T4.1 事件文件 EventWriter（Q6/10.3）**
- 目标：事件流基础设施。
- 文件：`server/infra/event_writer.py`（新增，替代 audit_logger）。
- 实现要点：JSONL 写入 + RotatingFileHandler（10MB×5）；`emit(event, beacon, **detail)`；线程安全；读端 `tail(n)` + 增量迭代（offset 游标）供转发线程/未来 API。
- 测试：写入格式、轮换触发、增量游标、并发写。
- 验收：单测通过。

**T4.2 双监听器 + max_connections（补1b/补5）**
- 目标：端口/密钥分离落地。
- 文件：`server/listener.py`（新增）。
- 实现要点：两个监听 socket（implant_port + client_port）各配密钥；统一 accept 循环；活跃连接计数 > max_connections 拒绝；**role 与端口绑定校验**（不匹配 → error + 断开）。
- 测试：双端口各自 accept、超限拒绝、跨端口 role 伪造被拒。
- 验收：集成测试通过。

**T4.3 BeaconSession（握手 + 任务循环）**
- 目标：handler 逻辑按角色下沉（S1）。
- 文件：`server/sessions/beacon.py`、`server/sessions/__init__.py`（新增）。
- 实现要点：握手（register version/role/via → welcome/error）；任务循环（pop → send → result → 存 results deque → result_processor 回填 → 事件 emit；空则 pong）；fire-and-forget 语义（10.2）；结果/上线不直接打印，只写事件（UI 无关）。
- 测试：握手矩阵（缺 version/不匹配/role 不符）、任务往返、结果处理器调用、事件 emit 断言。
- 验收：集成测试通过。

**T4.4 ClientSession（COMMAND/RESPONSE）**
- 目标：P2 协议统一（server 侧）。
- 文件：`server/sessions/client.py`（新增）。
- 实现要点：command → dispatcher.execute → response；未知 type → error；循环退出。
- 测试：命令往返、未知 type。
- 验收：集成测试通过。

**T4.5 headless + Server 生命周期（补1）**
- 目标：S2/S9 根治。
- 文件：`server/server.py`（重写装配与生命周期）。
- 实现要点：Server 自持 running/stop()/join；`--headless` 与交互两种启动模式；Ctrl-C → stop；console exit → server.stop()。
- 测试：headless 启动（无 TTY 起 server，事件文件生成）、优雅退出时序。
- 验收：headless 下可被假 client 操作。

**T4.6 事件转发线程（console 实时渲染）**
- 目标：Q6 的 UI 消费端。
- 文件：`server/ui/console.py`（转发线程）。
- 实现要点：后台线程 200ms 轮询事件文件增量 → safe_print 打断渲染；仅交互模式启动。
- 测试：写入事件 → 转发线程输出（capture stdout）。
- 验收：交互模式下新上线/结果实时可见。

**T4.7 清理旧集成代码**
- 目标：S4/S5/S6/S7/S8 收尾。
- 文件：删除 `server/handler.py`；`server/task_queue.py` deque 化；`client_manager.py` 快照接口 + results deque；删除 audit_logger（由 event_writer 替代）。
- 实现要点：确认 sessions 完全接管后删除；grep 无引用。
- 测试：全量回归。
- 验收：server/ 下无 handler.py；运行零旧引用。

**T4.8 集成测试套件（假 beacon/client）**
- 目标：网络层回归护栏。
- 文件：`tests/integration/test_server_beacon.py`、`test_server_client.py`、`test_headless.py`。
- 实现要点：本地回环起真 server（临时端口+配置）；假 beacon 用 core.protocol 帧交互；断言注册/任务/结果/事件文件。
- 测试：完整场景 + 异常场景（坏帧、超限、未知 type、断连）。
- 验收：全部通过。

#### 阶段 P5：Client 端

**T5.1 remote_client 统一 JSON 帧**
- 目标：P2 协议统一（client 侧）。
- 文件：`client/remote_client.py`。
- 实现要点：注册（role=client，client_key 加密，连 client_port）；COMMAND/RESPONSE 帧；send/send_line 合并（C3）；配置错误返回错误对象不退出进程（C4）；断线重连。
- 测试：对假 server 的命令往返、错误响应、重连。
- 验收：单测/集成通过。

**T5.2 client CLI**
- 目标：交互/单行模式 + 新配置。
- 文件：`client/client.py`、`client/config.json`。
- 实现要点：config 用 client_port/client_key；交互提示符；-c 单行。
- 测试：CLI 冒烟（subprocess）。
- 验收：client 可远程操作 server。

**T5.3 client 联调测试**
- 目标：端到端管理链路。
- 文件：`tests/integration/test_client_ops.py`。
- 实现要点：真 server + 假 client：beacon/use/show/raw/result 全流程。
- 验收：通过。

#### 阶段 P6：构建与 implant

**T6.1 构建功能模块化（server_modules/build.py，删除顶层 build.py）**
- 目标：构建业务并入 server 端模块（用户决策 2026-08-05），不再单独保留顶层脚本——与 proxy 生成器同一模式。
- 文件：删除顶层 `build.py`；新增 `server/server_modules/build.py`；新增 `core/bootstrap.py`（共享 bootstrap 生成）。
- 实现要点：
  - build 模块 `run(host, port, key_hex=None, interval=60, jitter=0.2, out_dir="server_modules/output")`：生成 implant_key（或复用参数 key）→ 渲染 implant_template → 经 core/bootstrap.py 生成 bootstrap → 写出 implant_command.txt + xor_key.hex → 返回 dict（部署命令 / key / 文件路径）；
  - **key_hex 未传时自动从 server/config.json 读取 implant_key**（模块文件上级目录约定：server_modules/ 的上级即 server/，config.json 位于其中）；config 缺失/无效 → 告警并提示先 `server_exec keygen` 或显式传 key；
  - 调用方式 `server_exec build <host> <port>`（与 proxy 生成器一致）；
  - `core/bootstrap.py` 收敛 _BOOTSTRAP 模板（修 %32 硬编码，base64，C1 解决；build 模块与 proxy 模块共用）；
  - 顶层 build.py 删除，`python3 build.py` 不再存在（Q3 不兼容旧部署）。
- 测试：roundtrip 解码回原代码、长度统计、key 参数化、**从 config.json 自动读取（有/无 key 两种路径）**、模块可被 server_module_loader 列出。
- 验收：`server_exec build 127.0.0.1 9001` 输出部署命令；生成的 implant 可部署（T6.3 验证）。

**T6.1b 密钥管理模块（server_modules/keygen.py）**
- 目标：随机生成密钥并自动填入 config.json（用户需求 2026-08-05）；build 自动读取由 T6.1 承接。
- 文件：`server/server_modules/keygen.py`（新增）。
- 实现要点：
  - `run(client_config=None)`：生成 **implant_key 与 client_key**（各 32 字节，64 hex，对应双端口分离，见 10.1）；
  - 自动写回 server/config.json（server 根目录约定）：缺失字段补入，**保留其余配置**；
  - `--client-config <path>`（可选参数）：同时把 client_key 写入 client 侧 config.json（操作员机器）；
  - 输出：两把 key 的 hex + 写回路径 + 提示（client_key 需同步到操作员机器）；
  - 与 server 启动兜底互补：config 缺 key 时 server 启动自动生成写回（_ensure_xor_key 正规化：写日志、不裸 except，见 10.1/T4.5）。
- 测试：key 格式（64 hex）、config.json 写回保留原字段、client config 写入、幂等（重复运行不破坏）。
- 验收：`server_exec keygen` 后 server/config.json（及指定 client/config.json）均为有效 key；随后 `server_exec build` 自动读到同一把 implant_key。

**T6.2 implant 模板重构（_T/_B 钩子）**
- 目标：U2/D2 落地 + 协议 v1。
- 文件：`implant/implant_template.py`。
- 实现要点：base64 编码；register 带 version/role=beacon；`_T` 传输钩子（默认 TcpXor 实现内联）；`_B` 退级标志（初始 False）；`_H/_P/_I/_J/_K` 短名契约；保持单行压缩风格；模块契约注释。
- 测试：模板渲染 → 解码 → compile()；沙箱 exec（假 socket）验证回连逻辑。
- 验收：生成的命令可部署。

**T6.3 构建 + 回连端到端测试**
- 目标：验证"生成即能用"。
- 文件：`tests/integration/test_build_deploy.py`。
- 实现要点：build.py 生成命令（host=127.0.0.1）→ subprocess 执行 → 真 server 收到注册 → 下发任务取回结果。
- 验收：端到端通过。

#### 阶段 P7：UpLevel（依赖 P6 的 implant 钩子）

**T7.1 传输抽象契约落地**
- 目标：U2 基座。
- 文件：`implant/implant_template.py`（_T 契约注释）、`server/server_modules/transport_base.py`（新增，生成器公共逻辑）。
- 实现要点：明确 `_T` 接口（一周期传输：connect/send/recv/close）；升级代码格式约定（覆盖 `_T/_H/_P/_K`）；**两阶段升级模板**（新通道探测成功才提交参数，失败保留旧参数并回传错误——U4）。
- 测试：升级模板在模拟 exec 环境中的两阶段行为（成功/失败分支）。
- 验收：单测通过。

**T7.2 transport_tls.py 生成器**
- 目标：U2/U3 首个落地。
- 文件：`server/server_modules/transport_tls.py`（新增）。
- 实现要点：生成 TLS 客户端传输代码（ssl + 证书指纹 pin）；自签证书/指纹生成辅助（同模块内或 tls_util）。
- 测试：生成代码 compile()；指纹 pin 逻辑（错指纹拒绝连接）。
- 验收：生成代码通过语法与行为测试。

**T7.3 proxy 生成器重做**
- 目标：6.5。
- 文件：`server/server_modules/proxy.py`（重写）。
- 实现要点：参数扩展（protocol、双 key）；多协议模板拼接（implant 侧 <protocol> 服务端 + server 侧 TcpXor 客户端 + 转发循环）；证书+指纹输出；bootstrap 用 core/bootstrap.py（C1 收尾）。
- 测试：生成 proxy 代码 compile()；假 implant 连 proxy → proxy 连真 server → 任务结果往返（集成）；via 字段与身份延续（U1）。
- 验收：端到端通过。

**T7.4 uplevel 命令**
- 目标：6.4。
- 文件：`server/engine/commands/uplevel.py`（新增）。
- 实现要点：`uplevel <beacon_id> <protocol> <host> <port>`；查 transport 生成器组装升级任务（`_H/_P/_K/_T` + 两阶段模板）；审计事件 EVT_UPLEVEL。
- 测试：命令构建的升级任务代码正确性；未知协议报错。
- 验收：单测通过。

**T7.5 break 模块实现（6.12）**
- 目标：D3 落地。
- 文件：`server/modules/break.py`（v2 改写，T2.4 已含格式，此处补行为测试）。
- 实现要点：`def run(): global _B; _B = True`；配合交互模式/长连会话。
- 测试：exec 后 `_B` 置位。
- 验收：单测通过。

**T7.6 UpLevel 端到端测试（含回退）**
- 目标：U1/U4 验收。
- 文件：`tests/integration/test_uplevel.py`。
- 实现要点：真 server + 真 implant（P6 产物）→ uplevel 到本地 proxy（tls）→ 身份延续（同 ID/队列）→ break 退级；失败场景：proxy 未启动 → 升级回退旧通道（implant 继续旧连）。
- 验收：升级成功链路 + 失败回退链路均通过。

#### 阶段 P8：收尾

**T8.1 README 重写**
- 内容：新架构图；双端口/双 key 配置说明；模块 v2 开发文档（`_H/_P/_I/_J/_K` 契约、MODULE dict、result_processor 契约）；uplevel 使用文档；headless 部署；信任模型（10.4）。
- 验收：文档与实际行为一致。

**T8.2 清理与产物策略**
- 内容：删除 server/server_modules/output/、c2_audit_history.log 等提交产物；新增 .gitignore（事件文件/日志/构建输出）；确认运行产物输出目录约定。
- 验收：git status 干净。

**T8.3 全量回归 + 设计核对**
- 内容：全部测试运行；对照第 9 章决策表逐条核对实现；更新文档状态。
- 验收：测试全绿，决策表无遗漏。

### 8.3 迁移要点

- **每阶段保持可运行**：P1 必须同步 build.py 与 implant 的 base64（否则 build 出的 implant 连不上 P1 后的 server）；P4 之前 handler 保留（P3 完成后由 sessions 接管再删）。
- **依赖顺序关键路径**：P0 → P1 → P2 → P3 → P4 → P6 → P7；P5 与 P6 可并行。
- **测试贯穿**：单元（纯函数，无 I/O）→ 集成（真 socket 回环）→ 端到端（build + uplevel）。
- **每个任务完成 = 代码 + 测试 + 验收三项齐**，未达验收不进入下一任务。
- 行为变化最大的两个阶段（P2 模块格式、P4 会话/事件流）重点回归。

### 8.4 风险

- 模块 v2 改写量大（11 个文件），但多为机械转换（变体改名 + 元数据迁移）。
- 事件文件轮询实时性：console 后台转发线程 200ms 轮询，可接受。
- 半双工传输（HTTPS/DNS）的 task 语义验证依赖 P7 集成测试；v1 仅落地 TLS。
- 双端口分离后，既有防火墙规则需要同步调整（部署侧）。

---

## 9. 决策记录汇总

| # | 决策 | 结论 |
|---|------|------|
| Q1 | 重构优先级 | 优先解耦 |
| 原则 | 模块化边界 | server 端能写成模块的业务一律不留集成代码 |
| Q2 | 零依赖 | 保持纯 stdlib |
| Q3 | 兼容性 | 不强制兼容旧部署 |
| Q5 | 测试 | 补全测试套件为验收标准 |
| Q6 | 会话事件 | 文件事件流（JSONL，文件=事件总线=审计） |
| Q7 | 元数据回填 | 模块声明 result_processor 标记，处理器为 server 端模块 |
| D1 | 模块格式 v2 | MODULE dict + AST 解析 + 可选平台入口，已确认 |
| D2 | 全局变量 | 保持 `_H/_P/_I/_J/_K` 短名，极致缩小载荷 |
| D3 | break | 保留为退级信号（增强会话退出） |
| D4 | 共享解析层 | server/module_meta.py，已确认 |
| U1 | 身份延续 | register 带 via 字段 + 原 ID 复用 |
| U2 | 协议实现 | 按需下发（transport_* 生成器模块） |
| U3 | TLS | 自签证书 + 指纹 pin |
| U4 | 升级回退 | 两阶段切换，失败保留旧参数 |
| 编码 | base85→base64 | 全部载荷统一 base64 |
| 补1 | headless | Server 自持生命周期，--headless 支持无 TTY 部署 |
| 补1b | 端口/密钥分离 | client 与 implant 不同端口（9002/9001）、不同密钥，role 与端口绑定校验 |
| 补2 | 任务执行 | 不追踪状态，fire-and-forget，重复执行风险接受 |
| 补3 | 日志审计 | 运行日志与事件文件分离，事件文件 10MB×5 轮换 |
| 补4 | 信任模型 | 密钥即认证；exec 是设计功能；错误码集中定义 |
| 补5 | 线程模型 | 五类线程 + max_connections + 超时 + 优雅退出 |
| 构建入口 | build 模块化 | build.py 并入 server_modules/build.py，删除顶层脚本 |
| 密钥管理 | keygen 模块 | 随机生成 implant_key/client_key 自动写 config.json；build 自动读取 |

---

## 10. 补充设计（2026-08-05，用户确认补 1-5）

### 10.1 Server 生命周期与 headless 模式（解决 S2/S9 根治）

现状问题：console 是主线程也是整个进程的生命中枢（S2/S9），无 TTY 环境无法运行，无法 systemd/docker 部署。

**端口与密钥分离（用户追加约束 2026-08-05）：**

- 现状：server 单端口同时服务 client 与 beacon，共用一把 xor_key——操作员通道和植入物通道混在一起。
- 新设计：**双监听器 + 双密钥**，两条通道完全隔离：
  - **implant 端口**（默认 9001，配置 server_port）：只接受 `role=beacon` 的连接，用 **implant_key**（即现状 xor_key）；
  - **client 端口**（默认 9002，新增配置 client_port）：只接受 `role=client` 的连接，用 **client_key**（新增配置 client_key）。
- **role 与端口绑定校验**：role 与端口不匹配 → error + 断开。拿到 client_key 也无法在 implant 端口注册 beacon，反之亦然。
- 好处：
  - **权限隔离**：泄露一把 key 只影响一条通道，不会一锅端；
  - **防火墙友好**：client 端口可只对操作员网段开放，implant 端口保持对公网；
  - proxy 属于 implant 通道，走 implant 端口 + implant_key，不变。
- 配置：server 配置新增 `client_port` / `client_key`；client/config.json 用 client_key；build.py 生成的 implant 用 implant_key。

设计：

- **Server 对象自持生命周期**：`running` 标志与 `stop()` 属于 Server，console 只是可选 UI 前端。
- **两种启动模式**：
  - 交互模式（默认，有 TTY）：启动 console；
  - **headless 模式**：`python3 server.py --headless`——不启动 console，事件照常写事件文件，运行日志输出到文件；操作员用 Client 远程操作（Q6 文件事件流的红利：UI 无关）。
- **生命周期规则**：listener / 清理线程 / 会话线程全部以 `server.running` 为信号；`stop()` 置位 + 关闭监听 socket + join(timeout=5) 收尾。
- console 的 exit 命令 → 调用 `server.stop()`（不再反向读取 console 私有字段）。
- Ctrl-C 优雅退出（KeyboardInterrupt → stop）。

验收：无 TTY 下 `--headless` 可启动、可被 Client 操作、Ctrl-C 优雅退出。

### 10.2 任务执行：不追踪状态（用户决策 2026-08-05，原设计否决）

用户拍板：**不需要任务状态机/去重，有回复就收，没回复就撒手不管**。

维持现状语义：

- 任务入队 → 连接期间逐个下发 → **收到 result 就存入 ClientRecord.results，没收到就拉倒**——不重发、不追踪 queued/sent/done。
- 连接中断时未发完的任务保留在队列（推回队头），下次回连继续发。
- **重复执行风险接受**：结果丢失后 server 可能重发同一任务，implant 可能重复执行；操作员对命令的幂等性负责。
- 仅保留两处实现级改进（内存保护/性能，与状态追踪无关）：
  - `ClientRecord.results` 用 `deque(maxlen=config.max_results_per_beacon)`（默认 200），防无限增长（S6）；
  - `TaskQueue` 用 `collections.deque` 替换 `list.pop(0)`（S7 性能）。

### 10.3 日志与审计分离 + 事件文件轮换（解决 E2/E5）

现状问题：print 满天飞；事件文件=审计但无排障日志；审计每行 open 无缓冲；事件文件无限增长。

设计：

- **两类输出，职责分离**：
  - **运行日志**（core/log.py，logging 封装）：排障用——连接建立/关闭、帧错误、模块加载失败、异常 traceback。级别 DEBUG/INFO/WARNING/ERROR；交互模式输出 stderr，headless 输出文件；格式 `[时间] [级别] [模块] 消息`。
  - **事件文件**（审计 + 多 UI 总线）：业务事件——上线/断开/任务下发/结果/升级。JSONL 一行一事件：`{"ts":..., "event":..., "beacon":..., "detail":...}`。
- **事件文件轮换**：`RotatingFileHandler`（10MB × 5 份，stdlib 自带，线程安全锁内置），解决无限增长。
- **事件类型常量**：core/events.py 集中定义（`EVT_CONNECT / EVT_DISCONNECT / EVT_TASK_SENT / EVT_TASK_RESULT / EVT_UPLEVEL / EVT_SERVER_START / EVT_SERVER_STOP ...`），消灭散落字符串。
- audit_logger 重写为事件文件的写入端（RotatingFileHandler + 锁），删除每行 open 的实现。

### 10.4 信任模型与错误码（大白话版，用户要求详细化）

**信任模型——这个系统相信谁、凭什么信：**

1. **密钥就是门禁卡。** 这个系统没有账号、没有密码，唯一的分辨方式就是你知不知道那把密钥。数据用密钥加密过、对方能正确解出来，服务器就默认他是自己人。所以：**密钥一定要收好，谁拿到密钥谁就能控制整个系统**（能向所有 beacon 下发任意代码）。这把钥匙丢了，等于整个系统交出去了，只能换 key 重新部署。
2. **下发代码 = 让目标机执行你的代码。** beacon 收到 Python 代码就用 exec 跑起来，这是这个工具的核心功能，不是漏洞。操作员对自己下发的代码负责——代码有 bug 或发错了，后果在目标机上，责任在发的人。
3. **server 端模块也是自己人。** server_modules/ 里的 .py 文件会被服务器动态加载并直接运行，里面写什么就执行什么。所以：**不要放不信任的文件进去**，放了个坏的模块，服务器可能直接崩掉。
4. **混淆 ≠ 加密。** XOR 这层只是把流量搅乱，让抓包的人看不出是 C2 通信，它不是真正的加密。密钥一旦泄露，所有通信等于明文。想要真正安全的通道，用 uplevel 升级到 TLS。

**错误码——出错时说清楚原因，而不是悄悄挂断：**

现在的行为：通信一出问题，服务器"啪"地断开连接，什么都不说。改版后：先回一条 error 消息说明原因，再断开。原因用一个固定的错误码表示，调试时一眼看懂：

| 错误码 | 大白话含义 |
|--------|-----------|
| VERSION_MISMATCH | 版本对不上：连进来的客户端/植入物用的协议版本和服务器不一样（多半是没重新 build） |
| BAD_FRAME | 数据包坏了：长度头不对、超过 512KB 上限、解不出来 |
| BAD_JSON | 内容不是合法的 JSON，没法解析 |
| UNKNOWN_TYPE | 消息类型不认识：不是 register/task/result/pong 这些约定好的类型 |
| INTERNAL | 服务器自己内部出错了（运行日志里会有详细 traceback） |

消息格式：`{"type":"error","code":"BAD_FRAME","message":"frame size 999999 exceeds maximum 524288"}`，发完就断。`validate_message()` 校验失败时返回错误码而不是自由文本，保证双方用同一套"暗号"（VERSION_MISMATCH / BAD_FRAME / BAD_JSON / UNKNOWN_TYPE / INTERNAL 定义在 core/protocol.py，AUTH_FAILED 预留）。

### 10.5 线程模型与资源上限（大白话版，用户要求详细化）

**线程模型——服务器像一家店，一个前台加一群工人：**

| 线程 | 角色 | 干什么的 | 什么时候下班 |
|------|------|----------|--------------|
| 主线程 | 前台/店长 | 启动服务器；交互模式等你敲命令；headless 模式只盯着服务器运行 | 你按 Ctrl-C |
| 监听线程 | 门卫 | 盯着端口，有人来连接就接进来，交给工人（**两个端口两个门卫**：implant 端口 + client 端口） | 服务器关停 |
| 会话线程 | 工人 | 一对一服务：beacon 来取任务就陪它发任务等结果；client 来下命令就陪它跑命令。**每个连接一个工人** | 服务器关停 + 连接断开 |
| 清理线程 | 保洁 | 每隔 60 秒查一遍，很久没回连的 beacon 从列表移除 | 服务器关停 |
| 事件转发线程 | 广播员 | 盯着事件文件，有新上线/新结果立刻打到屏幕（只有交互模式才需要） | 服务器关停 |

工人是"按连接分配"的：连接多，工人就多。所以要有下面的人数上限，防止被拖垮。

**资源上限——防呆措施：**

- **最大连接数（max_connections，默认 256）**：同时最多接 256 条连接。有人恶意或者程序出 bug 狂开连接，超过上限的新连接直接拒绝（关掉），服务器不会被打垮。
- **连接超时（socket_timeout，默认 30 秒）**：每条连接上收数据、发数据都有时间限制。对端半天不吭声（比如断网了、卡住了），服务器放弃这条连接，不占着资源不放。读和写都管。
- **结果大小上限（max_result_size，默认 1MB）**：beacon 回传结果太大就截断，防止一个大结果把内存撑爆。
- **任务代码上限（max_task_code_size）**：下发的代码太长直接拒绝（防止手滑或者被利用）。
- **优雅退出**：按 Ctrl-C 时服务器按顺序收摊：先通知大家"下班了"（running=False）→ 关掉大门（监听 socket，不再接新连接）→ 每个工人把手头的活儿干完（最多等 5 秒）→ 真正退出。不会出现关到一半丢数据或卡死。
