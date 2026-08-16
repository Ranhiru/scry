"""Workspace-wide configuration loader.

Reads `workspace.yaml` at the workspace root and exposes a typed config
object consumed by the indexer, MCP server, CLI, and setup script.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = WORKSPACE_ROOT / "workspace.yaml"


@dataclass
class EmbeddingConfig:
    api_url: str = "http://localhost:1234/v1/embeddings"
    model: str = "text-embedding-nomic-embed-text-v1.5"
    dimension: int = 768
    batch_size: int = 64
    concurrency: int = 4


@dataclass
class RepoEntry:
    name: str
    type: str = "spec"
    url: Optional[str] = None
    branch: Optional[str] = None


@dataclass
class WorkspaceConfig:
    name: str
    git_host: Optional[str]
    embeddings: EmbeddingConfig
    repos: List[RepoEntry]
    workspace_root: Path = WORKSPACE_ROOT

    def repo_names(self) -> List[str]:
        return [r.name for r in self.repos]

    def repo_type_map(self) -> Dict[str, str]:
        return {r.name: r.type for r in self.repos}

    def clone_url(self, repo: RepoEntry) -> Optional[str]:
        if repo.url:
            return repo.url
        if self.git_host:
            return f"{self.git_host}/{repo.name}.git"
        return None


def _require_yaml() -> Any:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML is required to read workspace.yaml. Run "
            "`uv --directory tools/mcp_docs_server sync` or "
            "`pip install pyyaml`."
        ) from exc
    return yaml


def _coerce_repo(entry: Any) -> RepoEntry:
    if isinstance(entry, str):
        return RepoEntry(name=entry)
    if not isinstance(entry, dict) or "name" not in entry:
        raise ValueError(f"Invalid repo entry: {entry!r}")
    return RepoEntry(
        name=str(entry["name"]),
        type=str(entry.get("type", "spec")),
        url=entry.get("url"),
        branch=entry.get("branch"),
    )


def _coerce_embeddings(raw: Any) -> EmbeddingConfig:
    raw = raw or {}
    defaults = EmbeddingConfig()
    return EmbeddingConfig(
        api_url=str(raw.get("api_url", defaults.api_url)),
        model=str(raw.get("model", defaults.model)),
        dimension=int(raw.get("dimension", defaults.dimension)),
        batch_size=int(raw.get("batch_size", defaults.batch_size)),
        concurrency=int(raw.get("concurrency", defaults.concurrency)),
    )


@lru_cache(maxsize=1)
def load_config(path: Optional[Path] = None) -> WorkspaceConfig:
    cfg_path = path or CONFIG_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"Workspace config not found at {cfg_path}. "
            "Copy workspace.example.yaml to workspace.yaml and edit it."
        )

    yaml = _require_yaml()
    raw = yaml.safe_load(cfg_path.read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"workspace.yaml must be a mapping, got {type(raw).__name__}")

    name = raw.get("name")
    if not name:
        raise ValueError("workspace.yaml is missing required field 'name'")

    repos_raw = raw.get("repos") or []
    if not isinstance(repos_raw, list):
        raise ValueError("workspace.yaml 'repos' must be a list")
    repos = [_coerce_repo(r) for r in repos_raw]

    return WorkspaceConfig(
        name=str(name),
        git_host=raw.get("git_host"),
        embeddings=_coerce_embeddings(raw.get("embeddings")),
        repos=repos,
    )


def _dump_for_shell() -> int:
    """Print the config as JSON for shell consumers (setup.sh)."""
    try:
        cfg = load_config()
    except Exception as exc:
        print(f"workspace_config: {exc}", file=sys.stderr)
        return 1

    payload = {
        "name": cfg.name,
        "git_host": cfg.git_host,
        "repos": [
            {
                "name": r.name,
                "type": r.type,
                "url": r.url,
                "branch": r.branch,
                "clone_url": cfg.clone_url(r),
            }
            for r in cfg.repos
        ],
    }
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(_dump_for_shell())
