"""Chunker contract and shared span math.

A chunker's only job is to choose byte cut points. It never produces content,
line numbers, IDs, or token counts — `finalize` does that, once, for everyone.

Modules in this package import only from here, never from `config`, so they
stay unit-testable without a `workspace.yaml`.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import List, Optional, Tuple

WHITESPACE = b" \t\n\r\x0b\x0c"


@dataclass(frozen=True)
class ChunkDraft:
    start_byte: int
    end_byte: int
    section: str


@dataclass(frozen=True)
class ChunkContext:
    source: bytes
    line_starts: List[int]
    target_size: int
    hard_max_size: int
    overlap: int = 0
    language: Optional[str] = None


def normalize_source(raw: bytes) -> bytes:
    """CRLF collapsed once, re-encoded so every byte span slices cleanly as UTF-8.

    Lone \\r and \\x0b are deliberately left alone: treating them as line breaks
    is what makes today's line numbers diverge from byte-derived ones.
    """
    return raw.replace(b"\r\n", b"\n").decode("utf-8", errors="ignore").encode("utf-8")


def line_starts(source: bytes) -> List[int]:
    """Byte offset of each line start. A trailing newline opens a final empty line."""
    starts = [0]
    for i, byte in enumerate(source):
        if byte == 0x0A:
            starts.append(i + 1)
    return starts


def line_of(starts: List[int], offset: int) -> int:
    """1-based line number containing `offset`."""
    return bisect_right(starts, offset)


def snap_forward(source: bytes, index: int) -> int:
    """Advance past UTF-8 continuation bytes so `index` lands on a codepoint boundary."""
    while index < len(source) and 0x80 <= source[index] < 0xC0:
        index += 1
    return index


def finalize(ctx: ChunkContext, draft: ChunkDraft) -> Optional[Tuple[str, int, int]]:
    """Resolve a draft to (content, line_start, line_end), or None if it is all whitespace.

    Offsets snap to codepoint boundaries and surrounding whitespace is trimmed
    before lines are read, so the reported range always covers the content.
    """
    start = snap_forward(ctx.source, max(0, draft.start_byte))
    end = snap_forward(ctx.source, min(len(ctx.source), draft.end_byte))
    while start < end and ctx.source[start] in WHITESPACE:
        start += 1
    while end > start and ctx.source[end - 1] in WHITESPACE:
        end -= 1
    if start >= end:
        return None

    content = ctx.source[start:end].decode("utf-8", errors="ignore")
    # end is exclusive: a span ending at column 0 belongs to the previous line.
    return content, line_of(ctx.line_starts, start), line_of(ctx.line_starts, end - 1)


def split_oversized(start: int, end: int, section: str, ctx: ChunkContext) -> List[ChunkDraft]:
    """Cut [start, end) down to `hard_max_size`, preferring line boundaries. Tiles exactly."""
    if end - start <= ctx.hard_max_size:
        return [ChunkDraft(start, end, section)]

    drafts: List[ChunkDraft] = []
    cut = start
    while cut < end:
        limit = min(end, cut + ctx.hard_max_size)
        if limit < end:
            newline = ctx.source.rfind(b"\n", cut, limit)
            limit = newline + 1 if newline > cut else snap_forward(ctx.source, limit)
        drafts.append(ChunkDraft(cut, limit, section))
        cut = limit
    return drafts
