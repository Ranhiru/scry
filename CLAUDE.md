# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Workspace Is

A generic, multi-repo RAG (Retrieval-Augmented Generation) toolkit. Clones a set of repos listed in `workspace.yaml`, builds a hybrid keyword + vector index across their contents, and exposes search via a local MCP server / CLI / daemon.

## Common Commands

```bash
# First-time setup (uv venv, clone repos, build index)
make setup

# Rebuild the index after pulling new changes
make build
make build-keyword-only   # skip embeddings
make build-vector-only    # skip BM25

# CLI (installed by `make install-cli` — name comes from workspace.yaml)
<cli-name> search "query"
<cli-name> examples "query"          # search only type=impl repos
<cli-name> get-chunk <chunk_id>
<cli-name> status
<cli-name> tool <tool_name> --args-json '{...}'   # call any registered tool by name
<cli-name> daemon status

# Install the CLI symlink and register the MCP server with Claude/Codex
make install-cli
make link
```

## Configuration: `workspace.yaml`

A single file at the workspace root drives everything:

```yaml
name: scry                       # CLI binary name, vector index name, MCP server name
git_host: git@github.com:my-org  # default clone host (optional)
embeddings:
  api_url: http://localhost:1234/v1/embeddings
  model: text-embedding-nomic-embed-text-v1.5
  dimension: 768
repos:
  - { name: docs-repo, type: spec }
  - { name: app-repo,  type: impl }
```

- `type` is either `spec` (docs/design/API specs) or `impl` (real-world usage code). `examples_search` filters to `type=impl`.
- Per-repo `url` overrides `git_host`; per-repo `branch` pins a non-default branch.
- Copy `workspace.example.yaml` to bootstrap a new workspace.

## Architecture

### Components

- **`tools/dsl_indexer/`** — file collection, chunking (~1100 chars w/ overlap), BM25 (`keyword_index.py`), and HNSW vector index via `zvec` (`vector_index.py`). Embeddings are produced via an OpenAI-compatible `/v1/embeddings` endpoint (`embedding.py`) and cached by content hash in SQLite. Incremental rebuilds use a manifest diff.
- **`tools/mcp_docs_server/`** — FastMCP server (`app.py`), Streamable HTTP daemon (`daemon.py`), and the CLI (`cli.py`). All three share `create_mcp()`, which loads `workspace.yaml` and registers the four built-in tools.
- **`tools/workspace_config.py`** — single source of truth for config; exposes a typed dataclass via `load_config()`.

### Built-in MCP tools

- `docs_search(query, top_k, repo_filter, repo_type)` — hybrid vector→keyword fallback.
- `examples_search(query, top_k, repo_filter)` — same as `docs_search` but pinned to `type=impl`.
- `docs_get_chunk(chunk_id)` — return full text + metadata for a hit.
- `docs_status()` — index metadata and readiness.

Each has a dedicated CLI subcommand, and any registered tool is also callable by name with raw JSON arguments:

```bash
<cli-name> tool docs_search --args-json '{"query": "auth", "top_k": 3}'
```

## Key Conventions

- **Search before inference.** Query the index before answering questions about indexed repos.
- **Cite sources.** Include file path and line range: `repos/some-repo/path/file.md:42`.
- **Prefer source over generated.** Use `src/`, `docs/`, `specs/`, `tools/` — not `node_modules/`, `.next/`, `build/`, `dist/`.
- **Workspace config drives behavior.** Renaming the CLI, changing the embedding model, or adding/removing repos is a `workspace.yaml` edit followed by `make build`.

## Prerequisites

- `git`, `python3` (3.10+), `uv` (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- An OpenAI-compatible embeddings endpoint (LM Studio, Ollama, llama-server, vLLM, OpenAI API, etc.) reachable at `embeddings.api_url`.
- Optional: `claude` CLI, `codex` (for `make link`).
