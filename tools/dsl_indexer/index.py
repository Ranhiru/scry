#!/usr/bin/env python3
import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Dict, List

if __package__ in (None, ""):
    from pathlib import Path

    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from dsl_indexer.chunk import chunk_file
    from dsl_indexer.collect import collect_source_files
    from dsl_indexer.config import INDEX_VERSION, SNIPPET_MAX_CHARS, SOURCE_REPOS, WORKSPACE_ROOT
    from dsl_indexer.keyword_index import build_keyword_index, search_keyword_index
    from dsl_indexer.storage import (
        read_chunks,
        read_keyword_index,
        read_meta,
        write_chunks,
        write_keyword_index,
        write_meta,
    )
else:
    from .chunk import chunk_file
    from .collect import collect_source_files
    from .config import INDEX_VERSION, SNIPPET_MAX_CHARS, SOURCE_REPOS, WORKSPACE_ROOT
    from .keyword_index import build_keyword_index, search_keyword_index
    from .storage import (
        read_chunks,
        read_keyword_index,
        read_meta,
        write_chunks,
        write_keyword_index,
        write_meta,
    )


def _import_vector_modules():
    """Lazily import vector modules, handling both package and direct-run modes."""
    if __package__ in (None, ""):
        from dsl_indexer.embedding import embed_texts, embed_chunks
        from dsl_indexer.vector_index import build_vector_index, search_vector_index, vector_index_exists
    else:
        from .embedding import embed_texts, embed_chunks
        from .vector_index import build_vector_index, search_vector_index, vector_index_exists
    return embed_texts, embed_chunks, build_vector_index, search_vector_index, vector_index_exists


def cmd_build(args: argparse.Namespace) -> int:
    print("Collecting source files...", file=sys.stderr, flush=True)
    files = collect_source_files()
    total_files = len(files)
    print(f"Collected {total_files} files. Chunking...", file=sys.stderr, flush=True)
    chunks = []
    for i, path in enumerate(files, 1):
        chunks.extend(chunk_file(path))
        if i % 500 == 0 or i == total_files:
            print(f"\rChunking: {i}/{total_files} files ({i * 100 // total_files}%)", end="", file=sys.stderr, flush=True)
    print(f"\nCreated {len(chunks)} chunks. Building keyword index...", file=sys.stderr, flush=True)

    print("Writing chunks...", file=sys.stderr, flush=True)
    write_chunks(chunks)
    chunk_dicts = [c.to_dict() for c in chunks]
    keyword_index = build_keyword_index(chunk_dicts)
    print("Writing keyword index...", file=sys.stderr, flush=True)
    write_keyword_index(keyword_index)
    print("Keyword index built.", file=sys.stderr, flush=True)

    mode = "keyword"
    skip_vectors = getattr(args, "skip_vectors", False)

    if not skip_vectors:
        try:
            _, embed_chunks, build_vector_index, _, _ = _import_vector_modules()

            print("Building vector index...", file=sys.stderr, flush=True)
            embeddings = embed_chunks(chunk_dicts)
            vec_meta = build_vector_index(chunk_dicts, embeddings)
            mode = "keyword+vector"
            print(f"Vector index built: {vec_meta['doc_count']} docs, {vec_meta['dimension']}D", file=sys.stderr, flush=True)
        except Exception as exc:
            print(f"WARNING: Vector index build failed (keyword index still built): {exc}", file=sys.stderr)

    meta = {
        "index_version": INDEX_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "workspace_root": str(WORKSPACE_ROOT),
        "source_repos": SOURCE_REPOS,
        "file_count": len(files),
        "chunk_count": len(chunks),
        "mode": mode,
    }
    write_meta(meta)
    print(json.dumps(meta, indent=2))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    repo_filter = args.repo or []

    # Try vector search first, fall back to keyword
    result = load_vector_hits(query=args.query, top_k=args.top_k, repo_filter=repo_filter)
    if result.get("error"):
        result = load_hits(query=args.query, top_k=args.top_k, repo_filter=repo_filter)
        result["search_mode"] = "keyword"
    else:
        result["search_mode"] = "vector"

    if result.get("error"):
        raise SystemExit(result["error"])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    meta = read_meta()
    chunks = read_chunks()
    keyword_index = read_keyword_index()
    doc_count = keyword_index.get("doc_count", 0) if keyword_index else 0

    # Check vector index presence
    try:
        _, _, _, _, vector_index_exists = _import_vector_modules()
        vec_present = vector_index_exists()
    except Exception:
        vec_present = False

    status = {
        "index_present": bool(keyword_index),
        "meta": meta,
        "chunks_present": len(chunks),
        "doc_count": doc_count,
        "vector_index_present": vec_present,
    }
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


