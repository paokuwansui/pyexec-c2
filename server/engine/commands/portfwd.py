"""portfwd — 端口转发（14）: 把目标内网端口映射到 server 本地
portfwd <beacon_id> <listen_port> <target_host> <target_port>
"""

import socket
import threading


def run(disp, args):
    if len(args) < 4:
        return "[!] usage: portfwd <beacon_id> <listen_port> " \
               "<target_host> <target_port>"
    bid, lport_s, thost, tport_s = args[0], args[1], args[2], args[3]
    try:
        lport = int(lport_s)
        tport = int(tport_s)
    except ValueError:
        return "[!] 端口必须是数字"
    hub = getattr(disp, "hub", None)
    if hub is None:
        return "[!] 中继未启用（config relay_port 需 >0）"

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", lport))
        s.listen(8)
        s.settimeout(1.0)
    except OSError as e:
        return f"[!] 监听失败: {e}"

    stopped = {"v": False}

    def _loop():
        while not stopped["v"]:
            try:
                conn, _ = s.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                hub.open_channel(bid, conn, thost, tport)
            except ValueError as e:
                conn.close()
                return

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    disp._portfwd_stop = lambda: stopped.update(v=True)

    return (f"[+] 端口转发: 127.0.0.1:{lport} → {bid}:{thost}:{tport}\n"
            f"    每个连接经 beacon 中继（延迟 ≈ beacon 轮询周期）")
