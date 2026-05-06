import json
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple

from . import embedding_cache
from .vector_config import (
    EMBEDDING_API_URL,
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_CONCURRENCY,
    EMBEDDING_MODEL,
)


def embed_texts(
    texts: List[str],
    *,
    model: str = EMBEDDING_MODEL,
    api_url: str = EMBEDDING_API_URL,
    batch_size: int = EMBEDDING_BATCH_SIZE,
    max_retries: int = 3,
    concurrency: int = EMBEDDING_CONCURRENCY,
) -> List[List[float]]:
    """Embed a list of texts via the OpenAI-compatible embeddings API.

    Calls POST /v1/embeddings with batches of `batch_size` texts. Up to
    `concurrency` batches run in parallel via a thread pool — urllib releases
    the GIL during socket I/O, so threads are sufficient. Retries with
    exponential backoff on transient errors per batch.
    """
    total = len(texts)
    if total == 0:
        return []

    all_embeddings: List[List[float]] = [[] for _ in texts]
    starts = list(range(0, total, batch_size))

    progress_lock = threading.Lock()
    done = {"count": 0}

    def _run_batch(start: int) -> None:
        end = min(start + batch_size, total)
        batch = texts[start:end]
        payload = json.dumps({"input": batch, "model": model}).encode("utf-8")
        req = urllib.request.Request(
            api_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        result = _request_with_retry(req, max_retries=max_retries)
        data_list = result["data"]
        data_list.sort(key=lambda d: d["index"])
        for i, item in enumerate(data_list):
            all_embeddings[start + i] = item["embedding"]
        with progress_lock:
            done["count"] += end - start
            current = done["count"]
            print(
                f"\rEmbedding: {current}/{total} chunks ({current * 100 // total}%)",
                end="",
                file=sys.stderr,
                flush=True,
            )

    workers = max(1, min(concurrency, len(starts)))
    if workers == 1:
        for start in starts:
            _run_batch(start)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_run_batch, s) for s in starts]
            for fut in as_completed(futures):
                # Surface the first error; remaining futures will be cancelled
                # on context exit (in-flight ones still complete).
                fut.result()

    print(file=sys.stderr)
    return all_embeddings


def embed_chunks(
    chunks: List[Dict],
    **kwargs,
) -> Dict[str, List[float]]:
    """Embed chunks and return a mapping of chunk_id to embedding vector."""
    texts = [chunk["content"] for chunk in chunks]
    vectors = embed_texts(texts, **kwargs)
    return {chunk["chunk_id"]: vec for chunk, vec in zip(chunks, vectors)}


def embed_chunks_cached(
    chunks: List[Dict],
    *,
    model: str = EMBEDDING_MODEL,
    api_url: str = EMBEDDING_API_URL,
    batch_size: int = EMBEDDING_BATCH_SIZE,
) -> Dict[str, List[float]]:
    """Like embed_chunks, but consults the embedding cache for hits.

    Only chunks with no cached vector hit the embeddings API. Newly embedded
    vectors are written back to the cache. Two chunks with identical content
    share a cache entry, so renames and copies cost nothing.
    """
    if not chunks:
        return {}

    hashes = [embedding_cache.hash_content(c["content"]) for c in chunks]
    cached = embedding_cache.get_many(hashes, model=model)

    miss_indices = [i for i, h in enumerate(hashes) if h not in cached]
    miss_texts = [chunks[i]["content"] for i in miss_indices]

    if miss_texts:
        new_vectors = embed_texts(miss_texts, model=model, api_url=api_url, batch_size=batch_size)
        new_items: List[Tuple[str, List[float]]] = []
        seen: Dict[str, List[float]] = {}
        for idx, vec in zip(miss_indices, new_vectors):
            h = hashes[idx]
            cached[h] = vec
            if h not in seen:
                seen[h] = vec
                new_items.append((h, vec))
        embedding_cache.put_many(new_items, model=model)

    print(
        f"Embedding cache: {len(chunks) - len(miss_indices)}/{len(chunks)} hits, "
        f"{len(miss_indices)} embedded",
        file=sys.stderr,
        flush=True,
    )

    return {chunk["chunk_id"]: cached[h] for chunk, h in zip(chunks, hashes)}


def _request_with_retry(req: urllib.request.Request, *, max_retries: int) -> dict:
    """Execute an HTTP request with exponential backoff on transient errors."""
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as exc:
            if attempt == max_retries:
                raise
            if isinstance(exc, urllib.error.HTTPError) and exc.code < 500:
                raise
            wait = 2 ** attempt
            print(f"\nRetry {attempt + 1}/{max_retries} after {wait}s: {exc}", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("Unreachable")
