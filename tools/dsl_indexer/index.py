#!/usr/bin/env python3
import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

if __package__ in (None, ""):
    from pathlib import Path

    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from dsl_indexer import embedding_cache, manifest as manifest_mod
    from dsl_indexer.chunk import chunk_file
    from dsl_indexer.collect import collect_source_files
    from dsl_indexer.config import (
        EMBEDDING_CACHE_PATH,
        INDEX_VERSION,
        MANIFEST_PATH,
        SNIPPET_MAX_CHARS,
        SOURCE_REPO_NAMES,
        WORKSPACE_ROOT,
    )
    from dsl_indexer.keyword_index import build_keyword_index, search_keyword_index
    from dsl_indexer.storage import (
        read_chunks,
        read_keyword_index,
        read_manifest,
        read_meta,
        write_chunk_dicts,
        write_chunks,
        write_keyword_index,
        write_manifest,
        write_meta,
    )
    from dsl_indexer.vector_config import EMBEDDING_DIMENSION, EMBEDDING_MODEL, VECTOR_INDEX_DIR
else:
    from . import embedding_cache, manifest as manifest_mod
    from .chunk import chunk_file
    from .collect import collect_source_files
    from .config import (
        EMBEDDING_CACHE_PATH,
        INDEX_VERSION,
        MANIFEST_PATH,
        SNIPPET_MAX_CHARS,
        SOURCE_REPO_NAMES,
        WORKSPACE_ROOT,
    )
    from .keyword_index import build_keyword_index, search_keyword_index
    from .storage import (
        read_chunks,
        read_keyword_index,
        read_manifest,
        read_meta,
        write_chunk_dicts,
        write_chunks,
        write_keyword_index,
        write_manifest,
        write_meta,
    )
    from .vector_config import EMBEDDING_DIMENSION, EMBEDDING_MODEL, VECTOR_INDEX_DIR


def _import_vector_modules():
    """Lazily import vector modules, handling both package and direct-run modes."""
    if __package__ in (None, ""):
        from dsl_indexer.embedding import embed_chunks_cached, embed_texts
        from dsl_indexer.vector_index import (
            apply_vector_delta,
            build_vector_index,
            search_vector_index,
            vector_index_exists,
        )
    else:
        from .embedding import embed_chunks_cached, embed_texts
        from .vector_index import (
            apply_vector_delta,
            build_vector_index,
            search_vector_index,
            vector_index_exists,
        )
    return embed_texts, embed_chunks_cached, build_vector_index, apply_vector_delta, search_vector_index, vector_index_exists


def cmd_build(args: argparse.Namespace) -> int:
    skip_vectors = getattr(args, "skip_vectors", False)
    skip_keyword = getattr(args, "skip_keyword", False)
    full = getattr(args, "full", False)
    yes = getattr(args, "yes", False)

    if skip_vectors and skip_keyword:
        print("ERROR: Cannot skip both keyword and vector indexes.", file=sys.stderr)
        return 1

    manifest = read_manifest()
    prior_meta = read_meta()
    schema_reason = _schema_invalidation_reason(prior_meta)

    needs_full = full or not manifest or schema_reason is not None
    user_requested_full = full

    if user_requested_full:
        if not _confirm_full_rebuild(yes):
            print("Aborted.", file=sys.stderr)
            return 1
    elif schema_reason is not None:
        print(f"Schema invalidation ({schema_reason}); running full rebuild.", file=sys.stderr)
    elif not manifest:
        print("No manifest found; running one-time full rebuild to establish baseline.", file=sys.stderr)

    if needs_full:
        return _run_full_build(skip_vectors=skip_vectors, skip_keyword=skip_keyword, schema_reason=schema_reason)

    return _run_incremental_build(
        manifest=manifest,
        prior_meta=prior_meta,
        skip_vectors=skip_vectors,
        skip_keyword=skip_keyword,
    )


