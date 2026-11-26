"""Pure-Python ChaCha20-Poly1305 AEAD used by server and generated implants.

The implementation follows RFC 8439 closely and intentionally has no third-party
runtime dependency.  It is suitable for protocol traffic where performance is
secondary to target portability.
"""
from __future__ import annotations

import os
import struct
from hashlib import sha256

_MASK = 0xFFFFFFFF


def _rotl32(v: int, c: int) -> int:
    return ((v << c) & _MASK) | (v >> (32 - c))


def _quarter_round(state: list[int], a: int, b: int, c: int, d: int) -> None:
    state[a] = (state[a] + state[b]) & _MASK
    state[d] ^= state[a]
    state[d] = _rotl32(state[d], 16)
    state[c] = (state[c] + state[d]) & _MASK
    state[b] ^= state[c]
    state[b] = _rotl32(state[b], 12)
    state[a] = (state[a] + state[b]) & _MASK
    state[d] ^= state[a]
    state[d] = _rotl32(state[d], 8)
    state[c] = (state[c] + state[d]) & _MASK
    state[b] ^= state[c]
    state[b] = _rotl32(state[b], 7)


def _chacha20_block(key: bytes, counter: int, nonce: bytes) -> bytes:
    if len(key) != 32 or len(nonce) != 12:
        raise ValueError("ChaCha20 requires a 32-byte key and 12-byte nonce")
    constants = b"expand 32-byte k"
    state = list(struct.unpack("<4I", constants))
    state.extend(struct.unpack("<8I", key))
    state.append(counter & _MASK)
    state.extend(struct.unpack("<3I", nonce))
    working = state[:]
    for _ in range(10):
        _quarter_round(working, 0, 4, 8, 12)
        _quarter_round(working, 1, 5, 9, 13)
        _quarter_round(working, 2, 6, 10, 14)
        _quarter_round(working, 3, 7, 11, 15)
        _quarter_round(working, 0, 5, 10, 15)
        _quarter_round(working, 1, 6, 11, 12)
        _quarter_round(working, 2, 7, 8, 13)
        _quarter_round(working, 3, 4, 9, 14)
    out = [(working[i] + state[i]) & _MASK for i in range(16)]
    return struct.pack("<16I", *out)


def chacha20_xor(data: bytes, key: bytes, nonce: bytes, counter: int = 1) -> bytes:
    result = bytearray(len(data))
    for offset in range(0, len(data), 64):
        block = _chacha20_block(key, counter + offset // 64, nonce)
        chunk = data[offset : offset + 64]
        for i, byte in enumerate(chunk):
            result[offset + i] = byte ^ block[i]
    return bytes(result)


def _poly1305_mac(message: bytes, key: bytes) -> bytes:
    if len(key) != 32:
        raise ValueError("Poly1305 requires a 32-byte key")
    r = int.from_bytes(key[:16], "little") & 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF
    s = int.from_bytes(key[16:], "little")
    p = (1 << 130) - 5
    acc = 0
    for offset in range(0, len(message), 16):
        chunk = message[offset : offset + 16]
        n = int.from_bytes(chunk + b"\x01", "little")
        acc = ((acc + n) * r) % p
    acc = (acc + s) & ((1 << 128) - 1)
    return acc.to_bytes(16, "little")


def _pad16(data: bytes) -> bytes:
    return b"\x00" * ((16 - len(data) % 16) % 16)


def derive_key(secret: bytes | str, salt: bytes = b"pyexec2") -> bytes:
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    return sha256(salt + b":" + secret).digest()


def seal(key: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
    """Return nonce || ciphertext || tag."""
    if len(key) != 32:
        raise ValueError("key must be 32 bytes")
    nonce = os.urandom(12)
    poly_key = _chacha20_block(key, 0, nonce)[:32]
    ciphertext = chacha20_xor(plaintext, key, nonce, 1)
    mac_data = aad + _pad16(aad) + ciphertext + _pad16(ciphertext)
    mac_data += struct.pack("<QQ", len(aad), len(ciphertext))
    tag = _poly1305_mac(mac_data, poly_key)
    return nonce + ciphertext + tag


def open_seal(key: bytes, sealed: bytes, aad: bytes = b"") -> bytes:
    if len(key) != 32:
        raise ValueError("key must be 32 bytes")
    if len(sealed) < 28:
        raise ValueError("sealed payload too short")
    nonce, ciphertext, tag = sealed[:12], sealed[12:-16], sealed[-16:]
    poly_key = _chacha20_block(key, 0, nonce)[:32]
    mac_data = aad + _pad16(aad) + ciphertext + _pad16(ciphertext)
    mac_data += struct.pack("<QQ", len(aad), len(ciphertext))
    expected = _poly1305_mac(mac_data, poly_key)
    if not hmac_compare(expected, tag):
        raise ValueError("authentication failed")
    return chacha20_xor(ciphertext, key, nonce, 1)


def hmac_compare(a: bytes, b: bytes) -> bool:
    if len(a) != len(b):
        return False
    diff = 0
    for x, y in zip(a, b):
        diff |= x ^ y
    return diff == 0
