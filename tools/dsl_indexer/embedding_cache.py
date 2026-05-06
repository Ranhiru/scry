"""SQLite-backed cache for chunk embeddings, keyed by sha256(content).

Avoids re-embedding chunks whose text has not changed across builds. Handles
(model, dimension) drift by ignoring rows whose meta does not match the active
config and surfaces an explicit ``wipe()`` for full invalidation.
"""
import hashlib
import sqlite3
import struct
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from .config import EMBEDDING_CACHE_PATH
from .vector_config import EMBEDDING_DIMENSION, EMBEDDING_MODEL

_SCHEMA = """
CREATE TABLE IF NOT EXISTS embeddings (
    content_hash TEXT PRIMARY KEY,
    model        TEXT NOT NULL,
    dimension    INTEGER NOT NULL,
    vector       BLOB NOT NULL
);
"""


def hash_content(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _vector_to_blob(vector: Sequence[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def _blob_to_vector(blob: bytes) -> List[float]:
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))


@contextmanager
def _connect(path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    # Resolve at call time so tests can monkeypatch EMBEDDING_CACHE_PATH.
    if path is None:
        path = EMBEDDING_CACHE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_many(
    hashes: Iterable[str],
    *,
    model: str = EMBEDDING_MODEL,
    dimension: int = EMBEDDING_DIMENSION,
) -> Dict[str, List[float]]:
    """Return a mapping of hash -> vector for cache hits matching (model, dimension)."""
    hashes = list(set(hashes))
    if not hashes:
        return {}
    out: Dict[str, List[float]] = {}
    with _connect() as conn:
        # Chunk into batches to stay under sqlite's parameter limit.
        batch = 500
        for start in range(0, len(hashes), batch):
            slice_ = hashes[start : start + batch]
            placeholders = ",".join("?" * len(slice_))
            rows = conn.execute(
                f"SELECT content_hash, vector FROM embeddings "
                f"WHERE model = ? AND dimension = ? AND content_hash IN ({placeholders})",
                [model, dimension, *slice_],
            ).fetchall()
            for content_hash, blob in rows:
                out[content_hash] = _blob_to_vector(blob)
    return out


def put_many(
    items: Iterable[Tuple[str, Sequence[float]]],
    *,
    model: str = EMBEDDING_MODEL,
    dimension: int = EMBEDDING_DIMENSION,
) -> int:
    rows = [(h, model, dimension, _vector_to_blob(v)) for h, v in items]
    if not rows:
        return 0
    with _connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO embeddings (content_hash, model, dimension, vector) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def wipe() -> None:
    """Remove all cache rows. Used on schema/model invalidation."""
    with _connect() as conn:
        conn.execute("DELETE FROM embeddings")


def gc(live_hashes: Iterable[str]) -> int:
    """Delete rows whose content_hash is not in ``live_hashes``. Returns row count removed."""
    live = set(live_hashes)
    with _connect() as conn:
        # Build a temp table to side-step IN-clause parameter limits.
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS live_hashes (h TEXT PRIMARY KEY)")
        conn.execute("DELETE FROM live_hashes")
        conn.executemany("INSERT OR IGNORE INTO live_hashes(h) VALUES (?)", [(h,) for h in live])
        cursor = conn.execute(
            "DELETE FROM embeddings WHERE content_hash NOT IN (SELECT h FROM live_hashes)"
        )
        removed = cursor.rowcount
        conn.execute("DROP TABLE live_hashes")
    return removed if removed is not None else 0


def row_count() -> int:
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]


def stale_row_count(
    *, model: str = EMBEDDING_MODEL, dimension: int = EMBEDDING_DIMENSION
) -> int:
    """Count rows that don't match the active (model, dimension)."""
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM embeddings WHERE model != ? OR dimension != ?",
            [model, dimension],
        ).fetchone()[0]


def purge_stale(
    *, model: str = EMBEDDING_MODEL, dimension: int = EMBEDDING_DIMENSION
) -> int:
    """Drop rows that don't match the active (model, dimension). Returns count removed."""
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM embeddings WHERE model != ? OR dimension != ?",
            [model, dimension],
        )
        return cursor.rowcount or 0
