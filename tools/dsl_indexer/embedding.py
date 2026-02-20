import json
import sys
import time
import urllib.error
import urllib.request
from typing import Dict, List

from .vector_config import EMBEDDING_API_URL, EMBEDDING_BATCH_SIZE, EMBEDDING_MODEL


def embed_texts(
    texts: List[str],
    *,
    model: str = EMBEDDING_MODEL,
    api_url: str = EMBEDDING_API_URL,
    batch_size: int = EMBEDDING_BATCH_SIZE,
    max_retries: int = 3,
) -> List[List[float]]:
    """Embed a list of texts via the OpenAI-compatible embeddings API.

    Calls POST /v1/embeddings with batches of `batch_size` texts.
    Retries with exponential backoff on transient errors.
    Prints progress to stderr.
    """
    all_embeddings: List[List[float]] = [[] for _ in texts]
    total = len(texts)

    for start in range(0, total, batch_size):
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

        print(f"\rEmbedding: {end}/{total} chunks ({end * 100 // total}%)", end="", file=sys.stderr, flush=True)

    if total > 0:
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
