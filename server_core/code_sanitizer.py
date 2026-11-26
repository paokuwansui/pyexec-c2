"""Central Python source sanitizer for every code path sent to implants."""
from __future__ import annotations

import hashlib
import io
import tokenize
from dataclasses import dataclass


@dataclass(frozen=True)
class SanitizedCode:
    source: str
    original_hash: str
    stripped_hash: str
    removed_tokens: int


def strip_comments(source: str, filename: str = "<implant>") -> SanitizedCode:
    """Remove only tokenizer-recognized COMMENT tokens.

    Strings, f-strings and multi-line strings are preserved.  The result is
    compiled before being returned; invalid code is rejected.
    """
    if not isinstance(source, str):
        raise TypeError("source must be str")
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    tokens = []
    removed = 0
    try:
        for tok in tokenize.generate_tokens(io.StringIO(normalized).readline):
            if tok.type == tokenize.COMMENT:
                removed += 1
                continue
            tokens.append((tok.type, tok.string))
        stripped = tokenize.untokenize(tokens)
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        raise ValueError(f"cannot tokenize Python source: {exc}") from exc
    try:
        compile(stripped, filename, "exec")
    except SyntaxError as exc:
        raise ValueError(f"sanitized Python source does not compile: {exc}") from exc
    return SanitizedCode(
        source=stripped,
        original_hash=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        stripped_hash=hashlib.sha256(stripped.encode("utf-8")).hexdigest(),
        removed_tokens=removed,
    )
