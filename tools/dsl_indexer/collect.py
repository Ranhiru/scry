from pathlib import Path
from typing import Iterable, List

from .config import (
    EXCLUDED_DIR_NAMES,
    EXCLUDED_FILE_EXACT,
    EXCLUDED_FILE_NAMES,
    EXCLUDED_FILE_PATTERNS,
    MAX_FILE_BYTES,
    REPOS_DIR,
    SOURCE_REPOS,
    TEXT_EXTENSIONS,
)


def iter_source_files() -> Iterable[Path]:
    for repo_name in SOURCE_REPOS:
        repo_root = REPOS_DIR / repo_name
        if not repo_root.exists():
            continue
        for path in repo_root.rglob("*"):
            if not path.is_file():
                continue
            if _is_excluded(path):
                continue
            if path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield path


def collect_source_files() -> List[Path]:
    return sorted(iter_source_files())


def _is_excluded(path: Path) -> bool:
    if path.name in EXCLUDED_FILE_NAMES:
        return True
    if path.name.lower() in EXCLUDED_FILE_EXACT:
        return True
    name_lower = path.name.lower()
    for pattern in EXCLUDED_FILE_PATTERNS:
        if pattern in name_lower:
            return True
    for part in path.parts:
        if part in EXCLUDED_DIR_NAMES:
            return True
    return False

