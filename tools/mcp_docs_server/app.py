import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

sys.path.append(str(Path(__file__).resolve().parents[1]))
from dsl_indexer.index import get_chunk, load_hits, load_vector_hits  # noqa: E402
from dsl_indexer.storage import read_meta  # noqa: E402
from plugin_registry import discover_plugins  # noqa: E402
from workspace_config import load_config  # noqa: E402

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


def docs_search(
    query: str,
    top_k: int = 8,
    repo_filter: Optional[List[str]] = None,
    repo_type: Optional[List[str]] = None,
) -> str:
    """Search indexed workspace docs using vector + keyword rank.

    Args:
        query: Search query text
        top_k: Maximum number of results to return (1-50, default 8)
        repo_filter: Optional repo names to restrict results to
        repo_type: Optional repo types to restrict results to (e.g. ["spec"] or ["impl"])
    """
    top_k = max(1, min(top_k, 50))
    rf = repo_filter or []
    rtf = repo_type or None
    result = load_vector_hits(query=query, top_k=top_k, repo_filter=rf, repo_type_filter=rtf)
    if result.get("error"):
        result = load_hits(query=query, top_k=top_k, repo_filter=rf, repo_type_filter=rtf)
        result["search_mode"] = "keyword"
    else:
        result["search_mode"] = "vector"
    return json.dumps(result, ensure_ascii=False)


def examples_search(query: str, top_k: int = 8, repo_filter: Optional[List[str]] = None) -> str:
    """Find real-world implementation examples by searching only repos tagged with `type: impl`.

    Use this when you want concrete usage code rather than documentation/specs.

    Args:
        query: Search query text
        top_k: Maximum number of results to return (1-50, default 8)
        repo_filter: Optional repo names to restrict within implementation repos
    """
    top_k = max(1, min(top_k, 50))
    rf = repo_filter or []
    rtf = ["impl"]
    result = load_vector_hits(query=query, top_k=top_k, repo_filter=rf, repo_type_filter=rtf)
    if result.get("error"):
        result = load_hits(query=query, top_k=top_k, repo_filter=rf, repo_type_filter=rtf)
        result["search_mode"] = "keyword"
    else:
        result["search_mode"] = "vector"
    return json.dumps(result, ensure_ascii=False)


def docs_get_chunk(chunk_id: str) -> str:
    """Get the full text and metadata for a chunk id.

    Args:
        chunk_id: The chunk identifier returned from docs_search results
    """
    result = get_chunk(chunk_id=chunk_id)
    return json.dumps(result, ensure_ascii=False)


def docs_status() -> str:
    """Get index metadata and readiness."""
    result = dict(read_meta())
    try:
        from dsl_indexer.vector_index import vector_index_exists

        result["vector_index_present"] = vector_index_exists()
    except Exception:
        result["vector_index_present"] = False
    return json.dumps(result, ensure_ascii=False)


def _register_core_tools(mcp: FastMCP) -> None:
    mcp.tool()(docs_search)
    mcp.tool()(examples_search)
    mcp.tool()(docs_get_chunk)
    mcp.tool()(docs_status)


def create_mcp(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    streamable_http_path: str = "/mcp",
    include_health: bool = False,
) -> FastMCP:
    cfg = load_config()
    mcp = FastMCP(
        cfg.name,
        host=host,
        port=port,
        streamable_http_path=streamable_http_path,
    )

    _register_core_tools(mcp)

    for plugin in discover_plugins(cfg):
        try:
            plugin.register(mcp, cfg)
        except Exception as exc:
            print(
                f"[mcp_docs_server] plugin {plugin.name!r} failed to register: {exc}",
                file=sys.stderr,
            )

    if include_health:

        @mcp.custom_route("/healthz", methods=["GET"], include_in_schema=False)
        async def healthz(_request):
            return JSONResponse(
                {
                    "status": "ok",
                    "workspace_root": str(WORKSPACE_ROOT),
                    "pid": os.getpid(),
                    "transport_path": streamable_http_path,
                }
            )

    return mcp
