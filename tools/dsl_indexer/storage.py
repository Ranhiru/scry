import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List

from .config import CHUNKS_PATH, DATA_DIR, KEYWORD_INDEX_PATH, MANIFEST_PATH, META_PATH
from .chunk_types import Chunk


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write(target: Path, data: bytes) -> None:
    """Write data to a temp file then atomically replace the target."""
    ensure_data_dir()
    fd, tmp_path = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
    closed = False
    try:
        os.write(fd, data)
        os.fsync(fd)
        os.close(fd)
        closed = True
        os.replace(tmp_path, str(target))
    except BaseException:
        if not closed:
            os.close(fd)
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _read_locked(path: Path) -> bytes:
    """Read an entire file under a shared (read) lock."""
    with path.open("rb") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
        try:
            return f.read()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def write_chunks(chunks: Iterable[Chunk]) -> None:
    lines = [json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n" for chunk in chunks]
    _atomic_write(CHUNKS_PATH, "".join(lines).encode("utf-8"))


def write_chunk_dicts(chunks: Iterable[Dict]) -> None:
    """Write already-dict chunks (e.g. loaded via read_chunks then mutated)."""
    lines = [json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks]
    _atomic_write(CHUNKS_PATH, "".join(lines).encode("utf-8"))


def read_chunks() -> List[Dict]:
    if not CHUNKS_PATH.exists():
        return []
    data = _read_locked(CHUNKS_PATH).decode("utf-8")
    rows: List[Dict] = []
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def write_keyword_index(index: Dict) -> None:
    data = json.dumps(index, ensure_ascii=False).encode("utf-8")
    _atomic_write(KEYWORD_INDEX_PATH, data)


def read_keyword_index() -> Dict:
    if not KEYWORD_INDEX_PATH.exists():
        return {}
    data = _read_locked(KEYWORD_INDEX_PATH).decode("utf-8")
    return json.loads(data)


def write_meta(meta: Dict) -> None:
    data = json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8")
    _atomic_write(META_PATH, data)


def read_meta() -> Dict:
    if not META_PATH.exists():
        return {}
    data = _read_locked(META_PATH).decode("utf-8")
    return json.loads(data)


def write_manifest(manifest: Dict) -> None:
    data = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
    _atomic_write(MANIFEST_PATH, data)


def read_manifest() -> Dict:
    if not MANIFEST_PATH.exists():
        return {}
    data = _read_locked(MANIFEST_PATH).decode("utf-8")
    return json.loads(data)
