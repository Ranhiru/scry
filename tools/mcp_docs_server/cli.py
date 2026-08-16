#!/usr/bin/env python3
"""CLI wrapper for the workspace docs MCP server."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import anyio
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT / "tools"))
from workspace_config import load_config  # noqa: E402

_CFG = load_config()
APP_NAME = _CFG.name
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_MCP_PATH = "/mcp"
STARTUP_TIMEOUT_SECONDS = 10.0
STATE_BASE_DIR = Path(
    os.environ.get("DOCS_CLI_STATE_DIR", str(Path.home() / ".local" / "state" / APP_NAME))
)
VENV_PYTHON = WORKSPACE_ROOT / "tools" / "mcp_docs_server" / ".venv" / "bin" / "python"
DAEMON_SCRIPT = WORKSPACE_ROOT / "tools" / "mcp_docs_server" / "daemon.py"


def workspace_hash() -> str:
    return hashlib.sha256(str(WORKSPACE_ROOT).encode("utf-8")).hexdigest()[:12]


def state_dir() -> Path:
    return STATE_BASE_DIR / workspace_hash()


def metadata_path() -> Path:
    return state_dir() / "daemon.json"


def log_path() -> Path:
    return state_dir() / "daemon.log"


def ensure_state_dir() -> Path:
    path = state_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_metadata() -> dict[str, Any] | None:
    path = metadata_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def write_metadata(metadata: dict[str, Any]) -> None:
    ensure_state_dir()
    metadata_path().write_text(json.dumps(metadata, indent=2) + "\n")


def remove_metadata() -> None:
    path = metadata_path()
    if path.exists():
        path.unlink()


def is_process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_health(metadata: dict[str, Any], timeout: float = 1.0) -> dict[str, Any] | None:
    url = f"{metadata['base_url']}/healthz"
    try:
        with urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None

    if payload.get("workspace_root") != str(WORKSPACE_ROOT):
        return None
    return payload


def daemon_status() -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None]:
    metadata = read_metadata()
    if not metadata:
        return False, None, None
    pid = int(metadata.get("pid", 0))
    if not pid or not is_process_running(pid):
        return False, metadata, None
    health = read_health(metadata)
    return health is not None, metadata, health


def pick_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((DEFAULT_HOST, preferred))
            return preferred
        except OSError:
            sock.bind((DEFAULT_HOST, 0))
            return int(sock.getsockname()[1])


def wait_for_health(metadata: dict[str, Any], process: subprocess.Popen[Any] | None = None) -> None:
    deadline = time.time() + STARTUP_TIMEOUT_SECONDS
    while time.time() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"Daemon exited early with code {process.returncode}. See {log_path()}.")
        if read_health(metadata, timeout=0.5):
            return
        time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for daemon readiness. See {log_path()}.")


def start_daemon() -> dict[str, Any]:
    healthy, metadata, _ = daemon_status()
    if healthy and metadata:
        return metadata

    if not VENV_PYTHON.exists():
        raise RuntimeError(
            f"Missing virtualenv interpreter at {VENV_PYTHON}. Run `uv --directory tools/mcp_docs_server sync` or `make setup`."
        )

    ensure_state_dir()
    port = pick_port(DEFAULT_PORT)
    base_url = f"http://{DEFAULT_HOST}:{port}"
    log_file = log_path().open("a", encoding="utf-8")

    process = subprocess.Popen(
        [str(VENV_PYTHON), str(DAEMON_SCRIPT), "--host", DEFAULT_HOST, "--port", str(port), "--path", DEFAULT_MCP_PATH],
        cwd=str(WORKSPACE_ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_file.close()

    metadata = {
        "workspace_root": str(WORKSPACE_ROOT),
        "pid": process.pid,
        "host": DEFAULT_HOST,
        "port": port,
        "base_url": base_url,
        "mcp_url": f"{base_url}{DEFAULT_MCP_PATH}",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    write_metadata(metadata)
    wait_for_health(metadata, process)
    return metadata


def ensure_daemon() -> dict[str, Any]:
    healthy, metadata, _ = daemon_status()
    if healthy and metadata:
        return metadata
    return start_daemon()


def stop_daemon(force: bool = False) -> bool:
    metadata = read_metadata()
    if not metadata:
        return False

    pid = int(metadata.get("pid", 0))
    if not pid or not is_process_running(pid):
        remove_metadata()
        return False

    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if not is_process_running(pid):
            remove_metadata()
            return True
        time.sleep(0.2)

    if force:
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.2)
        remove_metadata()
        return True

    return False


def _read_file_or_stdin(file_arg: str) -> str:
    if file_arg == "-":
        return sys.stdin.read()
    path = Path(file_arg)
    if not path.exists():
        raise RuntimeError(f"File not found: {file_arg}")
    return path.read_text()


async def _call_tool(metadata: dict[str, Any], name: str, arguments: dict[str, Any]) -> str:
    async with streamable_http_client(metadata["mcp_url"]) as (read_stream, write_stream, _get_session_id):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments=arguments)
            if result.isError:
                raise RuntimeError(result.model_dump_json(indent=2))

            chunks: list[str] = []
            for content in result.content:
                text = getattr(content, "text", None)
                if text is not None:
                    chunks.append(text)

            if chunks:
                return "\n".join(chunks)
            if result.structuredContent is not None:
                return json.dumps(result.structuredContent, ensure_ascii=False)
            return result.model_dump_json(indent=2)


def call_tool(metadata: dict[str, Any], name: str, arguments: dict[str, Any]) -> str:
    clean_arguments = {key: value for key, value in arguments.items() if value is not None}
    return anyio.run(_call_tool, metadata, name, clean_arguments)


def parse_json_payload(payload: str) -> Any | None:
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def format_search_results(parsed: dict[str, Any]) -> str:
    if parsed.get("error"):
        return json.dumps(parsed, indent=2, ensure_ascii=False)

    lines = [
        f"Results: {parsed.get('result_count', 0)}",
        f"Mode: {parsed.get('search_mode', 'unknown')}",
    ]
    for index, result in enumerate(parsed.get("results") or [], start=1):
        lines.append(
            f"{index}. {result.get('path', '(unknown path)')} [{result.get('chunk_id', 'no-chunk-id')}]"
        )
        if result.get("snippet"):
            lines.append(f"   {result['snippet']}")

    results = parsed.get("results") or []
    if results and results[0].get("chunk_id"):
        lines.append("")
        lines.append(f"Next: {APP_NAME} get-chunk {results[0]['chunk_id']}")

    return "\n".join(lines)


def print_payload(payload: str, raw_json: bool) -> None:
    if raw_json:
        print(payload)
        return

    parsed = parse_json_payload(payload)
    if parsed is None:
        print(payload)
        return

    if isinstance(parsed, dict) and parsed.get("results") is not None:
        print(format_search_results(parsed))
        return

    print(json.dumps(parsed, indent=2, ensure_ascii=False))


def command_exit_code(command: str, payload: str) -> int:
    parsed = parse_json_payload(payload)
    if parsed is None:
        return 0

    if isinstance(parsed, dict) and parsed.get("error"):
        return 1

    return 0


def tool_arguments(args: argparse.Namespace) -> dict[str, Any]:
    if args.args_json and args.args_file:
        raise RuntimeError("Use either --args-json or --args-file, not both")

    payload = args.args_json
    if payload is None and args.args_file:
        payload = _read_file_or_stdin(args.args_file)
    if payload is None:
        return {}

    parsed = parse_json_payload(payload)
    if not isinstance(parsed, dict):
        raise RuntimeError("Tool arguments must be a JSON object")
    return parsed


def handle_tool_command(args: argparse.Namespace) -> int:
    metadata = ensure_daemon()

    if args.command == "search":
        query = args.query_value if args.query_value is not None else args.query
        if not query:
            raise RuntimeError("search requires a query")
        tool_name = "docs_search"
        tool_args = {
            "query": query,
            "top_k": args.top_k,
            "repo_filter": args.repo,
            "repo_type": args.repo_type,
        }
    elif args.command == "examples":
        query = args.query_value if args.query_value is not None else args.query
        if not query:
            raise RuntimeError("examples requires a query")
        tool_name = "examples_search"
        tool_args = {
            "query": query,
            "top_k": args.top_k,
            "repo_filter": args.repo,
        }
    elif args.command == "get-chunk":
        tool_name = "docs_get_chunk"
        tool_args = {"chunk_id": args.chunk_id}
    elif args.command == "status":
        tool_name = "docs_status"
        tool_args = {}
    elif args.command == "tool":
        tool_name = args.tool_name
        tool_args = tool_arguments(args)
    else:
        raise RuntimeError(f"Unsupported command: {args.command}")

    payload = call_tool(metadata, tool_name, tool_args)
    print_payload(payload, raw_json=getattr(args, "json", False))
    return command_exit_code(args.command, payload)


def cmd_daemon_start(_args: argparse.Namespace) -> int:
    metadata = ensure_daemon()
    print(json.dumps({"status": "running", **metadata}, indent=2))
    return 0


def cmd_daemon_stop(args: argparse.Namespace) -> int:
    stopped = stop_daemon(force=args.force)
    print("stopped" if stopped else "not running")
    return 0


def cmd_daemon_restart(args: argparse.Namespace) -> int:
    stop_daemon(force=True)
    metadata = start_daemon()
    print(json.dumps({"status": "running", **metadata}, indent=2))
    return 0


def cmd_daemon_status(_args: argparse.Namespace) -> int:
    healthy, metadata, health = daemon_status()
    if not metadata:
        print(json.dumps({"status": "stopped", "workspace_root": str(WORKSPACE_ROOT)}, indent=2))
        return 0

    output = {
        "status": "running" if healthy else "stale",
        **metadata,
        "health": health,
        "log_path": str(log_path()),
    }
    print(json.dumps(output, indent=2))
    return 0 if healthy else 1


def tail_lines(path: Path, count: int) -> str:
    if not path.exists():
        return ""
    lines = path.read_text().splitlines()
    return "\n".join(lines[-count:])


def cmd_daemon_logs(args: argparse.Namespace) -> int:
    output = tail_lines(log_path(), args.tail)
    if output:
        print(output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="Workspace docs CLI backed by a reusable local MCP daemon",
        epilog=(
            "Use `search` for docs, `examples` for implementation usage, `get-chunk` to expand a hit, "
            "`tool` to call any tool by name, and `daemon status` to inspect the local server."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser(
        "search",
        help="Search indexed workspace docs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_search.description = "Search indexed workspace docs."
    p_search.epilog = (
        "Examples:\n"
        f"  {APP_NAME} search \"authentication flow\"\n"
        f"  {APP_NAME} search --query \"rate limiting\" --top-k 3"
    )
    p_search.add_argument("query_value", nargs="?", help="Search query")
    p_search.add_argument("--query", dest="query", help="Search query")
    p_search.add_argument("--top-k", type=int, default=8, help="Max hits")
    p_search.add_argument("--repo", action="append", help="Restrict to repo (repeatable)")
    p_search.add_argument("--repo-type", action="append", help="Restrict to repo type (repeatable)")
    p_search.add_argument("--json", action="store_true", help="Print raw JSON result")
    p_search.set_defaults(func=handle_tool_command)

    p_examples = sub.add_parser(
        "examples",
        help="Search implementation examples only",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_examples.description = "Search implementation examples only (type=impl repos)."
    p_examples.epilog = (
        "Examples:\n"
        f"  {APP_NAME} examples \"request handler\"\n"
        f"  {APP_NAME} examples --query \"event payload shape\" --top-k 5"
    )
    p_examples.add_argument("query_value", nargs="?", help="Search query")
    p_examples.add_argument("--query", dest="query", help="Search query")
    p_examples.add_argument("--top-k", type=int, default=8, help="Max hits")
    p_examples.add_argument("--repo", action="append", help="Restrict to repo (repeatable)")
    p_examples.add_argument("--json", action="store_true", help="Print raw JSON result")
    p_examples.set_defaults(func=handle_tool_command)

    p_chunk = sub.add_parser("get-chunk", help="Fetch a chunk by id")
    p_chunk.add_argument("chunk_id", help="Chunk id")
    p_chunk.add_argument("--json", action="store_true", help="Print raw JSON result")
    p_chunk.set_defaults(func=handle_tool_command)

    p_status = sub.add_parser("status", help="Show index status")
    p_status.add_argument("--json", action="store_true", help="Print raw JSON result")
    p_status.set_defaults(func=handle_tool_command)

    p_tool = sub.add_parser(
        "tool",
        help="Call any MCP tool by name",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_tool.description = (
        "Call any tool registered on the MCP server by name, passing raw JSON "
        "arguments. The dedicated subcommands are friendlier; this is the escape "
        "hatch for arguments they do not expose."
    )
    p_tool.epilog = (
        "Examples:\n"
        f"  {APP_NAME} tool docs_search --args-json '{{\"query\": \"auth\", \"top_k\": 3}}'\n"
        f"  echo '{{\"query\": \"auth\"}}' | {APP_NAME} tool docs_search --args-file -"
    )
    p_tool.add_argument("tool_name", help="Registered MCP tool name")
    p_tool.add_argument("--args-json", help="Tool arguments as a JSON object")
    p_tool.add_argument("--args-file", help="Read JSON arguments from a file, or - for stdin")
    p_tool.add_argument("--json", action="store_true", help="Print raw JSON result")
    p_tool.set_defaults(func=handle_tool_command)

    p_daemon = sub.add_parser("daemon", help="Manage the local daemon")
    daemon_sub = p_daemon.add_subparsers(dest="daemon_command", required=True)

    p_daemon_start = daemon_sub.add_parser("start", help="Start the daemon if needed")
    p_daemon_start.set_defaults(func=cmd_daemon_start)

    p_daemon_stop = daemon_sub.add_parser("stop", help="Stop the daemon")
    p_daemon_stop.add_argument("--force", action="store_true", help="Force kill if needed")
    p_daemon_stop.set_defaults(func=cmd_daemon_stop)

    p_daemon_restart = daemon_sub.add_parser("restart", help="Restart the daemon")
    p_daemon_restart.set_defaults(func=cmd_daemon_restart)

    p_daemon_status = daemon_sub.add_parser("status", help="Show daemon status")
    p_daemon_status.set_defaults(func=cmd_daemon_status)

    p_daemon_logs = daemon_sub.add_parser("logs", help="Show daemon log tail")
    p_daemon_logs.add_argument("--tail", type=int, default=50, help="Number of lines to print")
    p_daemon_logs.set_defaults(func=cmd_daemon_logs)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
