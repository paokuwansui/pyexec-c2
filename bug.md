# pyexec-c2 bug.md（审计记录）

> 记录既有问题（含未修复项）。修复项标记 [已修复]，未修复项标记 [待修]。

## 本轮修复（2026-08-13，回归测试见 tests/test_bugfix_round3.py）

- **[已修复] B1 find 无匹配 NameError** — `server/modules/find.py:49` 错误信息引用已改名参数 `{name}`（实为 `keyword`），无匹配时抛 `NameError`。改为 `{keyword}`。
- **[已修复] B2 portfwd 单次失败杀监听** — `server/engine/commands/portfwd.py` 的 `_loop` 中 `except ValueError: conn.close(); return` 会退出整个 accept 循环，一次队列满/构建失败后转发器永久失效。改 `return` → `continue`。
- **[已修复] B3 DNS 分片重组越界序号 KeyError** — `server/infra/dns_listener.py` 收齐判定只用 `len(cache[1]) < total` 数键，越界 seq（≥total 或负数）会撑高计数误判收齐 → `range(total)` 访问缺键抛 KeyError 被裸 except 吞掉 + cache 条目泄漏。新增 `total <= 0 or total > _MAX_FRAGMENTS or not (0 <= seq < total)` 前置校验。
- **[已修复] B4 DNS 大响应 4KB 截断** — 响应帧 base32 分片全部塞进单个 UDP 报文，beacon 端 `recv(4096)` 只读 4096 字节，>~3KB 帧（shell 模块/upload 数据块）被静默截断。新增响应分片拉取协议：server 端超 `_RESP_SPLIT_LIMIT` 片时缓存分片并回 `s<total>` 标记，beacon 端（transport_dns 生成器 `_resolve`）用 `r<idx>.<bid>.<domain>` 逐片拉取重组。

## 未修复项（记录）

- **[已修复] 5 relay 模块不发心跳** — `server/modules/relay.py` 内联心跳 `_relay_hb_start/_relay_hb_stop`（独立变量名避免与 exec 的 `_hb_go/_hb_stop_ev` 冲突），`run()` 连 relay 成功后启动、`finally` 停止。回归测试见 tests/test_relay_heartbeat.py。
- **[已修复] 6 portfwd 死代码 + 重复调用泄漏** — 新增 `portfwd stop` 命令；`run()` 重复调用先 `_stop_portfwd` 停旧的（置 stopped + 关 socket + join 线程），不再泄漏监听线程/socket。回归测试见 tests/test_bugfix_remaining.py。
- **[已修复] 7 _ensure_implant_key 不回写内存配置** — `server/server.py` 生成 key 写回 config.json 后同步 `config.implant_key = key.hex()`，内存与磁盘一致。回归测试见 tests/test_bugfix_remaining.py。
- **[已修复] 8 HTTPS/DNS 注册丢失 via/fork/shell 元数据** — 统一 beacon 周期引擎（`server/sessions/engine.py` 的 `register_beacon`），TCP/HTTPS/DNS 三传输共用，via/fork/shell 全通道生效。回归测试见 tests/test_engine_shared.py。
- **[已修复] 9 broadcast 丢 proc_arg** — `engine/commands/broadcast.py` 重建 Task 时补 `proc_arg=task.proc_arg`，download 落盘等处理器在 broadcast 下生效。回归测试见 tests/test_bugfix_remaining.py。

## 设计观察（已处理 / 供参考）

- **[已更新] 加密现状** — 通信层已升级 ChaCha20+HMAC（encrypt-then-MAC，随机 nonce），非 XOR 混淆；仅 bootstrap 外层仍为 1 字节 XOR（静态免杀靠外层套壳）。勿把 bootstrap XOR 当加密对外宣传。
- **[已修复] relay/socks5 默认绑回环** — 原绑 `server_host`（默认 0.0.0.0）= 公网开无认证 SOCKS5/中继。现新增 `relay_host` 配置项（默认 127.0.0.1），relay/socks5 只监听回环，需远程访问时显式改。回归测试见 tests/test_bugfix_remaining.py::test_relay_host_defaults_loopback。
- **[已覆盖] JSON 序列模块路径** — `module_loader._build_json_task` 已有测试覆盖（tests/test_module_loader.py 的 test_json_sequence_ok / test_json_missing_module_reported / test_json_nested_rejected），仓库虽无实际 .json 模块但路径受测。
