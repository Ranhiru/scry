# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commit Rules

Do not ever add Co-Authored-By: Claude in any of the commit messages, EVER.

## What This Workspace Is

A multi-repo workspace for the **Orbit** UI/design-system platform at example-org. The root contains tooling, documentation, and configuration. Source repositories live under `repos/` (listed in `repos.conf`):

| Repo | Role | Stack |
|---|---|---|
| `orbit.docs` | Architecture docs, patterns, guidelines | Docusaurus, Markdown |
| `orbit.web.frontend` | Shared Next.js frontend (homepage/search/details/gallery/enquiry) | Next.js, TypeScript, pnpm |
| `orbit.search.core` | Backend SDK: pipeline, plugins, tenant resolution | .NET/C# |
| `orbit.design-system` | XmlSpec element definitions and generated JSON specs | .NET/C#, JSON |
| `orbit.ui-builder.web` | Web renderer: XmlSpec → Orbit React components | TypeScript, React, pnpm |
| `orbit-design-system` | Multi-platform design system (web/iOS/Android/tokens) | Turborepo, TypeScript, Swift, Android |
| `Storefront.Monorepo` | Storefront monorepo | — |
| `Widgets.Packages.Monorepo` | Widgets packages monorepo | — |

## Common Commands

```bash
# First-time setup (clones repos, installs deps, builds index)
make setup

# Rebuild the search index after pulling new changes
make build
# or directly:
python3 tools/dsl_indexer/index.py build

# Search the index from CLI
python3 tools/dsl_indexer/index.py search --query "tenant resolution"

# Check index status
python3 tools/dsl_indexer/index.py status

# Link MCP server to Claude/Codex (usually not needed; .mcp.json auto-configures)
make link

# Check prerequisites
make check
```

### Per-Repo Commands

**orbit.web.frontend:** `pnpm build`, `pnpm dev`, app mode selection via `pnpm use-homepage` / `pnpm use-search` / `pnpm use-details`

**orbit.search.core:** Open `src/Orbit.Search.Core.sln` in IDE

**orbit.design-system:** Open `src/Orbit.DesignSystem.Elements.sln`; see `specs/readme.md` for spec generation

**orbit.ui-builder.web:** `pnpm storybook` for component work; `pnpm build`, `pnpm test`, `pnpm lint`

**orbit-design-system:** Turborepo root — `pnpm dev`, `pnpm build`; `pnpm sync` for Figma token updates

## Architecture

### Data Flow

1. **XmlSpec elements** are defined in `orbit.design-system` (C#) and compiled to JSON specs
2. **Orbit Core** (`orbit.search.core`) consumes XmlSpec via its pipeline/plugin framework, resolving tenants and serving API responses
3. **UI Builder** (`orbit.ui-builder.web`) renders XmlSpec for web by mapping elements/actions to Orbit React components
4. **Orbit Design System** provides the shared component library and design tokens consumed by the UI builder and frontends
5. **Homepage Frontend** (`orbit.web.frontend`) integrates the UI builder into the production Next.js app
6. **orbit.docs** is the shared documentation hub for architecture, patterns, and guides

### Workspace Tooling (Python, in `tools/`)

- **`tools/dsl_indexer/`** — Cross-repo keyword search (BM25). Collects text files from all repos listed in `repos.conf`, chunks them (~1100 chars with overlap), and builds a keyword index. Output in `tools/dsl_indexer/data/`.
- **`tools/dsl_toolkit/`** — XmlSpec XML validation, linting, parsing, and explanation against the design system spec. Available via CLI (`tools/dsl_toolkit/cli.py`) or MCP tools.
- **`tools/mcp_docs_server/`** — FastMCP server exposing `docs_search`, `docs_get_chunk`, `docs_status`, `xmlspec_validate`, `xmlspec_lint`, `xmlspec_explain`, `xmlspec_explain_element` to Claude Code. Auto-starts via `.mcp.json`.

### MCP Tools Available

When working in this workspace, use these MCP tools for grounded answers:
- `docs_search(query, top_k, repo_filter)` — search indexed documentation
- `docs_get_chunk(chunk_id)` — retrieve full text of a search result
- `xmlspec_validate(xml_text)` — validate XmlSpec XML against the spec
- `xmlspec_lint(xml_text)` — check XmlSpec XML for style/deprecation issues
- `xmlspec_explain(xml_text)` / `xmlspec_explain_element(element_name)` — human-readable XmlSpec descriptions

## Key Conventions

- **Search before inference.** Always query the index before answering questions about Orbit architecture or XmlSpec. Do not guess when retrieval returns no hits — state the gap.
- **Cite sources.** Include file path and line range: `orbit.docs/internal/architecture-guidelines.md:42`
- **Load instruction files before editing.** Check for `CLAUDE.md`, `.github/copilot-instructions.md`, and `README.md` in a repo before proposing changes.
- **Prefer source over generated.** Use `src/`, `pages/`, `docs/`, `specs/`, `tools/` — not `node_modules/`, `.next/`, `build/`, `dist/`.
- For Orbit coding patterns: `repos/orbit.docs/internal/architecture-guidelines.md`
- For XmlSpec spec questions: `repos/orbit.design-system/specs/`
- For web renderer behavior: both `repos/orbit.ui-builder.web/` and `repos/orbit-design-system/`

## Prerequisites

- `git`, `python3` (3.10+), `uv` (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Optional: `claude` CLI, `codex`
