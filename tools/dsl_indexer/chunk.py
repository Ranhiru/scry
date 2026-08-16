from pathlib import Path
from typing import Callable, Dict, List, Tuple
import hashlib

from .chunkers import base, text
from .config import CHUNKING, REPO_TYPE_MAP, REPOS_DIR
from .text_utils import tokenize
from .chunk_types import Chunk

# markdown and code route to text until their strategies land.
_STRATEGIES: Dict[str, Callable[[base.ChunkContext], List[base.ChunkDraft]]] = {
    "text": text.chunk,
    "markdown": text.chunk,
    "code": text.chunk,
}


def chunk_file(path: Path) -> List[Chunk]:
    source = base.normalize_source(path.read_bytes())
    if not source.strip():
        return []

    repo, rel_path = _repo_and_rel_path(path)
    repo_type = REPO_TYPE_MAP.get(repo, "spec")
    profile, language = CHUNKING.resolve(path.suffix.lower())
    ctx = base.ChunkContext(
        source=source,
        line_starts=base.line_starts(source),
        target_size=profile.target_size,
        hard_max_size=profile.hard_max_size,
        overlap=profile.overlap,
        language=language,
    )

    chunks: List[Chunk] = []
    for draft in _STRATEGIES[profile.strategy](ctx):
        resolved = base.finalize(ctx, draft)
        if resolved is None:
            continue
        content, line_start, line_end = resolved
        chunks.append(
            _build_chunk(
                repo=repo,
                rel_path=rel_path,
                repo_type=repo_type,
                section=draft.section,
                line_start=line_start,
                line_end=line_end,
                content=content,
                ordinal=len(chunks),
            )
        )
    return chunks


def _repo_and_rel_path(path: Path) -> Tuple[str, str]:
    rel = path.resolve().relative_to(REPOS_DIR)
    parts = rel.parts
    repo = parts[0]
    rel_path = str(Path(*parts))
    return repo, rel_path


def _build_chunk(
    repo: str,
    rel_path: str,
    repo_type: str,
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
        repo_type=repo_type,
        path=rel_path,
        section=section,
        line_start=line_start,
        line_end=line_end,
        content=content,
        tokens_est=token_count,
    )
