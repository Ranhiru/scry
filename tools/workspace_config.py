"""Workspace-wide configuration loader.

Reads `workspace.yaml` at the workspace root and exposes a typed config
object consumed by the indexer, MCP server, CLI, and setup script.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = WORKSPACE_ROOT / "workspace.yaml"

CHUNK_STRATEGIES = {"text", "markdown", "code"}
PROFILE_KEYS = {"strategy", "target_size", "hard_max_size", "overlap"}


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
class PluginConfig:
    enabled: bool = False
    settings: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChunkProfile:
    strategy: str = "text"
    target_size: int = 1100
    hard_max_size: int = 2200
    overlap: int = 0


@dataclass(frozen=True)
class ChunkingConfig:
    default_profile: str
    profiles: Dict[str, ChunkProfile]
    by_extension: Dict[str, Tuple[str, Optional[str]]]

    def resolve(self, suffix: str) -> Tuple[ChunkProfile, Optional[str]]:
        name, language = self.by_extension.get(suffix, (self.default_profile, None))
        return self.profiles[name], language


DEFAULT_PROFILES = {
    "code": ChunkProfile(strategy="code", target_size=1800, hard_max_size=3600),
    "markdown": ChunkProfile(strategy="markdown", target_size=1400, hard_max_size=2800),
    "text": ChunkProfile(strategy="text", target_size=1100, hard_max_size=2200, overlap=180),
}

DEFAULT_RULES = [
    ([".md", ".mdx"], "markdown", None),
    ([".py"], "code", "python"),
    ([".ts"], "code", "typescript"),
    ([".tsx"], "code", "tsx"),
    ([".js", ".jsx"], "code", "javascript"),
    ([".cs"], "code", "csharp"),
    ([".sh"], "code", "bash"),
]


@dataclass
class WorkspaceConfig:
    name: str
    git_host: Optional[str]
    embeddings: EmbeddingConfig
    repos: List[RepoEntry]
    plugins: Dict[str, PluginConfig]
    chunking: ChunkingConfig = field(default_factory=lambda: _coerce_chunking(None))
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

    def plugin(self, name: str) -> Optional[PluginConfig]:
        return self.plugins.get(name)


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


def _coerce_plugins(raw: Any) -> Dict[str, PluginConfig]:
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"plugins must be a mapping, got {type(raw).__name__}")
    out: Dict[str, PluginConfig] = {}
    for name, settings in raw.items():
        settings = settings or {}
        if not isinstance(settings, dict):
            raise ValueError(f"plugin '{name}' settings must be a mapping")
        enabled = bool(settings.get("enabled", True))
        rest = {k: v for k, v in settings.items() if k != "enabled"}
        out[str(name)] = PluginConfig(enabled=enabled, settings=rest)
    return out


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


def _coerce_profile(name: str, raw: Any, base: Optional[ChunkProfile]) -> ChunkProfile:
    if not isinstance(raw, dict):
        raise ValueError(f"chunking profile '{name}' must be a mapping")
    unknown = set(raw) - PROFILE_KEYS
    if unknown:
        raise ValueError(f"chunking profile '{name}' has unknown keys: {sorted(unknown)}")

    base = base or ChunkProfile()
    strategy = str(raw.get("strategy", base.strategy))
    if strategy not in CHUNK_STRATEGIES:
        raise ValueError(f"chunking profile '{name}' has unknown strategy '{strategy}'")

    target_size = int(raw.get("target_size", base.target_size))
    overlap = int(raw.get("overlap", base.overlap))
    if "hard_max_size" in raw:
        hard_max_size = int(raw["hard_max_size"])
    elif "target_size" in raw:
        hard_max_size = 2 * target_size
    else:
        hard_max_size = base.hard_max_size

    if target_size <= 0 or hard_max_size <= 0:
        raise ValueError(f"chunking profile '{name}' sizes must be positive")
    if hard_max_size < target_size:
        raise ValueError(f"chunking profile '{name}' hard_max_size is below target_size")
    if not 0 <= overlap < target_size:
        raise ValueError(f"chunking profile '{name}' overlap must be >= 0 and < target_size")

    return ChunkProfile(strategy, target_size, hard_max_size, overlap)


def _coerce_rules(raw: Any, profiles: Dict[str, ChunkProfile]) -> Dict[str, Tuple[str, Optional[str]]]:
    if not isinstance(raw, list):
        raise ValueError("chunking.rules must be a list")

    by_extension: Dict[str, Tuple[str, Optional[str]]] = {}
    for rule in raw:
        if not isinstance(rule, dict):
            raise ValueError(f"Invalid chunking rule: {rule!r}")
        name = str(rule.get("profile", ""))
        if name not in profiles:
            raise ValueError(f"chunking rule references unknown profile '{name}'")

        language = rule.get("language")
        is_code = profiles[name].strategy == "code"
        if is_code and not language:
            raise ValueError(f"chunking rule for profile '{name}' requires a 'language'")
        if not is_code and language:
            raise ValueError(f"chunking rule for profile '{name}' must not set 'language'")

        extensions = rule.get("extensions")
        if not isinstance(extensions, list) or not extensions:
            raise ValueError(f"chunking rule for profile '{name}' needs a non-empty 'extensions' list")
        for ext in extensions:
            ext = str(ext).lower()
            if ext in by_extension:
                raise ValueError(f"chunking rule extension '{ext}' is defined twice")
            by_extension[ext] = (name, str(language) if language else None)
    return by_extension


def _coerce_chunking(raw: Any) -> ChunkingConfig:
    raw = raw or {}
    if not isinstance(raw, dict):
        raise ValueError(f"chunking must be a mapping, got {type(raw).__name__}")

    profiles_raw = raw.get("profiles")
    if profiles_raw is None:
        profiles_raw = {}
    if not isinstance(profiles_raw, dict):
        raise ValueError("chunking.profiles must be a mapping")
    profiles = dict(DEFAULT_PROFILES)
    for name, body in profiles_raw.items():
        name = str(name)
        profiles[name] = _coerce_profile(name, body or {}, profiles.get(name))

    default_profile = str(raw.get("default_profile", "text"))
    if default_profile not in profiles:
        raise ValueError(f"chunking.default_profile references unknown profile '{default_profile}'")

    if raw.get("rules") is None:
        by_extension = {ext: (name, lang) for exts, name, lang in DEFAULT_RULES for ext in exts}
    else:
        by_extension = _coerce_rules(raw["rules"], profiles)

    return ChunkingConfig(default_profile, profiles, by_extension)


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
        plugins=_coerce_plugins(raw.get("plugins")),
        chunking=_coerce_chunking(raw.get("chunking")),
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
