"""
client/remote_client.py — Client 到 Server 的加密 TCP 通信层（T5.1）

统一 JSON 帧协议（第 7 章）: 注册（role=client, client_key, client_port）
→ COMMAND/RESPONSE 往返。配置错误不退出进程（C4），通过 error 属性暴露。

断线重连: 发送时若连接已失效自动重连。
"""

import json
import os
import socket
import threading
from typing import Optional

from server.core.protocol import (
    send_frame, recv_frame, COMMAND, RESPONSE, ERROR,
    REGISTER, WELCOME, PROTOCOL_VERSION,
)


class RemoteClient:
    """加密连接到 Server 的 Client。"""

    def __init__(self, server_host: str, client_port: int,
                 client_key_hex: str, client_tls: bool = False):
        self._host = server_host
        self._port = client_port
        self._key_hex = client_key_hex or ""
        self._tls = client_tls
        self._key: Optional[bytes] = None
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._error = ""
        if not self._key_hex or len(self._key_hex) != 64:
            self._error = (f"client_key 无效 "
                           f"(长度={len(self._key_hex)}，需要 64 字符 hex)。"
                           f"请先 s_exec keygen 并同步到 client 配置。")
        else:
            try:
                self._key = bytes.fromhex(self._key_hex)
            except ValueError:
                self._error = "client_key 不是合法 hex"

    @property
    def error(self) -> str:
        return self._error

    def connect(self) -> bool:
        """连接 Server 并注册为 Client（含握手响应校验）。"""
        if self._key is None:
            return False
        try:
            sock = socket.create_connection((self._host, self._port),
                                            timeout=10)
            if self._tls:
                import ssl
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE  # 自签证书：防被动嗅探
                sock = ctx.wrap_socket(sock, server_hostname=self._host)
            sock.settimeout(30)
            reg = {
                "type": REGISTER, "version": PROTOCOL_VERSION,
                "role": "client",
                "id": f"client_{socket.gethostname()}_{os.getpid()}",
            }
            send_frame(sock, json.dumps(reg).encode("utf-8"), self._key)
            resp = json.loads(recv_frame(sock, self._key).decode("utf-8"))
            if resp.get("type") == ERROR:
                self._error = f"server rejected: {resp.get('message')}"
                sock.close()
                return False
            if resp.get("type") != WELCOME:
                self._error = f"unexpected handshake: {resp.get('type')}"
                sock.close()
                return False
            self._sock = sock
            self._error = ""
            return True
        except Exception as e:
            self._error = str(e)
            return False

    def send_command(self, line: str) -> dict:
        """发送一条命令，返回响应 dict（7.5 COMMAND/RESPONSE）。

        失败时返回 {"status": "error", "error": ...}。
        """
        with self._lock:
            if self._sock is None and not self.connect():
                return {"status": "error",
                        "error": self._error or "connection failed"}
            try:
                msg = {"type": COMMAND, "line": line}
                send_frame(self._sock, json.dumps(msg).encode("utf-8"),
                           self._key)
                raw = recv_frame(self._sock, self._key)
                return json.loads(raw.decode("utf-8"))
            except Exception as e:
                self._sock = None
                return {"status": "error", "error": str(e)}

    def close(self) -> None:
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
