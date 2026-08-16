"""Reference plugin showing the contract in `tools/plugin_registry.py`.

Registers one tool, `repo_files`, which reports what the indexer actually
collected for a given repo. The built-in search tools cannot answer that: they
only surface chunks matching a query, so a file that was silently skipped by an
extension filter or a size cap is invisible to them.

Enable it in workspace.yaml:

    plugins:
      example:
        enabled: true
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from workspace_config import WorkspaceConfig

MANIFEST_RELATIVE_PATH = Path("tools") / "dsl_indexer" / "data" / "manifest.json"
MAX_LIMIT = 2000


class Plugin:
    name: str = "example"

    def register(self, mcp: Any, cfg: WorkspaceConfig) -> None:
        manifest_path = cfg.workspace_root / MANIFEST_RELATIVE_PATH
        configured_repos = cfg.repo_names()

        def repo_files(repo: str, limit: int = 200) -> str:
            """List the files the indexer picked up for one repo, with chunk counts.

            Args:
                repo: Repo name as it appears in workspace.yaml
                limit: Maximum number of files to return (1-2000, default 200)
            """
            limit = max(1, min(limit, MAX_LIMIT))

            if not manifest_path.exists():
                return _error(
                    f"No manifest at {manifest_path}. Run `make build` first.",
                    configured_repos=configured_repos,
                )
            try:
                manifest = json.loads(manifest_path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                return _error(f"Could not read manifest: {exc}")

            all_entries: List[Dict[str, Any]] = list(manifest.get("files", {}).values())
            entries = [e for e in all_entries if e.get("repo") == repo]
            if not entries:
                return _error(
                    f"No indexed files for repo {repo!r}",
                    configured_repos=configured_repos,
                    indexed_repos=sorted({str(e.get("repo")) for e in all_entries}),
                )

            entries.sort(key=_chunk_count, reverse=True)
            shown = entries[:limit]
            extensions = Counter(Path(str(e.get("rel_path", ""))).suffix or "(none)" for e in entries)

            return json.dumps(
                {
                    "repo": repo,
                    "repo_type": entries[0].get("repo_type", "spec"),
                    "file_count": len(entries),
                    "chunk_count": sum(_chunk_count(e) for e in entries),
                    "returned": len(shown),
                    "truncated": len(entries) > len(shown),
                    "by_extension": dict(extensions.most_common()),
                    "files": [
                        {
                            "path": e.get("rel_path"),
                            "chunks": _chunk_count(e),
                            "bytes": e.get("size", 0),
                        }
                        for e in shown
                    ],
                },
                ensure_ascii=False,
            )

        mcp.tool()(repo_files)


def _chunk_count(entry: Dict[str, Any]) -> int:
    return len(entry.get("chunk_ids") or [])


def _error(message: str, **extra: Any) -> str:
    return json.dumps({"error": message, **extra}, ensure_ascii=False)
