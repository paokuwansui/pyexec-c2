"""Single egress pipeline for every Python source sent to an implant."""
from __future__ import annotations

from dataclasses import dataclass

from .code_sanitizer import SanitizedCode, strip_comments


@dataclass(frozen=True)
class PreparedCode:
    source: str
    original_hash: str
    stripped_hash: str
    removed_tokens: int
    source_type: str


class CodeDeliveryPipeline:
    def __init__(self, store=None):
        self.store = store

    def prepare(self, source: str, source_type: str, *, ref: str = "", filename: str = "<implant>") -> PreparedCode:
        if source_type not in {"plugin", "script", "control", "payload", "upgrade"}:
            raise ValueError(f"unknown source_type: {source_type}")
        result: SanitizedCode = strip_comments(source, filename=filename)
        prepared = PreparedCode(
            source=result.source,
            original_hash=result.original_hash,
            stripped_hash=result.stripped_hash,
            removed_tokens=result.removed_tokens,
            source_type=source_type,
        )
        if self.store is not None:
            self.store.event(
                "code.prepared",
                {
                    "source_type": source_type,
                    "ref": ref,
                    "original_hash": prepared.original_hash,
                    "stripped_hash": prepared.stripped_hash,
                    "removed_tokens": prepared.removed_tokens,
                },
                actor="server",
            )
        return prepared
