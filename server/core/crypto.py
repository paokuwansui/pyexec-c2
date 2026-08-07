"""
core/crypto.py — 加密/解密管道 (XOR + zlib + Base64)

编码管道:
  原始数据 (bytes)
    → zlib.compress()
    → xor_crypt(key)
    → base64.b64encode()

解码管道 (逆向):
  Base64 ASCII → base64.b64decode() → xor_crypt(key) → zlib.decompress() → 原始数据

XOR 运算对称：加密和解密是同一函数。

编码选型 (6.11 决策): Base64 字符集 (A-Za-z0-9+/=) 在单引号 shell 部署命令、
JSON、URL 等场景完全兼容；体积由 zlib 压缩 + 短变量名控制。
"""

import zlib
import base64


def xor_crypt(data: bytes, key: bytes) -> bytes:
    """逐字节与 key 循环异或。

    Args:
        data: 待处理数据
        key: XOR 密钥 (任意长度)

    Returns:
        异或后的数据 (长度不变)

    Raises:
        ValueError: key 为空
    """
    if not key:
        raise ValueError("xor_crypt: key must not be empty")
    key_len = len(key)
    return bytes(b ^ key[i % key_len] for i, b in enumerate(data))


def encode_frame(data: bytes, key: bytes) -> bytes:
    """编码: zlib 压缩 → XOR 混淆 → Base64 ASCII。

    Args:
        data: 原始字节
        key: XOR 密钥

    Returns:
        Base64 ASCII 字符串 (bytes)
    """
    compressed = zlib.compress(data)
    obfuscated = xor_crypt(compressed, key)
    return base64.b64encode(obfuscated)


def decode_frame(data: bytes, key: bytes) -> bytes:
    """解码: Base64 解码 → XOR 解密 → zlib 解压。

    Args:
        data: Base64 编码的 ASCII 数据
        key: XOR 密钥

    Returns:
        原始字节

    Raises:
        ValueError: 数据损坏或格式错误
    """
    if not data:
        raise ValueError("decode_frame: data must not be empty")
    try:
        decoded = base64.b64decode(data)
    except (ValueError, base64.binascii.Error) as e:
        raise ValueError(f"decode_frame: invalid Base64 data: {e}") from e
    deobfuscated = xor_crypt(decoded, key)
    try:
        return zlib.decompress(deobfuscated)
    except zlib.error as e:
        raise ValueError(f"decode_frame: decompression failed: {e}") from e
