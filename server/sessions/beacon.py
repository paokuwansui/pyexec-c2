"""
server/sessions/beacon.py — Beacon 会话（T4.3）

流程: 握手（register/welcome，7.4）→ 注册 → auto_commands（首次上线）→
任务循环（pop → task → result → 存库 → 结果处理器回填 → 事件；空 → pong）
→ 断开。

fire-and-forget 语义（10.2）: 结果收到就存，没收到就拉倒；连接中断时
未发完的任务推回队头，下次回连继续。不追踪任务状态。

UI 无关（Q6）: 只写事件文件，不打印。
"""

import json

from server.core.protocol import (
    send_frame, recv_frame, validate_message, TASK, RESULT, PONG,
)
from server.core.events import (
    EVT_CONNECT, EVT_DISCONNECT, EVT_TASK_SENT, EVT_TASK_RESULT,
    EVT_AUTO_CMD_SENT,
)
from server.core.log import get_logger
from server.client_manager import TaskResult
from .base import handshake, send_welcome, send_error, SessionError

logger = get_logger("beacon_session")


class BeaconSession:
    """Beacon 连接会话。"""

    def __init__(self, sock, key: bytes, expected_role: str,
                 mgr, tq, events, config, modules, smods, dispatcher=None):
        self._sock = sock
        self._key = key
        self._expected_role = expected_role
        self._mgr = mgr
        self._tq = tq
        self._events = events
        self._config = config
        self._modules = modules
        self._smods = smods
        self._dispatcher = dispatcher  # 仅用于 auto_commands 构建任务
        self._client_id = ""           # 注册成功后填充（close 清 active 用）
        self._is_fork = False          # 注册时标记（跳过 auto_commands）

    def run(self) -> None:
        try:
            self._sock.settimeout(self._config.socket_timeout)
            reg = handshake(self._sock, self._key, self._expected_role,
                            self._config.max_frame_size)
            # 注册（含 via 标记）先于 welcome：welcome 语义 = 注册成功
            client_id, is_new = self._register(reg)
            self._client_id = client_id
            send_welcome(self._sock, self._key)
            self._task_cycle(client_id, is_new)
        except SessionError as e:
            logger.warning("handshake failed: %s", e.message)
            send_error(self._sock, self._key, e.code, e.message)
        except (ConnectionError, ValueError):
            logger.debug("beacon connection closed")
        except Exception:
            logger.exception("beacon session error")

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass
        # 会话结束：清活跃标记（cleanup 竞态防护，S9）
        rec = self._mgr.get_client(self._client_id)
        if rec:
            rec.active = False

    # ── 主流程 ──

    def _register(self, reg: dict) -> tuple:
        """注册 + via/fork/shell 标记 + 上线事件。"""
        client_id = reg["id"]
        via = reg.get("via", "")
        is_fork = bool(reg.get("fork", False))
        self._is_fork = is_fork
        # shell 标记直接赋值：shell 循环注册带 True，基础循环注册不带 → 自动复位
        is_shell = bool(reg.get("shell", False))
        client_id, is_new = self._mgr.register(client_id, is_client=False)
        rec = self._mgr.get_client(client_id)
        if rec:
            if via:
                rec.via = via
            if is_fork:
                rec.is_fork = True
            rec.is_shell = is_shell
            rec.active = True  # 当前会话活跃（cleanup 跳过）
        self._events.emit(EVT_CONNECT, client_id,
                          first=bool(is_new), via=via or None,
                          fork=is_fork or None, shell=is_shell or None)
        return client_id, is_new

    def _task_cycle(self, client_id: str, is_new: bool) -> None:
        # fork 分裂出的 beacon 跳过 auto_commands：auto 命令（如
        # set_interval 5）会改共享全局，干扰主 beacon（S9）
        if is_new and not self._is_fork:
            self._run_auto_commands(client_id)

        while True:
            task = self._tq.pop(client_id)
            if not task:
                break
            if not self._send_and_wait(client_id, task):
                self._tq.push_front(client_id, task)  # 断线保序重发
                break
            # shell 文本任务 exit/break 已确认执行：立即复位 is_shell，
            # 消除退出后到下次基础注册之间的误路由窗口（真机测试发现：
            # 窗口内 fork/exec 等模块命令会被当成 shell 文本直发）
            if task.code.strip() in ("exit", "break"):
                rec = self._mgr.get_client(client_id)
                if rec is not None:
                    rec.is_shell = False

        try:
            send_frame(self._sock,
                       json.dumps({"type": PONG}).encode("utf-8"), self._key)
        except Exception:
            pass
        self._events.emit(EVT_DISCONNECT, client_id)

    def _send_and_wait(self, client_id: str, task) -> bool:
        """发送 task → 接收 result → 存库/回填/事件。

        Returns: True 成功；False 连接中断（任务需重试）。
        """
        try:
            task_msg = json.dumps({
                "type": TASK, "task_id": task.task_id, "code": task.code,
            })
            send_frame(self._sock, task_msg.encode("utf-8"), self._key)
            self._events.emit(EVT_TASK_SENT, client_id,
                              task_id=task.task_id)

            # 长任务：等待结果期间把 socket 超时放宽到 client_timeout。
            # 此前用 socket_timeout（默认 15s），beacon 任务执行超过
            # 该值时 server 端 recv 超时 → 会话断开 → 结果丢失 +
            # push_front 重发（真机测试发现：exec sleep 45 必断）。
            old_timeout = self._sock.gettimeout()
            self._sock.settimeout(self._config.client_timeout)
            try:
                raw = recv_frame(self._sock, self._key,
                                 max_frame_size=self._config.max_frame_size)
            finally:
                self._sock.settimeout(old_timeout)
            result = json.loads(raw.decode("utf-8"))
            # S2：result 帧同样过 validate_message（S9 的类型校验此前
            # 只挂在 handshake 的 register 路径，从未执行）
            vcode = validate_message(result)
            if vcode:
                logger.warning("beacon %s sent invalid result: %s",
                               client_id[:8], vcode)
                return False
            if result.get("type") != RESULT:
                logger.warning("beacon %s sent non-result: %s",
                               client_id[:8], result.get("type"))
                return False

            output = result.get("output", "")
            error = result.get("error", "")
            max_size = self._config.max_result_size
            if len(output) > max_size:
                output = (output[:max_size] +
                          f"\n... (truncated, {len(output)} bytes total)")

            self._mgr.add_result(client_id, TaskResult(
                task_id=task.task_id, output=output, error=error,
            ))
            self._events.emit(EVT_TASK_RESULT, client_id,
                              task_id=task.task_id, output=output[:200])

            if task.result_processor:
                self._apply_result_processor(client_id, task, output, error)
            return True

        except (ConnectionError, ValueError, json.JSONDecodeError):
            return False

    # ── 结果处理器（Q7） ──

    def _apply_result_processor(self, client_id: str, task,
                                output: str, error: str) -> None:
        if not self._smods:
            return
        try:
            out = self._smods.run(task.result_processor,
                                  [output, error,
                                   getattr(task, "proc_arg", ""),
                                   self._dispatcher, client_id])
        except Exception as e:
            logger.warning("result processor %s failed: %s",
                           task.result_processor, e)
            return
        try:
            fields = json.loads(out)
        except ValueError:
            return
        if isinstance(fields, dict) and fields:
            self._mgr.update_metadata(client_id, fields)

    # ── auto_commands（T3.4 语义迁移） ──

    def _run_auto_commands(self, client_id: str) -> None:
        commands = self._config.auto_commands
        if not commands or not self._dispatcher:
            return
        for cmd_str in commands:
            cmd_str = cmd_str.strip()
            if not cmd_str:
                continue
            parts = cmd_str.split()
            name, args = parts[0], parts[1:]
            try:
                task = self._dispatcher.build_task_for(client_id, name, args)
            except ValueError as e:
                logger.warning("auto command '%s' build failed: %s",
                               name, e)
                continue
            if task is None:
                logger.warning("auto command module not found: %s", name)
                continue
            self._events.emit(EVT_AUTO_CMD_SENT, client_id, cmd=cmd_str)
            if not self._send_and_wait(client_id, task):
                self._tq.push_front(client_id, task)
                return
