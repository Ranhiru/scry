from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
REPOS_DIR = WORKSPACE_ROOT / "repos"
DATA_DIR = WORKSPACE_ROOT / "tools" / "dsl_indexer" / "data"
CHUNKS_PATH = DATA_DIR / "chunks.jsonl"
KEYWORD_INDEX_PATH = DATA_DIR / "keyword_index.json"
META_PATH = DATA_DIR / "meta.json"
MANIFEST_PATH = DATA_DIR / "manifest.json"
EMBEDDING_CACHE_PATH = DATA_DIR / "embedding_cache.sqlite"


def _load_repos() -> list[dict]:
    """Read repo entries from the shared repos.conf file.

    Format: ``repo_name:type`` where *type* is ``spec`` or ``impl``.
    If the type suffix is omitted the repo defaults to ``spec``.
    """
    conf = WORKSPACE_ROOT / "repos.conf"
    repos: list[dict] = []
    for line in conf.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" in line:
            name, repo_type = line.rsplit(":", 1)
        else:
            name, repo_type = line, "spec"
        repos.append({"name": name.strip(), "type": repo_type.strip()})
    return repos


SOURCE_REPOS = _load_repos()
SOURCE_REPO_NAMES: list[str] = [r["name"] for r in SOURCE_REPOS]
REPO_TYPE_MAP: dict[str, str] = {r["name"]: r["type"] for r in SOURCE_REPOS}

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
CHUNK_TARGET_CHARS = 1100
CHUNK_OVERLAP_CHARS = 180
SNIPPET_MAX_CHARS = 260
INDEX_VERSION = "1.1.0"