def _confirm_full_rebuild(yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        print(
            "ERROR: --full requires an interactive terminal or --yes. Refusing to wipe artifacts non-interactively.",
            file=sys.stderr,
        )
        return False
    print(
        "This will delete data/vector_index, data/chunks.jsonl, the manifest, "
        "and the embedding cache, then rebuild from scratch.",
        file=sys.stderr,
    )
    response = input("Type 'yes' to continue: ").strip().lower()
    return response == "yes"


def _schema_invalidation_reason(meta: Dict) -> Optional[str]:
    if not meta:
        return None
    if meta.get("index_version") != INDEX_VERSION:
        return f"index_version {meta.get('index_version')} -> {INDEX_VERSION}"
    if meta.get("embedding_model") and meta["embedding_model"] != EMBEDDING_MODEL:
        return f"embedding_model {meta['embedding_model']} -> {EMBEDDING_MODEL}"
    if meta.get("embedding_dimension") and int(meta["embedding_dimension"]) != EMBEDDING_DIMENSION:
        return f"embedding_dimension {meta['embedding_dimension']} -> {EMBEDDING_DIMENSION}"
    return None


def _run_full_build(*, skip_vectors: bool, skip_keyword: bool, schema_reason: Optional[str]) -> int:
    """Destructive rebuild: chunks, vector index, keyword index, manifest, embedding cache."""
    if schema_reason is not None or _should_wipe_cache():
        # Drop stale rows that can't help us anymore.
        purged = embedding_cache.purge_stale()
        if purged:
            print(f"Embedding cache: purged {purged} stale rows", file=sys.stderr)

    print("Collecting source files...", file=sys.stderr, flush=True)
    files = collect_source_files()
    total_files = len(files)
    print(f"Collected {total_files} files. Chunking...", file=sys.stderr, flush=True)

    chunks = []
    chunks_by_path: Dict[str, List[str]] = {}
    for i, path in enumerate(files, 1):
        file_chunks = chunk_file(path)
        chunks.extend(file_chunks)
        for ch in file_chunks:
            chunks_by_path.setdefault(ch.path, []).append(ch.chunk_id)
        if i % 500 == 0 or i == total_files:
            pct = (i * 100 // total_files) if total_files else 100
            print(f"\rChunking: {i}/{total_files} files ({pct}%)", end="", file=sys.stderr, flush=True)
    print(f"\nCreated {len(chunks)} chunks.", file=sys.stderr, flush=True)

    print("Writing chunks...", file=sys.stderr, flush=True)
    write_chunks(chunks)
    chunk_dicts = [c.to_dict() for c in chunks]

    modes: List[str] = []

    if not skip_keyword:
        keyword_index = build_keyword_index(chunk_dicts)
        print("Writing keyword index...", file=sys.stderr, flush=True)
        write_keyword_index(keyword_index)
        print("Keyword index built.", file=sys.stderr, flush=True)
        modes.append("keyword")

    if not skip_vectors:
        try:
            _, embed_chunks_cached, build_vector_index, _, _, _ = _import_vector_modules()
            if VECTOR_INDEX_DIR.exists():
                shutil.rmtree(VECTOR_INDEX_DIR)
            print("Building vector index...", file=sys.stderr, flush=True)
            embeddings = embed_chunks_cached(chunk_dicts)
            vec_meta = build_vector_index(chunk_dicts, embeddings)
            modes.append("vector")
            print(
                f"Vector index built: {vec_meta['doc_count']} docs, {vec_meta['dimension']}D",
                file=sys.stderr,
                flush=True,
            )
        except Exception as exc:
            print(f"WARNING: Vector index build failed: {exc}", file=sys.stderr)

    # Seed manifest from full rebuild.
    files_by_key: Dict[str, manifest_mod.FileEntry] = {}
    for path in files:
        repo, key = manifest_mod.repo_and_rel(path)
        chunk_ids = chunks_by_path.get(key, [])
        try:
            entry = manifest_mod.build_entry(path, chunk_ids)
        except OSError:
            continue
        files_by_key[key] = entry
    write_manifest(manifest_mod.serialize(files_by_key))

    # GC the embedding cache against the live content hashes from this build.
    live_hashes = {embedding_cache.hash_content(c["content"]) for c in chunk_dicts}
    removed = embedding_cache.gc(live_hashes)
    if removed:
        print(f"Embedding cache: GC removed {removed} unreferenced rows", file=sys.stderr)

    meta = {
        "index_version": INDEX_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "last_incremental_at": None,
        "workspace_root": str(WORKSPACE_ROOT),
        "source_repos": SOURCE_REPO_NAMES,
        "file_count": len(files),
        "chunk_count": len(chunks),
        "mode": "+".join(modes) if modes else "none",
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimension": EMBEDDING_DIMENSION,
        "rebuild_reason": "user --full" if schema_reason is None else schema_reason,
    }
    write_meta(meta)
    print(json.dumps(meta, indent=2))
    return 0


def _should_wipe_cache() -> bool:
    """Return True if the cache contains rows that can't match the current config."""
    return embedding_cache.stale_row_count() > 0


def _run_incremental_build(
    *,
    manifest: Dict,
    prior_meta: Dict,
    skip_vectors: bool,
    skip_keyword: bool,
) -> int:
    print("Collecting source files...", file=sys.stderr, flush=True)
    files = collect_source_files()
    print(f"Collected {len(files)} files. Diffing against manifest...", file=sys.stderr, flush=True)

    diff = manifest_mod.classify(files, manifest)

    print(
        f"Diff: {len(diff.unchanged)} unchanged, {len(diff.modified)} modified, "
        f"{len(diff.added)} added, {len(diff.deleted)} deleted",
        file=sys.stderr,
    )

    if not diff.has_changes:
        print("No file changes detected.", file=sys.stderr)
        # Still refresh manifest entries that were touched-but-unchanged so we
        # avoid re-hashing them next run.
        files_by_key = {entry.rel_path: entry for entry in diff.unchanged}
        write_manifest(manifest_mod.serialize(files_by_key))
        meta = dict(prior_meta or {})
        meta["last_incremental_at"] = datetime.now(timezone.utc).isoformat()
        meta["file_count"] = len(diff.unchanged)
        write_meta(meta)
        print(json.dumps(meta, indent=2))
        return 0

    # Re-chunk modified and added files.
    new_chunks = []
    new_chunk_ids_by_key: Dict[str, List[str]] = {}
    rechunk_paths = [path for _, path in diff.modified] + list(diff.added)
    for i, path in enumerate(rechunk_paths, 1):
        file_chunks = chunk_file(path)
        new_chunks.extend(file_chunks)
        if file_chunks:
            _, key = manifest_mod.repo_and_rel(path)
            new_chunk_ids_by_key.setdefault(key, []).extend(c.chunk_id for c in file_chunks)
        if i % 100 == 0 or i == len(rechunk_paths):
            print(f"\rRe-chunking: {i}/{len(rechunk_paths)} files", end="", file=sys.stderr, flush=True)
    if rechunk_paths:
        print(file=sys.stderr)
    print(f"Generated {len(new_chunks)} new chunks.", file=sys.stderr)

    new_chunk_dicts = [c.to_dict() for c in new_chunks]

    # Compute the chunk-id deltas.
    obsolete_ids: List[str] = []
    for old_entry, _ in diff.modified:
        obsolete_ids.extend(old_entry.chunk_ids)
    for old_entry in diff.deleted:
        obsolete_ids.extend(old_entry.chunk_ids)
    obsolete_set = set(obsolete_ids)
    new_id_set = {c["chunk_id"] for c in new_chunk_dicts}

    # Merge chunks.jsonl: drop obsolete + drop any colliding ids that the new
    # chunks would replace, then append new chunks.
    print("Merging chunks.jsonl...", file=sys.stderr, flush=True)
    existing = read_chunks()
    kept = [c for c in existing if c["chunk_id"] not in obsolete_set and c["chunk_id"] not in new_id_set]
    merged = kept + new_chunk_dicts
    write_chunk_dicts(merged)
    print(f"chunks.jsonl: {len(existing)} -> {len(merged)}", file=sys.stderr)

    modes: List[str] = []

    # Vector delta.
    if not skip_vectors:
        try:
            _, embed_chunks_cached, build_vector_index, apply_vector_delta, _, vector_index_exists = (
                _import_vector_modules()
            )

            if not vector_index_exists():
                print(
                    "Vector index missing despite manifest present; doing full vector rebuild.",
                    file=sys.stderr,
                )
                if VECTOR_INDEX_DIR.exists():
                    shutil.rmtree(VECTOR_INDEX_DIR)
                embeddings = embed_chunks_cached(merged)
                build_vector_index(merged, embeddings)
            else:
                embeddings = embed_chunks_cached(new_chunk_dicts) if new_chunk_dicts else {}
                summary = apply_vector_delta(
                    delete_ids=list(obsolete_set),
                    upsert_chunks=new_chunk_dicts,
                    embeddings=embeddings,
                )
                print(
                    f"Vector delta applied: deleted={summary['deleted']}, upserted={summary['upserted']}",
                    file=sys.stderr,
                )
            modes.append("vector")
        except Exception as exc:
            print(f"WARNING: Vector delta failed: {exc}", file=sys.stderr)

    # BM25 rebuild from merged set.
    if not skip_keyword:
        print("Rebuilding keyword index from merged chunks...", file=sys.stderr, flush=True)
        keyword_index = build_keyword_index(merged)
        write_keyword_index(keyword_index)
        modes.append("keyword")

    # Update manifest.
    files_by_key: Dict[str, manifest_mod.FileEntry] = {}
    for entry in diff.unchanged:
        files_by_key[entry.rel_path] = entry
    for path in rechunk_paths:
        _, key = manifest_mod.repo_and_rel(path)
        chunk_ids = new_chunk_ids_by_key.get(key, [])
        try:
            entry = manifest_mod.build_entry(path, chunk_ids)
        except OSError:
            continue
        files_by_key[key] = entry
    write_manifest(manifest_mod.serialize(files_by_key))

    # GC embedding cache: drop rows for content no longer in any live chunk.
    live_hashes = {embedding_cache.hash_content(c["content"]) for c in merged}
    removed = embedding_cache.gc(live_hashes)
    if removed:
        print(f"Embedding cache: GC removed {removed} unreferenced rows", file=sys.stderr)

    meta = dict(prior_meta or {})
    meta.update(
        {
            "index_version": INDEX_VERSION,
            "last_incremental_at": datetime.now(timezone.utc).isoformat(),
            "workspace_root": str(WORKSPACE_ROOT),
            "source_repos": SOURCE_REPO_NAMES,
            "file_count": len(files_by_key),
            "chunk_count": len(merged),
            "mode": "+".join(modes) if modes else (prior_meta or {}).get("mode", "none"),
            "embedding_model": EMBEDDING_MODEL,
            "embedding_dimension": EMBEDDING_DIMENSION,
        }
    )
    if "built_at" not in meta:
        meta["built_at"] = meta["last_incremental_at"]
    write_meta(meta)
    print(json.dumps(meta, indent=2))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    repo_filter = args.repo or []
    repo_type_filter = args.repo_type or None

    # Try vector search first, fall back to keyword
    result = load_vector_hits(query=args.query, top_k=args.top_k, repo_filter=repo_filter, repo_type_filter=repo_type_filter)
    if result.get("error"):
        result = load_hits(query=args.query, top_k=args.top_k, repo_filter=repo_filter, repo_type_filter=repo_type_filter)
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
    manifest = read_manifest()
    doc_count = keyword_index.get("doc_count", 0) if keyword_index else 0

    try:
        _, _, _, _, _, vector_index_exists = _import_vector_modules()
        vec_present = vector_index_exists()
    except Exception:
        vec_present = False

    try:
        cache_rows = embedding_cache.row_count() if EMBEDDING_CACHE_PATH.exists() else 0
    except Exception:
        cache_rows = 0

    status = {
        "index_present": bool(keyword_index),
        "meta": meta,
        "chunks_present": len(chunks),
        "doc_count": doc_count,
        "vector_index_present": vec_present,
        "manifest_present": MANIFEST_PATH.exists(),
        "manifest_file_count": len(manifest.get("files", {})) if manifest else 0,
        "embedding_cache_rows": cache_rows,
    }
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


def load_hits(query: str, top_k: int, repo_filter: List[str], repo_type_filter: Optional[List[str]] = None) -> Dict:
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
    rows = search_keyword_index(index=index, query=query, top_k=top_k, repo_filter=repo_filter, repo_type_filter=repo_type_filter)
    for row in rows:
        row["snippet"] = _to_snippet(row["snippet"])
    return {
        "query": query,
        "top_k": top_k,
        "repo_filter": repo_filter,
        "result_count": len(rows),
        "results": rows,
    }


def load_vector_hits(query: str, top_k: int, repo_filter: List[str], repo_type_filter: Optional[List[str]] = None) -> Dict:
    """Embed query and search the vector index. Returns same format as load_hits."""
    try:
        embed_texts, _, _, _, search_vector_index, vector_index_exists = _import_vector_modules()
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

    rows = search_vector_index(query_embedding, top_k=top_k, repo_filter=repo_filter or None, repo_type_filter=repo_type_filter or None)
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

    p_build = sub.add_parser("build", help="Build/update indexes incrementally (use --full to wipe and rebuild)")
    p_build.add_argument("--skip-vectors", action="store_true", help="Skip vector index work")
    p_build.add_argument("--skip-keyword", action="store_true", help="Skip keyword index work")
    p_build.add_argument("--full", action="store_true", help="Destructive rebuild from scratch (requires confirmation)")
    p_build.add_argument("--yes", action="store_true", help="Skip --full confirmation prompt (for scripts)")
    p_build.set_defaults(func=cmd_build)

    p_search = sub.add_parser("search", help="Search index (vector if available, keyword fallback)")
    p_search.add_argument("--query", required=True, help="Search query")
    p_search.add_argument("--top-k", type=int, default=8, help="Max hits")
    p_search.add_argument("--repo", action="append", help="Restrict to repo (repeatable)")
    p_search.add_argument("--repo-type", action="append", help="Restrict to repo type: spec or impl (repeatable)")
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
