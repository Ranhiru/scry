#!/usr/bin/env bash
set -euo pipefail

# Orbit Workspace Setup
# Clones repos (or pulls latest if already cloned), installs MCP server
# dependencies, and builds the search index. Safe to re-run at any time.

WORKSPACE_DIR="$(cd "$(dirname "$0")" && pwd)"
GH_ORG="git@github.com:your-org"

# Read repo list from shared config (skip comments and blank lines)
# Format: repo_name:type — we only need the name for cloning
REPOS=()
while IFS= read -r line; do
  line="${line%%#*}"          # strip inline comments
  line="${line// /}"          # trim spaces
  [[ -z "$line" ]] && continue
  line="${line%%:*}"          # strip :type suffix (e.g. :spec, :impl)
  REPOS+=("$line")
done < "$WORKSPACE_DIR/repos.conf"

# ---------- helpers ----------
info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m  OK\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m  WARN\033[0m %s\n' "$*"; }
fail()  { printf '\033[1;31m  FAIL\033[0m %s\n' "$*"; }

# ---------- prerequisites ----------
info "Checking prerequisites"

if ! command -v git &>/dev/null; then
  fail "git not found — install it first"
  exit 1
fi
ok "git"

if ! command -v python3 &>/dev/null; then
  fail "python3 not found — install Python 3.10+"
  exit 1
fi
ok "python3 ($(python3 --version 2>&1))"

has_uv=false
if command -v uv &>/dev/null; then
  has_uv=true
  ok "uv ($(uv --version 2>&1))"
else
  warn "uv not found — MCP server venv will be skipped (install with: curl -LsSf https://astral.sh/uv/install.sh | sh)"
fi

# ---------- clone / update repos ----------
info "Syncing repositories in $WORKSPACE_DIR/repos"

mkdir -p "$WORKSPACE_DIR/repos"

for repo in "${REPOS[@]}"; do
  target="$WORKSPACE_DIR/repos/$repo"
  if [ -d "$target/.git" ]; then
    # Repo exists — force checkout default branch and pull latest
    default_branch=$(git -C "$target" remote show origin 2>/dev/null | sed -n 's/.*HEAD branch: //p')
    if [ -z "$default_branch" ]; then
      default_branch="main"
    fi
    git -C "$target" checkout --force "$default_branch" 2>/dev/null
    git -C "$target" clean -fd 2>/dev/null
    if git -C "$target" pull --ff-only 2>/dev/null; then
      ok "$repo (updated $default_branch)"
    else
      # ff-only failed — reset to origin
      git -C "$target" reset --hard "origin/$default_branch" 2>/dev/null
      ok "$repo (reset to origin/$default_branch)"
    fi
  else
    info "Cloning $repo ..."
    if git clone "$GH_ORG/$repo.git" "$target"; then
      ok "$repo (cloned)"
    else
      fail "$repo — clone failed (check SSH keys / access)"
    fi
  fi
done

# ---------- MCP server venv ----------
if $has_uv; then
  info "Setting up MCP server Python environment"
  (
    cd "$WORKSPACE_DIR/tools/mcp_docs_server"
    uv sync
  )
  ok "MCP server dependencies installed"
else
  warn "Skipping MCP server venv (uv not available)"
fi

# ---------- build search index ----------
info "Building search index (this may take a minute)"

if $has_uv; then
  uv --directory "$WORKSPACE_DIR/tools/mcp_docs_server" run python "$WORKSPACE_DIR/tools/dsl_indexer/index.py" build
else
  warn "uv not available — building keyword index only (vector index requires uv)"
  python3 "$WORKSPACE_DIR/tools/dsl_indexer/index.py" build --skip-vectors
fi

ok "Search index built"

# ---------- verify ----------
info "Verifying index"
if $has_uv; then
  uv --directory "$WORKSPACE_DIR/tools/mcp_docs_server" run python "$WORKSPACE_DIR/tools/dsl_indexer/index.py" status
else
  python3 "$WORKSPACE_DIR/tools/dsl_indexer/index.py" status
fi

# ---------- summary ----------
echo ""
info "Setup complete"
echo ""
echo "  Repos:  ${#REPOS[@]} (in $WORKSPACE_DIR/repos)"
echo "  Index:  tools/dsl_indexer/data/"
echo ""
echo "  Next steps:"
echo "    - Open the workspace in Claude Code:  cd $WORKSPACE_DIR && claude"
echo "    - The MCP server starts automatically via .mcp.json"
echo "    - Rebuild the index after pulling new changes:  make build"
echo ""
