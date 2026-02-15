import json
import sys
from pathlib import Path
from typing import List, Optional

from mcp.server.fastmcp import FastMCP

sys.path.append(str(Path(__file__).resolve().parents[1]))
from dsl_indexer.index import get_chunk, load_hits  # noqa: E402
from dsl_indexer.storage import read_meta  # noqa: E402
from dsl_toolkit.spec_loader import load_spec  # noqa: E402
from dsl_toolkit.xml_parser import parse_xmlspec_xml  # noqa: E402
from dsl_toolkit.validator import validate  # noqa: E402
from dsl_toolkit.linter import lint  # noqa: E402
from dsl_toolkit.explainer import explain, explain_element  # noqa: E402

mcp = FastMCP("workspace-docs-search")

_spec = load_spec()


@mcp.tool()
def docs_search(query: str, top_k: int = 8, repo_filter: Optional[List[str]] = None) -> str:
    """Search indexed workspace docs using keyword rank.

    Args:
        query: Search query text
        top_k: Maximum number of results to return (1-50, default 8)
        repo_filter: Optional repo names to restrict results to
    """
    top_k = max(1, min(top_k, 50))
    result = load_hits(query=query, top_k=top_k, repo_filter=repo_filter or [])
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def docs_get_chunk(chunk_id: str) -> str:
    """Get the full text and metadata for a chunk id.

    Args:
        chunk_id: The chunk identifier returned from docs_search results
    """
    result = get_chunk(chunk_id=chunk_id)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def docs_status() -> str:
    """Get index metadata and readiness."""
    result = read_meta()
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def xmlspec_validate(xml_text: str) -> str:
    """Validate a XmlSpec XML fragment against the design system spec.

    Args:
        xml_text: XmlSpec XML string to validate
    """
    result = parse_xmlspec_xml(xml_text, _spec)
    if result.errors:
        out = {
            "valid": False,
            "parse_errors": [
                {"line": e.line, "column": e.column, "message": e.message}
                for e in result.errors
            ],
        }
        return json.dumps(out, ensure_ascii=False)

    vr = validate(result.tree, _spec)
    out = {
        "valid": vr.valid,
        "errors": [
            {"path": e.path, "message": e.message, "rule": e.rule}
            for e in vr.errors
        ],
        "warnings": [
            {"path": e.path, "message": e.message, "rule": e.rule}
            for e in vr.warnings
        ],
    }
    return json.dumps(out, ensure_ascii=False)


@mcp.tool()
def xmlspec_lint(xml_text: str, rules: Optional[List[str]] = None) -> str:
    """Lint a XmlSpec XML fragment for style and deprecation issues.

    Args:
        xml_text: XmlSpec XML string to lint
        rules: Optional list of rule names to run (default: all rules)
    """
    result = parse_xmlspec_xml(xml_text, _spec)
    if result.errors:
        return json.dumps(
            {"error": "Parse failed", "details": result.errors[0].message},
            ensure_ascii=False,
        )

    issues = lint(result.tree, _spec, rules)
    out = {
        "issues": [
            {"path": i.path, "message": i.message, "rule": i.rule, "severity": i.severity}
            for i in issues
        ],
        "issue_count": len(issues),
    }
    return json.dumps(out, ensure_ascii=False)


@mcp.tool()
def xmlspec_explain(xml_text: str, verbose: bool = False) -> str:
    """Explain a XmlSpec XML fragment in human-readable form.

    Args:
        xml_text: XmlSpec XML string to explain
        verbose: Show all properties including unset ones
    """
    result = parse_xmlspec_xml(xml_text, _spec)
    if result.errors:
        return f"Parse error: {result.errors[0].message}"
    return explain(result.tree, _spec, verbose=verbose)


@mcp.tool()
def xmlspec_explain_element(element_name: str, verbose: bool = False) -> str:
    """Describe an element type from the XmlSpec design system spec.

    Args:
        element_name: Element name (case-insensitive), e.g. 'Button', 'Text', 'Stack'
        verbose: Show full property details including defaults and all enum values
    """
    return explain_element(element_name, _spec, verbose=verbose)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
