"""Span math and the text chunker.

Imports only `chunkers.*`, so these run without a workspace.yaml.
"""

from typing import List, Tuple

from tools.dsl_indexer.chunkers import text
from tools.dsl_indexer.chunkers.base import (
    ChunkContext,
    ChunkDraft,
    finalize,
    line_of,
    line_starts,
    normalize_source,
    snap_forward,
)


def _context(source: str, target: int = 1100, overlap: int = 180) -> ChunkContext:
    data = source.encode("utf-8")
    return ChunkContext(
        source=data,
        line_starts=line_starts(data),
        target_size=target,
        hard_max_size=2 * target,
        overlap=overlap,
    )


def _chunks(source: str, **kwargs) -> List[Tuple[str, int, int]]:
    ctx = _context(source, **kwargs)
    return [r for r in (finalize(ctx, d) for d in text.chunk(ctx)) if r is not None]


def _assert_lines_match(source: str, results: List[Tuple[str, int, int]]) -> None:
    lines = source.split("\n")
    for content, line_start, line_end in results:
        window = "\n".join(lines[line_start - 1 : line_end])
        assert content in window, f"{content[:40]!r} not within lines {line_start}-{line_end}"


def test_line_numbers_exact():
    source = "\n\n\nalpha\nbeta\ngamma\n" + "\n".join(f"line {i}" for i in range(200))
    results = _chunks(source, target=200, overlap=40)
    assert len(results) > 1
    _assert_lines_match(source, results)


def test_leading_blank_lines_are_not_swallowed():
    source = "\n\n\nfirst real line\n"
    (content, line_start, line_end), = _chunks(source)
    assert content == "first real line"
    assert (line_start, line_end) == (4, 4)


def test_repeated_blocks_get_distinct_line_windows():
    block = '{"name": "same", "value": 1}\n'
    results = _chunks(block * 60, target=120, overlap=0)
    starts = [line_start for _, line_start, _ in results]
    assert starts == sorted(starts)
    assert len(set(starts)) == len(starts)
    _assert_lines_match(block * 60, results)


def test_multibyte_content_is_not_corrupted():
    source = "héllo wörld ✅ 日本語テキスト\n" * 200
    results = _chunks(source, target=100, overlap=20)
    assert len(results) > 1
    for content, _, _ in results:
        assert "�" not in content
    _assert_lines_match(source, results)


def test_crlf_matches_lf():
    lf = "alpha\nbeta\ngamma\n" * 40
    crlf = normalize_source(lf.replace("\n", "\r\n").encode("utf-8")).decode("utf-8")
    assert _chunks(crlf, target=100) == _chunks(lf, target=100)


def test_no_trailing_newline():
    source = "alpha\nbeta\ngamma"
    (content, line_start, line_end), = _chunks(source)
    assert content == source
    assert (line_start, line_end) == (1, 3)


def test_span_ending_at_column_zero_reports_previous_line():
    source = "alpha\nbeta\n"
    ctx = _context(source)
    content, line_start, line_end = finalize(ctx, ChunkDraft(0, len(source.encode()), "General"))
    assert content == "alpha\nbeta"
    assert (line_start, line_end) == (1, 2)


def test_whitespace_only_span_is_dropped():
    ctx = _context("alpha\n\n\n\nbeta\n")
    assert finalize(ctx, ChunkDraft(6, 9, "General")) is None


def test_line_of_boundaries():
    starts = line_starts(b"ab\ncd\n")
    assert [line_of(starts, i) for i in range(6)] == [1, 1, 1, 2, 2, 2]


def test_snap_forward_never_splits_a_codepoint():
    source = "aé日".encode("utf-8")
    for i in range(len(source)):
        snapped = snap_forward(source, i)
        source[snapped:].decode("utf-8")  # raises if a codepoint was split


def test_empty_source_yields_nothing():
    assert _chunks("") == []
    assert _chunks("   \n\n  \n") == []
