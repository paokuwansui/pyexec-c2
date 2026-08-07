#!/usr/bin/env python3
"""
client/client.py — PyExec2 C2 Client 主程序（T5.2）

两种模式:
  1. 单行模式 (-c): 直接发送一条命令到 Server
  2. 交互模式 (默认): 与 Server 控制台相同的交互体验

配置: client/config.json（server_host / client_port / client_key）
"""

import os
import sys
import argparse

# 运行时从 client/ 目录启动（python3 client.py）：项目根入 sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from server.core.config import load_config, ClientConfig
from client.remote_client import RemoteClient


class PyExec2Client:
    """Client 主类 — 透明加密管道。"""

    def __init__(self, config: ClientConfig):
        self._config = config
        self._remote = RemoteClient(
            server_host=config.server_host,
            client_port=config.client_port,
            client_key_hex=config.client_key,
            client_tls=bool(getattr(config, "client_tls", False)),
        )

    def send_line(self, line: str) -> str:
        """发送一条命令，返回 Server 响应文本。"""
        resp = self._remote.send_command(line)
        if resp.get("type") == "response":
            return resp.get("output", "")
        return f"error: {resp.get('error', 'unknown')}"

    def interactive(self) -> None:
        """交互式命令行模式。"""
        if self._remote.error:
            print(f"[!] {self._remote.error}")
            return
        if not self._remote.connect():
            print(f"[!] Failed to connect: {self._remote.error}")
            return

        print(f"[*] Connected to {self._config.server_host}:"
              f"{self._config.client_port}")
        print("Type commands (same as Server console). 'exit' to quit.\n")

        while True:
            try:
                line = input("client> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[*] Disconnecting...")
                break
            if not line:
                continue
            if line.lower() == "exit":
                break
            output = self.send_line(line)
            if output:
                print(output)

        self._remote.close()


def main():
    parser = argparse.ArgumentParser(description="PyExec2 C2 Client")
    parser.add_argument("--config", default="config.json",
                        help="Config file path")
    parser.add_argument("-c", "--command", default=None,
                        help="Single command mode")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except FileNotFoundError:
        print(f"[!] Config not found: {args.config}, using defaults")
        config = ClientConfig()

    client = PyExec2Client(config)

    if args.command:
        output = client.send_line(args.command)
        if output:
            print(output)
    else:
        client.interactive()


if __name__ == "__main__":
    main()