def load_hits(query: str, top_k: int, repo_filter: List[str]) -> Dict:
    index = read_keyword_index()
    if not index:
        return {
            "query": query,
            "top_k": top_k,
            "repo_filter": repo_filter,
            "result_count": 0,
            "results": [],
            "error": "Index not found. Run build first.",
        }
    rows = search_keyword_index(index=index, query=query, top_k=top_k, repo_filter=repo_filter)
    for row in rows:
        row["snippet"] = _to_snippet(row["snippet"])
    return {
        "query": query,
        "top_k": top_k,
        "repo_filter": repo_filter,
        "result_count": len(rows),
        "results": rows,
    }


def load_vector_hits(query: str, top_k: int, repo_filter: List[str]) -> Dict:
    """Embed query and search the vector index. Returns same format as load_hits."""
    try:
        embed_texts, _, _, search_vector_index, vector_index_exists = _import_vector_modules()
    except ImportError as exc:
        return {
            "query": query,
            "top_k": top_k,
            "repo_filter": repo_filter,
            "result_count": 0,
            "results": [],
            "error": f"Vector search dependencies not available: {exc}",
        }

    if not vector_index_exists():
        return {
            "query": query,
            "top_k": top_k,
            "repo_filter": repo_filter,
            "result_count": 0,
            "results": [],
            "error": "Vector index not found. Run build first (without --skip-vectors).",
        }

    try:
        query_vectors = embed_texts([query])
        query_embedding = query_vectors[0]
    except Exception as exc:
        return {
            "query": query,
            "top_k": top_k,
            "repo_filter": repo_filter,
            "result_count": 0,
            "results": [],
            "error": f"Embedding query failed: {exc}",
        }

    rows = search_vector_index(query_embedding, top_k=top_k, repo_filter=repo_filter or None)
    for row in rows:
        row["snippet"] = _to_snippet(row["snippet"])

    return {
        "query": query,
        "top_k": top_k,
        "repo_filter": repo_filter,
        "result_count": len(rows),
        "results": rows,
    }


def get_chunk(chunk_id: str) -> Dict:
    for row in read_chunks():
        if row.get("chunk_id") == chunk_id:
            return row
    return {}


def _to_snippet(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= SNIPPET_MAX_CHARS:
        return text
    return text[: SNIPPET_MAX_CHARS - 3] + "..."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Workspace DSL indexer and search")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="Build keyword index (and optionally vector index)")
    p_build.add_argument("--skip-vectors", action="store_true", help="Skip vector index build")
    p_build.set_defaults(func=cmd_build)

    p_search = sub.add_parser("search", help="Search index (vector if available, keyword fallback)")
    p_search.add_argument("--query", required=True, help="Search query")
    p_search.add_argument("--top-k", type=int, default=8, help="Max hits")
    p_search.add_argument("--repo", action="append", help="Restrict to repo (repeatable)")
    p_search.set_defaults(func=cmd_search)

    p_status = sub.add_parser("status", help="Get index status")
    p_status.set_defaults(func=cmd_status)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
