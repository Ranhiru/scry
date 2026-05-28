#!/usr/bin/env bash
set -euo pipefail

# Workspace setup
# - Installs MCP server Python deps via uv
# - Reads workspace.yaml for repo list + clone URLs
# - Clones (or pulls) each repo into ./repos/
# - Builds the search index
# Safe to re-run at any time.

WORKSPACE_DIR="$(cd "$(dirname "$0")" && pwd)"

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

if ! command -v uv &>/dev/null; then
  fail "uv not found — install: curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi
ok "uv ($(uv --version 2>&1))"

# ---------- workspace.yaml ----------
if [ ! -f "$WORKSPACE_DIR/workspace.yaml" ]; then
  fail "workspace.yaml not found. Copy workspace.example.yaml -> workspace.yaml and edit it."
  exit 1
fi
ok "workspace.yaml"

# ---------- MCP server venv (needed to parse YAML) ----------
info "Setting up MCP server Python environment"
(
  cd "$WORKSPACE_DIR/tools/mcp_docs_server"
  uv sync
)
ok "MCP server dependencies installed"

VENV_PYTHON="$WORKSPACE_DIR/tools/mcp_docs_server/.venv/bin/python"

# ---------- read repo list ----------
info "Reading repo list from workspace.yaml"
REPO_JSON="$($VENV_PYTHON "$WORKSPACE_DIR/tools/workspace_config.py")"
REPO_COUNT="$(echo "$REPO_JSON" | $VENV_PYTHON -c 'import json,sys; print(len(json.load(sys.stdin)["repos"]))')"
ok "Found $REPO_COUNT repo entries"

# ---------- clone / update repos ----------
info "Syncing repositories in $WORKSPACE_DIR/repos"
mkdir -p "$WORKSPACE_DIR/repos"

# Pipe each entry as "name\turl\tbranch" lines. clone_url may be empty if
# git_host is unset and the entry has no explicit url.
echo "$REPO_JSON" | $VENV_PYTHON -c '
import json, sys
data = json.load(sys.stdin)
for r in data["repos"]:
    print("\t".join([r["name"], r.get("clone_url") or "", r.get("branch") or ""]))
' | while IFS=$'\t' read -r repo clone_url branch; do
  target="$WORKSPACE_DIR/repos/$repo"

  if [ -d "$target/.git" ]; then
    if [ -n "$branch" ]; then
      default_branch="$branch"
    else
      default_branch=$(git -C "$target" remote show origin 2>/dev/null | sed -n 's/.*HEAD branch: //p')
      [ -z "$default_branch" ] && default_branch="main"
    fi
    git -C "$target" checkout --force "$default_branch" 2>/dev/null
    git -C "$target" clean -fd 2>/dev/null
    if git -C "$target" pull --ff-only 2>/dev/null; then
      ok "$repo (updated $default_branch)"
    else
      git -C "$target" reset --hard "origin/$default_branch" 2>/dev/null
      ok "$repo (reset to origin/$default_branch)"
    fi
  else
    if [ -z "$clone_url" ]; then
      warn "$repo — no clone URL (set git_host or repo.url in workspace.yaml); skipping"
      continue
    fi
    info "Cloning $repo from $clone_url ..."
    if git clone "$clone_url" "$target"; then
      if [ -n "$branch" ]; then
        git -C "$target" checkout "$branch" 2>/dev/null || true
      fi
      ok "$repo (cloned)"
    else
      fail "$repo — clone failed (check SSH keys / access)"
    fi
  fi
done

# ---------- build search index ----------
info "Building search index (this may take a minute)"
uv --directory "$WORKSPACE_DIR/tools/mcp_docs_server" run python "$WORKSPACE_DIR/tools/dsl_indexer/index.py" build
ok "Search index built"

# ---------- verify ----------
info "Verifying index"
uv --directory "$WORKSPACE_DIR/tools/mcp_docs_server" run python "$WORKSPACE_DIR/tools/dsl_indexer/index.py" status

# ---------- summary ----------
echo ""
info "Setup complete"
echo ""
echo "  Repos:  $REPO_COUNT (in $WORKSPACE_DIR/repos)"
echo "  Index:  tools/dsl_indexer/data/"
echo ""
echo "  Next steps:"
echo "    - Open the workspace in Claude Code:  cd $WORKSPACE_DIR && claude"
echo "    - The MCP server starts automatically via .mcp.json"
echo "    - Rebuild the index after pulling new changes:  make build"
echo ""
