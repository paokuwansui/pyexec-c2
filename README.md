# pyexec2

pyexec2 是一个插件优先、文件存储驱动的 Python C2 / 远程 Python 执行平台，仅用于授权的安全测试和实验环境。

## 项目结构

- `server_core/`：控制面、文件存储、Action 注册、任务引擎、监听器和代理网关。
- `transport_plugins/`：UDP、TCP、HTTP、HTTPS、DNS 传输插件。
- `implant_plugins/`：下发到 Beacon 的 Python 能力插件。
- `server_plugins/`：服务端本地扩展。
- `clients/web/`：React 操作端。
- `clients/web_backend.py`：只在本机运行的 Web 后端，浏览器不直接接触服务端 Token。
- `clients/ai/`：AI Worker / AI Approval 命令行客户端及配置示例。
- `clients/default_redteam_notes/`：项目内置的初始红队笔记。
- `tests/`：Python 测试套件。

## 环境要求

- Python 3.12+
- Node.js 18+ 与 npm
- OpenSSL，用于生成本地开发 TLS 证书

安装 Python 依赖。Kali / Debian 的系统 Python 通常启用了 PEP 668，不要直接往系统环境安装，建议使用虚拟环境：

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e '.[dev]'
```

如果出现“Multiple top-level packages discovered”或“externally-managed-environment”，请确认是在项目根目录执行上述命令，并使用 `.venv` 虚拟环境。

安装并构建 Web 客户端：

```bash
cd clients/web
npm install
npm run build
cd ../..
```

## 首次启动

### 1. 生成本地开发证书

HTTPS 监听器和 HTTPS Payload 需要本地证书：

```bash
bash scripts/gen_dev_cert.sh
```

该证书和私钥只用于本地开发和测试，不能作为生产证书使用。

### 2. 启动控制 API

```bash
python3 run.py --host 0.0.0.0 --port 18080
```

首次启动时，服务端会生成并打印：

- Human Token
- AI Worker Token
- AI Approval Token

请妥善保存这些 Token。浏览器 UI 不会从本地后端获得服务端 Token。

### 3. 配置本地 Web 客户端

复制示例配置：

```bash
cp config/web.json.example config/web.json
```

编辑 `config/web.json`：

```json
{
  "server": "http://127.0.0.1:18080",
  "token": "PASTE_HUMAN_TOKEN_HERE"
}
```

启动本地 Web 后端：

```bash
python3 clients/web_backend.py --config config/web.json --host 127.0.0.1 --port 8765
```

浏览器打开：

```text
http://127.0.0.1:8765/
```

## Beacon 列表

- 新发现、未进入手工排序的 Beacon 默认显示在列表最上方。
- 新 Beacon 之间按首次发现时间 `first_seen` 排序，最新发现的优先。
- 心跳只更新最后心跳时间，不会改变未手工排序 Beacon 的上下位置。
- 避免新上线机器在心跳过程中上下跳动。
- 在线和离线 Beacon 都可以拖动排序。
- 拖动 Beacon 并保存后，会保留人工设置的显示顺序。
- 后续新上线的 Beacon 仍会优先显示在顶部，直到被手工加入排序。
- Beacon 列表显示用户名、平台、协议、心跳间隔、状态和距离最后心跳的相对时间。
- 收纳区同样显示用户名和距离最后心跳的相对时间。

## AI 配置

本地 AI 配置保存在：

```text
clients/local_data/ai_agent/
```

配置文件使用 Fernet 加密保存，不应提交到仓库。

AI Worker 和 AI Approval 客户端配置示例：

```bash
cp clients/ai/config.json.example clients/ai/config.json
cp clients/ai/approval_config.json.example clients/ai/approval_config.json
```

然后填入服务端生成的 AI Worker Token 和 AI Approval Token。

默认 AI 配置：

```text
Base URL: https://api.deepseek.com
Model: deepseek-flash
Thinking: max
API 格式: OpenAI-compatible
```

支持：

- OpenAI Chat Completions 兼容格式
- Anthropic Claude Messages 格式

## 并行命令任务

命令终端支持连续下发多个任务，不需要等待前一个任务完成：

- 每次发送都会创建独立任务条目
- 每个任务单独显示下发、排队、Beacon 获取、执行中、完成或失败状态
- 后台分别轮询每个任务，不会阻塞下一次输入
- 每个任务的输出只更新到自己的终端条目
- 先完成的任务不会把结果写到后一个任务下面
- 后完成的任务结果仍显示在自己的条目中
- 输入区提示当前并行执行中的任务数量

## UDP 可靠传输

UDP 传输已增加应用层可靠机制：

- 请求逻辑超时 1.5 秒，UDP 最多快速尝试 3 次
- 每次重试使用新的加密 nonce，但保持同一个 request_id
- 服务端按 `session/token + request_id` 缓存响应，重试不会重复领取任务
- 任务采用 8 秒租约，Beacon 通过 `task_ack` 确认收取
- 未确认任务在租约到期后自动重新投递
- Beacon 按 task_id 去重，重复投递不会重复执行
- 结果保留到收到 `ack_results` 后才删除
- UDP 消息按 700 字节分片，单数据报不超过 1200 字节
- 每个分片带 CRC32，整条消息带 SHA-256 校验
- 分片丢失时可整体重试；服务端缓存响应可以重复返回
- `client_pub` 只存在于完整逻辑请求中，不会在每个分片重复携带

协议升级：

- TCP → UDP 升级已验证
- 支持升级时同时轮换 Token 和 32 字节密钥
- 升级后的新 UDP 请求可以正常分片、重试、任务 ACK 和结果回传
- `protocol.upgrade` Action 会转发 `url`、`token`、`key` 字段

## 命令终端滚动

命令终端默认跟随最新输出：

- 正常情况下始终滚动到最下方。
- 新命令或新输出出现时自动滚动到底部。
- 用户主动向上滚动查看历史后，停止自动跟随。
- 向上滚动查看历史时切换界面再返回，会保留原来的滚动位置。
- 用户手动滚回底部后，自动跟随恢复。
- 终端使用 MutationObserver 监听输出内容变化，避免异步任务结果追加后停留在旧位置。

## Linux 进程伪装

新增 Linux 植入端插件 `lmasquerade`，终端可直接输入基础命令：

```text
masquerade systemd
```

也可以指定任意名称：

```text
masquerade my-daemon
```

执行内容：

- 使用 `prctl(PR_SET_NAME)` 修改当前 Beacon 进程的 Linux comm 名称
- 尽力修改 glibc 的 `__progname`、`program_invocation_short_name` 和 `program_invocation_name`
- 返回实际应用名称和是否因为 15 字节限制被截断
- 不修改磁盘文件，不影响 Beacon 的其他功能

Linux 的进程 comm 名称最多 15 字节，超过部分会被截断。

## Linux 目录列表

Linux 的 `ls` / `file.list` 会显示文件和目录的：

- 权限
- 所属用户和用户组，使用 `owner:group` 格式
- 大小，右对齐
- 修改时间
- 名称

所属用户和用户组通过 UID/GID 解析为名称，解析不到时回退显示数字 ID。终端 `ls` 输出使用 `用户:用户组`，仅文件大小列保持右对齐。文件浏览页面仍单独显示“用户”和“用户组”两列。

### 文件浏览器列宽

文件浏览器左侧目录已压缩为紧凑列：

```text
类型 | 权限 | 用户 | 用户组 | 名称 | 大小 | 修改时间
```

列间距缩减为 3px，用户/用户组/大小/时间使用紧凑宽度，名称列自动占满剩余空间。文件名不会再被挤成 0 宽度，目录面板也不会出现横向溢出。

## 文件上传

Beacon 文件编辑界面的上传功能使用分块方式写入目标文件：

- 每块约 8 KB
- 第一块使用 `start` 模式创建文件
- 后续块使用 `append` 模式追加
- 每个分块任务完成后才发送下一块
- 任一分块超时或失败会立即中止上传并显示真实错误
- 上传完成后显示目标路径和文件大小，并刷新目录列表

上传功能使用浏览器 FileReader 读取本地文件，再通过 `file.upload_chunk` 下发，不需要浏览器直接访问目标文件系统。

### 删除远程文件

只有左侧文件浏览器工具栏提供“删除”按钮；文件编辑工具栏不重复放置删除入口。

删除流程：

1. 先在左侧文件列表选择文件
2. 点击“删除”
3. 在确认弹窗中核对目标路径
4. 点击“确认删除”
5. 等待 Beacon 执行 `rm` 任务
6. 删除成功后刷新当前目录并清空文件预览

操作不可恢复，未选择文件时删除按钮保持禁用。

### 新建远程文件

文件浏览器还提供“＋ 新建文件”按钮。

新建文件时可以填写：

- 目标目录或路径
- 文件名
- 文件内容

创建时会使用 `file.write` 下发写文件任务，目标父目录不存在时会由植入端自动创建。创建完成后会刷新目录并打开新文件预览。同名文件会被覆盖。

## Python 本地模板

在 Beacon 的 Python 脚本面板中可以填写模板名称并保存为本地模板。

- 模板名称支持中文、英文、数字、空格和常用符号。
- 名称会原样保留，例如“更改进程名”不会被改写成随机字符串。
- 仅替换路径分隔符、控制字符和系统保留字符，防止路径穿越。
- 模板保存在 `clients/local_data/templates/`，不会提交到仓库。
- 选择模板后会同时恢复模板名称和脚本内容。

## AI 记忆机制

AI 记忆保存在：

```text
clients/local_data/ai_agent/memory.json
```

记忆来源包括：

- 人类操作员通过“查看记忆”管理器新增或编辑
- AI 通过 `remember` 工具写入
- 两种来源写入同一个记忆文件

AI 读取规则：

- 每次发起新的对话或 AI 运行请求时，都会重新读取 `memory.json`
- 读取到的记忆会写入 AI 系统提示词
- AI 运行过程中如果检测到记忆文件发生变化，会在下一次模型调用前追加最新记忆
- 会话重置不会删除记忆
- AI 配置回退不会删除记忆
- 删除记忆必须通过“查看记忆”管理器手动删除

## AI 教程动态上下文

AI 教程页面顶部新增“动态上下文”区域。

客户端能自动获取的字段：

- 服务端控制 API
- 服务端协议 / 主机 / 端口
- 本地 Web 客户端地址
- 项目目录
- AI 客户端路径
- Human Token
- AI Worker Token（客户端可读取时）
- AI Approval Token（客户端可读取时）

如果客户端无法获取某个值，可以直接在输入框中手动填写：

- 服务端控制 API
- 本地 Web 客户端
- 项目目录
- AI 客户端路径
- Human Token
- AI Worker Token
- AI Approval Token

手动填写的值会保存在本机浏览器中，并立即重新渲染 AI 教程；不会提交到服务端。

教程默认使用 Markdown 渲染，也可以点击“显示原文”查看纯文本。编辑教程时仍只显示占位符，保存后自动替换为当前动态值。

## AI 对话重置

AI 模式页面右上角提供“重新开始对话”按钮。

点击后会：

- 停止当前 AI 运行
- 清空当前对话消息
- 清空排队消息
- 关闭待审批弹窗
- 清理当前执行轨迹
- 重新显示初始欢迎消息

该操作不会删除：

- AI 配置
- API Key
- 记忆管理中的长期记忆
- 红队笔记
- 服务端 Beacon 和任务数据

## 审批模型

- Human Token：完整人工权限，可绕过 Action 审批。
- AI Worker Token：受 `all_allow` 或 `per_action` 审批策略约束。
- AI Approval Token：可以审批或拒绝 AI 操作，但不能审批自己发起的操作。
- `per_action` 模式下，AI 写操作会进入审批队列。
- AI 工具调用被拦截时会暂停，人工放行后继续执行，并把真实结果返回给 AI。
- 人工拒绝时可以填写建议，建议会作为工具结果返回给 AI，AI 会据此重新规划。

## Payload 投递

载荷工坊提供三种投递方式，顺序固定：

1. 直接 Echo
2. 短 Python 下载器
3. Curl 下载执行

每种投递方式都有独立的“混淆模式”按钮：

- 打开直接 Echo 的混淆模式，只改变直接 Echo 命令。
- 打开短 Python 下载器的混淆模式，只改变短下载器命令。
- 打开 Curl 的混淆模式，只改变 Curl 命令。
- 三种投递方式互不影响，可以单独恢复原始命令。
- 普通载荷地址仍为 `/p/<token>`。
- 混淆载荷地址为 `/p/<token>?variant=obfuscated`。

混淆层包括：

- zlib 压缩
- 每次操作生成新的随机 XOR Key
- Base64 编码
- 随机变量名
- 模块名和 builtin 名称拆分

混淆模式用于降低静态字符串特征，不保证绕过任意杀毒软件、EDR、沙箱或流量检测设备。

## 内置红队笔记

当前备份保留了现有的 15 条红队笔记条目，并在首次启动时导入记事本。


项目首次启动时不需要预置记事本数据库。

本地 Web 后端会自动读取：

```text
clients/default_redteam_notes/
```

并把这些 Markdown 笔记导入“红队笔记”区域。

红队笔记是项目初始内容的一部分。默认笔记内容更新后，系统会通过内容指纹自动刷新内置笔记，同时保留用户自己的记事本和 AI Skill 开关设置。

## 测试

在项目根目录执行：

```bash
python3 -m pytest -q
```

如果 `config/server.crt` 和 `config/server.key` 不存在，测试夹具会自动生成临时开发证书。

## 仓库清理说明

公开仓库中不包含以下运行痕迹或敏感信息：

- 真实 Human / AI Worker / AI Approval Token
- API Key、代理密码和私钥
- 本地 `config/web.json`、`config/proxy.json`
- 服务端证书私钥和运行时数据
- Beacon、任务、审批、记忆、命令历史和记事本运行数据
- `data/`、`logs/`、`runtime/` 中的运行文件
- 本机用户名、主机名、真实 IP 和绝对项目路径
- `node_modules/`、前端构建产物、缓存和测试证据

首次使用时请根据 `*.example` 文件重新创建本地配置，或按启动步骤生成新 Token 和开发证书。

## 安全注意事项

- 不要提交真实 API Key、Token、私钥、运行数据、日志或操作历史。
- 配置示例中的值全部是占位符。
- `.gitignore` 已排除：
  - `config/web.json`
  - `config/proxy.json`
  - `clients/ai/config.json`
  - `clients/ai/approval_config.json`
  - `clients/local_data/`
  - `data/`
  - `runtime/`
  - `logs/`
- 部署或共享后建议立即轮换所有 Token。
- 仅对你明确获得授权的系统使用本项目。

## 常用目录

```text
server_core/                 控制面源码
transport_plugins/           传输协议插件
implant_plugins/             Beacon 能力插件
clients/web/                 React 前端源码
clients/web_backend.py       本地 Web 后端
clients/ai/                  AI 客户端与示例配置
clients/default_redteam_notes/ 初始红队笔记
tests/                       测试代码
config/                      示例配置
scripts/                     启动与证书生成脚本
```
