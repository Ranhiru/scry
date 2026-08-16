"""Per-file manifest for incremental indexing.

Tracks which chunk_ids belong to each source file and a (size, mtime, sha256)
fingerprint so subsequent builds can classify files as unchanged / modified /
added / deleted.
"""
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from .config import REPOS_DIR, REPO_TYPE_MAP

MANIFEST_VERSION = 1
_HASH_CHUNK_BYTES = 1 << 20  # 1 MiB


@dataclass
class FileEntry:
    repo: str
    repo_type: str
    rel_path: str  # includes repo prefix, matches Chunk.path
    size: int
    mtime_ns: int
    sha256: str
    chunk_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "repo": self.repo,
            "repo_type": self.repo_type,
            "rel_path": self.rel_path,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "sha256": self.sha256,
            "chunk_ids": list(self.chunk_ids),
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "FileEntry":
        return cls(
            repo=d["repo"],
            repo_type=d.get("repo_type", "spec"),
            rel_path=d["rel_path"],
            size=int(d["size"]),
            mtime_ns=int(d["mtime_ns"]),
            sha256=d["sha256"],
            chunk_ids=list(d.get("chunk_ids", [])),
        )


@dataclass
class Diff:
    unchanged: List[FileEntry]  # reuse existing chunk_ids
    modified: List[Tuple[FileEntry, Path]]  # old entry + current path
    added: List[Path]
    deleted: List[FileEntry]

    @property
    def has_changes(self) -> bool:
        return bool(self.modified or self.added or self.deleted)


def empty_manifest() -> Dict:
    return {"version": MANIFEST_VERSION, "files": {}}


def load_files(manifest: Dict) -> Dict[str, FileEntry]:
    raw = manifest.get("files", {})
    return {key: FileEntry.from_dict(value) for key, value in raw.items()}


def serialize(files: Dict[str, FileEntry]) -> Dict:
    return {
        "version": MANIFEST_VERSION,
        "files": {key: entry.to_dict() for key, entry in files.items()},
    }


def repo_and_rel(path: Path) -> Tuple[str, str]:
    """Return (repo_name, manifest_key) for a file under REPOS_DIR.

    The manifest key matches the chunk.path convention: it includes the repo
    name as the first segment (e.g. ``docs-repo/internal/foo.md``).
    """
    rel = path.resolve().relative_to(REPOS_DIR)
    parts = rel.parts
    return parts[0], str(Path(*parts))


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(_HASH_CHUNK_BYTES)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def stat_fingerprint(path: Path) -> Tuple[int, int]:
    st = path.stat()
    return st.st_size, st.st_mtime_ns


def classify(current_files: Iterable[Path], manifest: Dict) -> Diff:
    """Diff the current file set against the manifest.

    Fast path: identical (size, mtime_ns) means unchanged, no hashing required.
    Otherwise hash and compare to detect touch-only edits.
    """
    files_map = load_files(manifest)
    seen_keys: set[str] = set()

    unchanged: List[FileEntry] = []
    modified: List[Tuple[FileEntry, Path]] = []
    added: List[Path] = []

    for path in current_files:
        repo, key = repo_and_rel(path)
        seen_keys.add(key)
        existing = files_map.get(key)
        try:
            size, mtime_ns = stat_fingerprint(path)
        except OSError:
            continue

        if existing is None:
            added.append(path)
            continue

        if existing.size == size and existing.mtime_ns == mtime_ns:
            unchanged.append(existing)
            continue

        # Stat differs; hash to confirm content change.
        digest = hash_file(path)
        if digest == existing.sha256:
            # Touched but content unchanged — refresh fingerprint, keep chunk_ids.
            refreshed = FileEntry(
                repo=existing.repo,
                repo_type=REPO_TYPE_MAP.get(existing.repo, existing.repo_type),
                rel_path=existing.rel_path,
                size=size,
                mtime_ns=mtime_ns,
                sha256=digest,
                chunk_ids=list(existing.chunk_ids),
            )
            unchanged.append(refreshed)
        else:
            modified.append((existing, path))

    deleted = [entry for key, entry in files_map.items() if key not in seen_keys]
    return Diff(unchanged=unchanged, modified=modified, added=added, deleted=deleted)


def build_entry(path: Path, chunk_ids: List[str]) -> FileEntry:
    """Build a FileEntry for a (re-)chunked file."""
    repo, key = repo_and_rel(path)
    size, mtime_ns = stat_fingerprint(path)
    digest = hash_file(path)
    return FileEntry(
        repo=repo,
        repo_type=REPO_TYPE_MAP.get(repo, "spec"),
        rel_path=key,
        size=size,
        mtime_ns=mtime_ns,
        sha256=digest,
        chunk_ids=list(chunk_ids),
    )
