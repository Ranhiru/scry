#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from typing import Dict, List

if __package__ in (None, ""):
    import sys
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


def cmd_build(_: argparse.Namespace) -> int:
    files = collect_source_files()
    chunks = []
    for path in files:
        chunks.extend(chunk_file(path))

    write_chunks(chunks)
    keyword_index = build_keyword_index([c.to_dict() for c in chunks])
    write_keyword_index(keyword_index)
    meta = {
        "index_version": INDEX_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "workspace_root": str(WORKSPACE_ROOT),
        "source_repos": SOURCE_REPOS,
        "file_count": len(files),
        "chunk_count": len(chunks),
        "mode": "keyword",
    }
    write_meta(meta)
    print(json.dumps(meta, indent=2))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    index = read_keyword_index()
    if not index:
        raise SystemExit("Index not found. Run `python3 tools/dsl_indexer/index.py build` first.")

    repo_filter = args.repo or []
    rows = search_keyword_index(index=index, query=args.query, top_k=args.top_k, repo_filter=repo_filter)
    for row in rows:
        row["snippet"] = _to_snippet(row["snippet"])

    output = {
        "query": args.query,
        "top_k": args.top_k,
        "repo_filter": repo_filter,
        "result_count": len(rows),
        "results": rows,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    meta = read_meta()
    chunks = read_chunks()
    keyword_index = read_keyword_index()
    doc_count = keyword_index.get("doc_count", 0) if keyword_index else 0

    status = {
        "index_present": bool(keyword_index),
        "meta": meta,
        "chunks_present": len(chunks),
        "doc_count": doc_count,
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

    p_build = sub.add_parser("build", help="Build keyword index")
    p_build.set_defaults(func=cmd_build)

    p_search = sub.add_parser("search", help="Search keyword index")
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
