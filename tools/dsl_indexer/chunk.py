from pathlib import Path
from typing import List, Tuple
import hashlib
import re

from .config import CHUNK_OVERLAP_CHARS, CHUNK_TARGET_CHARS, REPOS_DIR
from .text_utils import tokenize
from .chunk_types import Chunk


def chunk_file(path: Path) -> List[Chunk]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="ignore")

    repo, rel_path = _repo_and_rel_path(path)
    if path.suffix.lower() in {".md", ".mdx"}:
        chunks = _chunk_markdown(text, repo, rel_path)
    else:
        chunks = _chunk_plain(text, repo, rel_path)
    return chunks


def _repo_and_rel_path(path: Path) -> Tuple[str, str]:
    rel = path.resolve().relative_to(REPOS_DIR)
    parts = rel.parts
    repo = parts[0]
    rel_path = str(Path(*parts))
    return repo, rel_path


def _chunk_markdown(text: str, repo: str, rel_path: str) -> List[Chunk]:
    lines = text.splitlines()
    sections = []
    current_heading = "Document Start"
    start_idx = 0

    for i, line in enumerate(lines):
        if re.match(r"^\s{0,3}#{1,6}\s+.+", line):
            if i > start_idx:
                sections.append((current_heading, start_idx, i))
            current_heading = line.lstrip("# ").strip()
            start_idx = i

    sections.append((current_heading, start_idx, len(lines)))

    chunks: List[Chunk] = []
    for heading, start, end in sections:
        section_lines = lines[start:end]
        section_text = "\n".join(section_lines).strip()
        if not section_text:
            continue
        pieces = _slice_with_overlap(section_text, CHUNK_TARGET_CHARS, CHUNK_OVERLAP_CHARS)
        offset = 0
        for idx, piece in enumerate(pieces):
            line_start, line_end = _line_window_for_piece(section_text, piece, start + 1, offset)
            offset = max(0, section_text.find(piece, offset) + len(piece))
            chunks.append(
                _build_chunk(
                    repo=repo,
                    rel_path=rel_path,
                    section=heading,
                    line_start=line_start,
                    line_end=line_end,
                    content=piece,
                    ordinal=idx,
                )
            )
    return chunks


def _chunk_plain(text: str, repo: str, rel_path: str) -> List[Chunk]:
    lines = text.splitlines()
    content = "\n".join(lines).strip()
    if not content:
        return []

    chunks: List[Chunk] = []
    pieces = _slice_with_overlap(content, CHUNK_TARGET_CHARS, CHUNK_OVERLAP_CHARS)
    offset = 0
    for idx, piece in enumerate(pieces):
        line_start, line_end = _line_window_for_piece(content, piece, 1, offset)
        offset = max(0, content.find(piece, offset) + len(piece))
        chunks.append(
            _build_chunk(
                repo=repo,
                rel_path=rel_path,
                section="General",
                line_start=line_start,
                line_end=line_end,
                content=piece,
                ordinal=idx,
            )
        )
    return chunks


def _slice_with_overlap(text: str, target: int, overlap: int) -> List[str]:
    if len(text) <= target:
        return [text]

    chunks: List[str] = []
    step = max(1, target - overlap)
    start = 0
    while start < len(text):
        end = min(len(text), start + target)
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end == len(text):
            break
        start += step
    return chunks


def _line_window_for_piece(full_text: str, piece: str, base_line: int, offset_hint: int) -> Tuple[int, int]:
    idx = full_text.find(piece, offset_hint)
    if idx < 0:
        idx = full_text.find(piece)
    if idx < 0:
        return base_line, base_line

    before = full_text[:idx]
    within = full_text[idx : idx + len(piece)]
    line_start = base_line + before.count("\n")
    line_end = line_start + within.count("\n")
    return line_start, max(line_start, line_end)


def _build_chunk(
    repo: str,
    rel_path: str,
    section: str,
    line_start: int,
    line_end: int,
    content: str,
    ordinal: int,
) -> Chunk:
    stable = f"{repo}:{rel_path}:{section}:{line_start}:{line_end}:{ordinal}"
    chunk_id = hashlib.sha1(stable.encode("utf-8")).hexdigest()[:16]
    token_count = len(tokenize(content))
    return Chunk(
        chunk_id=chunk_id,
        repo=repo,
        path=rel_path,
        section=section,
        line_start=line_start,
        line_end=line_end,
        content=content,
        tokens_est=token_count,
    )
