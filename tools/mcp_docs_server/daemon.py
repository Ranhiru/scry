#!/usr/bin/env python3

import argparse

from app import create_mcp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the workspace docs MCP daemon over Streamable HTTP")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind")
    parser.add_argument("--path", default="/mcp", help="Streamable HTTP path")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    mcp = create_mcp(
        host=args.host,
        port=args.port,
        streamable_http_path=args.path,
        include_health=True,
    )
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
