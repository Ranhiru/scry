# scry

A generic, multi-repo RAG toolkit. Point it at a set of git repositories, and it
clones them, builds a hybrid keyword + vector index over their contents, and
exposes search through an MCP server, a CLI, and a local daemon.

Useful when a coding agent needs to answer questions grounded in several repos —
specs, design docs, and real implementation code — instead of guessing.

## How it works

1. `workspace.yaml` lists the repos, the embeddings endpoint, and the CLI name.
2. `setup.sh` clones/pulls each repo into `./repos/`.
3. The indexer collects files, chunks them (~1100 chars with overlap), and
   builds a BM25 keyword index plus an HNSW vector index.
4. The MCP server answers queries vector-first, falling back to keyword search.

Embeddings come from any OpenAI-compatible `/v1/embeddings` endpoint (LM Studio,
Ollama, llama-server, vLLM, the OpenAI API) and are cached by content hash, so
rebuilds only pay for changed chunks.

## Prerequisites

- `git`, `python3` (3.10+), and [`uv`](https://astral.sh/uv)
- An embeddings endpoint reachable at `embeddings.api_url`
- Optional: the `claude` or `codex` CLI, for `make link`

Run `make check` to verify.

## Getting started

```bash
cp workspace.example.yaml workspace.yaml   # then edit it
make setup                                 # venv, clone repos, build index
make install-cli                           # symlink the CLI into ~/.local/bin
make link                                  # register the MCP server
```

`workspace.yaml` is gitignored — each checkout defines its own workspace.

## Configuration

```yaml
name: scry                       # CLI binary, index, and MCP server name
git_host: git@github.com:my-org  # default clone host
embeddings:
  api_url: http://localhost:1234/v1/embeddings
  model: text-embedding-nomic-embed-text-v1.5
  dimension: 768
repos:
  - { name: docs-repo, type: spec }
  - { name: app-repo,  type: impl }
```

Each repo is `spec` (docs, design, API surfaces) or `impl` (real-world usage
code). `examples_search` searches only `impl` repos. A repo may override the
clone URL with `url` and pin a branch with `branch`.

See `workspace.example.yaml` for the fully annotated version.

## Usage

The CLI is named after `name:` in `workspace.yaml` — `scry` by default.

```bash
scry search "how is auth configured"
scry examples "retry policy"          # impl repos only
scry get-chunk <chunk_id>
scry status
scry daemon status
scry tool docs_search --args-json '{"query": "auth", "top_k": 3}'
```

Add `--json` to any command for raw output, `--top-k` to widen a search, and
`--repo` (repeatable) to narrow it.

### Rebuilding

```bash
make build                # full rebuild (incremental via manifest diff)
make build-keyword-only   # skip embeddings
make build-vector-only    # skip BM25
```

## MCP tools

| Tool | Purpose |
| --- | --- |
| `docs_search(query, top_k, repo_filter, repo_type)` | Hybrid search across all repos |
| `examples_search(query, top_k, repo_filter)` | Same, pinned to `type=impl` |
| `docs_get_chunk(chunk_id)` | Full text and metadata for a hit |
| `docs_status()` | Index metadata and readiness |

Each has a dedicated CLI subcommand; `scry tool <name>` calls any of them
directly with raw JSON arguments.

## Layout

```
tools/dsl_indexer/         file collection, chunking, BM25 + vector index
tools/mcp_docs_server/     FastMCP server, HTTP daemon, CLI
tools/workspace_config.py  config loading (single source of truth)
docs/design/               design notes
```

## Tests

```bash
make test
```

## License

MIT — see [LICENSE](LICENSE).
