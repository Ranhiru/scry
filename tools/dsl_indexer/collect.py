import subprocess
import sys
from pathlib import Path
from typing import Iterable, List

from .config import (
    EXCLUDED_DIR_NAMES,
    EXCLUDED_FILE_EXACT,
    EXCLUDED_FILE_NAMES,
    EXCLUDED_FILE_PATTERNS,
    MAX_FILE_BYTES,
    REPOS_DIR,
    SOURCE_REPO_NAMES,
    TEXT_EXTENSIONS,
)


def iter_source_files() -> Iterable[Path]:
    for repo_name in SOURCE_REPO_NAMES:
        repo_root = REPOS_DIR / repo_name
        if not repo_root.exists():
            continue
        for path in _iter_repo_files(repo_root):
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


def _iter_repo_files(repo_root: Path) -> Iterable[Path]:
    """Yield files under repo_root, honouring .gitignore when the repo is a git checkout.

    Uses `git ls-files --cached --others --exclude-standard -z` to get tracked files
    plus untracked-but-not-ignored files. Falls back to rglob for non-git directories.
    """
    if (repo_root / ".git").exists():
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                capture_output=True,
                check=True,
                timeout=60,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
            print(f"WARNING: git ls-files failed in {repo_root} ({exc}); falling back to rglob", file=sys.stderr)
            yield from repo_root.rglob("*")
            return
        for entry in result.stdout.split(b"\0"):
            if not entry:
                continue
            yield repo_root / entry.decode("utf-8", errors="replace")
        return
    yield from repo_root.rglob("*")


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
