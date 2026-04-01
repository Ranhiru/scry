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
from dsl_toolkit.explainer import explain, explain_element  # noqa: E402
from dsl_toolkit.linter import lint  # noqa: E402
from dsl_toolkit.spec_loader import load_spec  # noqa: E402
from dsl_toolkit.validator import validate  # noqa: E402
from dsl_toolkit.xml_parser import parse_xmlspec_xml  # noqa: E402

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
_SPEC = load_spec()


def docs_search(
    query: str,
    top_k: int = 8,
    repo_filter: Optional[List[str]] = None,
    repo_type: Optional[List[str]] = None,
) -> str:
    """Search indexed workspace docs using keyword rank.

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
    """Find real-world implementation examples of Orbit patterns in production repos (Storefront, Widgets, etc.).
    Use this when looking for how Orbit patterns are used in practice.

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


def xmlspec_validate(xml_text: str) -> str:
    """Validate a XmlSpec XML fragment against the design system spec.

    Args:
        xml_text: XmlSpec XML string to validate
    """
    result = parse_xmlspec_xml(xml_text, _SPEC)
    if result.errors:
        out = {
            "valid": False,
            "parse_errors": [
                {"line": e.line, "column": e.column, "message": e.message}
                for e in result.errors
            ],
        }
        return json.dumps(out, ensure_ascii=False)

    vr = validate(result.tree, _SPEC)
    out = {
        "valid": vr.valid,
        "errors": [{"path": e.path, "message": e.message, "rule": e.rule} for e in vr.errors],
        "warnings": [{"path": e.path, "message": e.message, "rule": e.rule} for e in vr.warnings],
    }
    return json.dumps(out, ensure_ascii=False)


def xmlspec_lint(xml_text: str, rules: Optional[List[str]] = None) -> str:
    """Lint a XmlSpec XML fragment for style and deprecation issues.

    Args:
        xml_text: XmlSpec XML string to lint
        rules: Optional list of rule names to run (default: all rules)
    """
    result = parse_xmlspec_xml(xml_text, _SPEC)
    if result.errors:
        return json.dumps(
            {"error": "Parse failed", "details": result.errors[0].message},
            ensure_ascii=False,
        )

    issues = lint(result.tree, _SPEC, rules)
    out = {
        "issues": [
            {"path": i.path, "message": i.message, "rule": i.rule, "severity": i.severity}
            for i in issues
        ],
        "issue_count": len(issues),
    }
    return json.dumps(out, ensure_ascii=False)


def xmlspec_explain(xml_text: str, verbose: bool = False) -> str:
    """Explain a XmlSpec XML fragment in human-readable form.

    Args:
        xml_text: XmlSpec XML string to explain
        verbose: Show all properties including unset ones
    """
    result = parse_xmlspec_xml(xml_text, _SPEC)
    if result.errors:
        return f"Parse error: {result.errors[0].message}"
    return explain(result.tree, _SPEC, verbose=verbose)


def xmlspec_explain_element(element_name: str, verbose: bool = False) -> str:
    """Describe an element type from the XmlSpec design system spec.

    Args:
        element_name: Element name (case-insensitive), e.g. 'Button', 'Text', 'Stack'
        verbose: Show full property details including defaults and all enum values
    """
    return explain_element(element_name, _SPEC, verbose=verbose)


def create_mcp(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    streamable_http_path: str = "/mcp",
    include_health: bool = False,
) -> FastMCP:
    mcp = FastMCP(
        "workspace-docs-search",
        host=host,
        port=port,
        streamable_http_path=streamable_http_path,
    )

    mcp.tool()(docs_search)
    mcp.tool()(examples_search)
    mcp.tool()(docs_get_chunk)
    mcp.tool()(docs_status)
    mcp.tool()(xmlspec_validate)
    mcp.tool()(xmlspec_lint)
    mcp.tool()(xmlspec_explain)
    mcp.tool()(xmlspec_explain_element)

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
