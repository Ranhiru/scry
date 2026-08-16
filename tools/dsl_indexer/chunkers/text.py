"""Fixed-size overlapping chunker — the universal fallback.

Cut positions match the pre-contract implementation exactly, so boundaries for
`.json`, `.yaml`, `.xml`, `.csproj` and friends do not move.
"""

from typing import List

from .base import ChunkContext, ChunkDraft, snap_forward

SECTION = "General"


def chunk(ctx: ChunkContext) -> List[ChunkDraft]:
    size = len(ctx.source)
    if size == 0:
        return []
    if size <= ctx.target_size:
        return [ChunkDraft(0, size, SECTION)]

    drafts: List[ChunkDraft] = []
    step = max(1, ctx.target_size - ctx.overlap)
    start = 0
    while start < size:
        end = min(size, start + ctx.target_size)
        drafts.append(
            ChunkDraft(
                snap_forward(ctx.source, start),
                snap_forward(ctx.source, end),
                SECTION,
            )
        )
        if end == size:
            break
        start += step
    return drafts
