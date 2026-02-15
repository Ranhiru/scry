from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
REPOS_DIR = WORKSPACE_ROOT / "repos"
DATA_DIR = WORKSPACE_ROOT / "tools" / "dsl_indexer" / "data"
CHUNKS_PATH = DATA_DIR / "chunks.jsonl"
KEYWORD_INDEX_PATH = DATA_DIR / "keyword_index.json"
META_PATH = DATA_DIR / "meta.json"

SOURCE_REPOS = [
    "orbit.docs",
    "orbit.web.frontend",
    "orbit.search.core",
    "orbit.design-system",
    "orbit.ui-builder.web",
    "orbit-design-system",
]

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
INDEX_VERSION = "1.0.0"

