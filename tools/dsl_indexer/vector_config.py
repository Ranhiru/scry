from .config import DATA_DIR, _CFG

EMBEDDING_API_URL: str = _CFG.embeddings.api_url
EMBEDDING_MODEL: str = _CFG.embeddings.model
EMBEDDING_DIMENSION: int = _CFG.embeddings.dimension
EMBEDDING_BATCH_SIZE: int = _CFG.embeddings.batch_size
EMBEDDING_CONCURRENCY: int = _CFG.embeddings.concurrency
VECTOR_INDEX_DIR = DATA_DIR / "vector_index"
# Collection names must be a valid identifier (no hyphens, dots, etc).
VECTOR_COLLECTION_NAME: str = "".join(
    c if c.isalnum() else "_" for c in _CFG.name
).strip("_") or "workspace_docs"

HNSW_EF_CONSTRUCTION = 200
HNSW_M = 16
