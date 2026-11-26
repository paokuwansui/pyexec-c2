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

安装 Python 依赖：

```bash
python3 -m pip install -e '.[dev]'
```

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
- 新 Beacon 之间按最近心跳时间排序，最近上线的优先。
- 拖动 Beacon 并保存后，会保留人工设置的显示顺序。
- 后续新上线的 Beacon 仍会优先显示在顶部，直到被手工加入排序。

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
