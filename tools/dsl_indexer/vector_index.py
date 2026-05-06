import shutil
import sys
from typing import Dict, List, Optional

import zvec

from .vector_config import EMBEDDING_DIMENSION, HNSW_EF_CONSTRUCTION, HNSW_M, VECTOR_INDEX_DIR


def build_vector_index(
    chunks: List[Dict],
    embeddings: Dict[str, List[float]],
    *,
    dimension: int = EMBEDDING_DIMENSION,
) -> Dict:
    """Build a zvec HNSW collection from chunks and their embeddings.

    Destroys any existing collection at VECTOR_INDEX_DIR, creates a fresh one,
    inserts all documents, flushes, and optimizes.

    Returns metadata dict with doc_count, dimension, etc.
    """
    index_path = str(VECTOR_INDEX_DIR)

    # Remove existing collection directory if present
    if VECTOR_INDEX_DIR.exists():
        shutil.rmtree(VECTOR_INDEX_DIR)

    schema = zvec.CollectionSchema(
        name="workspace_docs",
        fields=[
            zvec.FieldSchema("repo", zvec.DataType.STRING),
            zvec.FieldSchema("repo_type", zvec.DataType.STRING),
            zvec.FieldSchema("path", zvec.DataType.STRING),
            zvec.FieldSchema("section", zvec.DataType.STRING),
            zvec.FieldSchema("line_start", zvec.DataType.INT32),
            zvec.FieldSchema("line_end", zvec.DataType.INT32),
            zvec.FieldSchema("content", zvec.DataType.STRING),
        ],
        vectors=zvec.VectorSchema(
            "embedding",
            zvec.DataType.VECTOR_FP32,
            dimension=dimension,
            index_param=zvec.HnswIndexParam(
                ef_construction=HNSW_EF_CONSTRUCTION,
                m=HNSW_M,
            ),
        ),
    )

    collection = zvec.create_and_open(path=index_path, schema=schema)

    # Create inverted indexes for efficient filtering
    collection.create_index(
        field_name="repo",
        index_param=zvec.InvertIndexParam(),
    )
    collection.create_index(
        field_name="repo_type",
        index_param=zvec.InvertIndexParam(),
    )

    # Insert in batches
    batch_size = 1000
    inserted = 0
    chunk_ids = list(embeddings.keys())
    chunk_map = {c["chunk_id"]: c for c in chunks}

    for start in range(0, len(chunk_ids), batch_size):
        batch_ids = chunk_ids[start : start + batch_size]
        docs = []
        for cid in batch_ids:
            chunk = chunk_map[cid]
            vec = embeddings[cid]
            docs.append(
                zvec.Doc(
                    id=cid,
                    vectors={"embedding": vec},
                    fields={
                        "repo": chunk["repo"],
                        "repo_type": chunk.get("repo_type", "spec"),
                        "path": chunk["path"],
                        "section": chunk["section"],
                        "line_start": chunk["line_start"],
                        "line_end": chunk["line_end"],
                        "content": chunk["content"],
                    },
                )
            )
        collection.insert(docs)
        inserted += len(docs)
        print(
            f"\rVector index: inserted {inserted}/{len(chunk_ids)} docs",
            end="",
            file=sys.stderr,
            flush=True,
        )

    print(file=sys.stderr)
    collection.flush()
    collection.optimize()

    return {
        "doc_count": inserted,
        "dimension": dimension,
        "index_path": index_path,
        "hnsw_ef_construction": HNSW_EF_CONSTRUCTION,
        "hnsw_m": HNSW_M,
    }


def search_vector_index(
    query_embedding: List[float],
    *,
    top_k: int = 8,
    repo_filter: Optional[List[str]] = None,
    repo_type_filter: Optional[List[str]] = None,
) -> List[Dict]:
    """Search the zvec vector index and return results matching keyword search format.

    Returns list of dicts with: chunk_id, repo, repo_type, path, section, line_start, line_end, score, snippet
    """
    if not vector_index_exists():
        return []

    collection = zvec.open(path=str(VECTOR_INDEX_DIR))

    filter_clauses = []
    if repo_filter:
        clauses = [f"repo = '{r}'" for r in repo_filter]
        filter_clauses.append("(" + " OR ".join(clauses) + ")")
    if repo_type_filter:
        clauses = [f"repo_type = '{t}'" for t in repo_type_filter]
        filter_clauses.append("(" + " OR ".join(clauses) + ")")

    filter_expr = " AND ".join(filter_clauses) if filter_clauses else None

    query_kwargs = {
        "vectors": zvec.VectorQuery("embedding", vector=query_embedding),
        "topk": top_k,
        "output_fields": ["repo", "repo_type", "path", "section", "line_start", "line_end", "content"],
        "include_vector": False,
    }
    if filter_expr:
        query_kwargs["filter"] = filter_expr

    results = collection.query(**query_kwargs)

    rows = []
    for doc in results:
        rows.append(
            {
                "chunk_id": doc.id,
                "repo": doc.field("repo"),
                "repo_type": doc.field("repo_type"),
                "path": doc.field("path"),
                "section": doc.field("section"),
                "line_start": doc.field("line_start"),
                "line_end": doc.field("line_end"),
                "score": round(doc.score, 6),
                "snippet": doc.field("content"),
            }
        )

    return rows


def vector_index_exists() -> bool:
    """Check whether the vector index directory exists and is non-empty."""
    return VECTOR_INDEX_DIR.exists() and any(VECTOR_INDEX_DIR.iterdir())


def apply_vector_delta(
    delete_ids: List[str],
    upsert_chunks: List[Dict],
    embeddings: Dict[str, List[float]],
) -> Dict:
    """Apply an incremental delta to the existing vector collection.

    Deletes ``delete_ids``, then upserts ``upsert_chunks`` (using ``embeddings``
    keyed by chunk_id), then flushes and optimizes. Returns a small summary
    dict for logging.

    Caller is responsible for ensuring the collection exists and has the
    expected dimension.
    """
    collection = zvec.open(path=str(VECTOR_INDEX_DIR))

    if delete_ids:
        # zvec accepts a list of ids. Chunk to keep memory bounded.
        batch = 1000
        for start in range(0, len(delete_ids), batch):
            collection.delete(ids=delete_ids[start : start + batch])

    upserted = 0
    if upsert_chunks:
        batch = 1000
        for start in range(0, len(upsert_chunks), batch):
            slice_ = upsert_chunks[start : start + batch]
            docs = []
            for chunk in slice_:
                cid = chunk["chunk_id"]
                vec = embeddings.get(cid)
                if vec is None:
                    continue
                docs.append(
                    zvec.Doc(
                        id=cid,
                        vectors={"embedding": vec},
                        fields={
                            "repo": chunk["repo"],
                            "repo_type": chunk.get("repo_type", "spec"),
                            "path": chunk["path"],
                            "section": chunk["section"],
                            "line_start": chunk["line_start"],
                            "line_end": chunk["line_end"],
                            "content": chunk["content"],
                        },
                    )
                )
            if docs:
                collection.upsert(docs)
                upserted += len(docs)
                print(
                    f"\rVector delta: upserted {upserted}/{len(upsert_chunks)} docs",
                    end="",
                    file=sys.stderr,
                    flush=True,
                )

    if upsert_chunks:
        print(file=sys.stderr)

    collection.flush()
    collection.optimize()

    return {
        "deleted": len(delete_ids),
        "upserted": upserted,
        "index_path": str(VECTOR_INDEX_DIR),
    }
