import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
REPOS_DIR = WORKSPACE_ROOT / "repos"
DATA_DIR = WORKSPACE_ROOT / "tools" / "dsl_indexer" / "data"
CHUNKS_PATH = DATA_DIR / "chunks.jsonl"
KEYWORD_INDEX_PATH = DATA_DIR / "keyword_index.json"
META_PATH = DATA_DIR / "meta.json"
MANIFEST_PATH = DATA_DIR / "manifest.json"
EMBEDDING_CACHE_PATH = DATA_DIR / "embedding_cache.sqlite"

# Allow `import workspace_config` from any indexer module.
_TOOLS_DIR = str(WORKSPACE_ROOT / "tools")
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from workspace_config import load_config  # noqa: E402

_CFG = load_config()

SOURCE_REPOS = [{"name": r.name, "type": r.type} for r in _CFG.repos]
SOURCE_REPO_NAMES: list[str] = [r["name"] for r in SOURCE_REPOS]
REPO_TYPE_MAP: dict[str, str] = {r["name"]: r["type"] for r in SOURCE_REPOS}
WORKSPACE_NAME: str = _CFG.name
CHUNKING = _CFG.chunking

TEXT_EXTENSIONS = {
    ".md",
    ".mdx",
    ".txt",
    ".rst",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".config",
    ".cs",
    ".csproj",
    ".sln",
    ".tsx",
    ".ts",
    ".jsx",
    ".js",
    ".py",
    ".sh",
    ".xml",
}

EXCLUDED_DIR_NAMES = {
    ".git",
    "node_modules",
    ".next",
    "dist",
    "build",
    "bin",
    "obj",
    ".pnpm",
    ".cache",
    "coverage",
}

EXCLUDED_FILE_NAMES = {
    "pnpm-lock.yaml",
    "yarn.lock",
    "package-lock.json",
}

EXCLUDED_FILE_PATTERNS = {
    "secret",
    "credential",
    "credentials",
    ".env",
    ".secret",
}

EXCLUDED_FILE_EXACT = {
    "appsettings.development.json",
    "appsettings.local.json",
    "appsettings.production.json",
    "local.settings.json",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
    "credentials.json",
    "service-account.json",
    ".npmrc",
    ".pypirc",
}

MAX_FILE_BYTES = 512_000
SNIPPET_MAX_CHARS = 260
# 1.2.0: chunk spans derive from byte offsets, rotating every chunk_id.
INDEX_VERSION = "1.2.0"
