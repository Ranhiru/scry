# AST-Aware Chunking Plan

Status: Proposed  
Research date: 2026-08-16

## Objective

Replace the single hard-coded chunking decision with configurable, file-type-aware chunking:

- Tree-sitter-based structural chunking for source code.
- Structure-aware chunking for Markdown and MDX.
- A plain-text fallback for unsupported, malformed, or explicitly configured files.
- Future extension points for structured formats such as JSON, YAML, TOML, and XML.

The change must preserve deterministic chunk IDs, exact line citations, incremental indexing, BM25 indexing, vector indexing, and the existing CLI and MCP contracts.

## Current State

`tools/dsl_indexer/chunk.py` currently selects one of two paths:

- Markdown and MDX are split at heading boundaries and then sliced by character count.
- Every other supported file, including source code, is sliced by character count.

Both paths use global settings from `tools/dsl_indexer/config.py`:

- Target: 1,100 characters.
- Overlap: 180 characters.

The current code chunker is not syntax-aware and can split declarations, signatures, comments, strings, and statements at arbitrary positions.

## Research Findings

### Tree-sitter

Tree-sitter is the recommended parsing foundation. Strictly, it produces a concrete syntax tree rather than a normalized AST. This is beneficial because it preserves declarations, comments, and exact source byte and line ranges while tolerating incomplete code.

The Python bindings expose named syntax nodes, byte offsets, source positions, traversal APIs, and parser error information.

Source: [py-tree-sitter](https://github.com/tree-sitter/py-tree-sitter)

### Tree-sitter language pack

`tree-sitter-language-pack` is the recommended integration for this generic multi-repository toolkit. It provides:

- A unified Python API for hundreds of grammars.
- Language detection from paths and extensions.
- Syntax-aware chunks.
- Syntax diagnostics.
- Byte offsets, line ranges, and node-type metadata.
- Pre-download and caching support for offline builds.

The dependency and selected parser versions should be locked. Configured parsers should be downloaded during setup so normal index builds do not require network access.

Source: [tree-sitter-language-pack](https://github.com/xberg-io/tree-sitter-language-pack)

### Alternatives considered

| Option | Assessment |
| --- | --- |
| `py-tree-sitter` plus individual grammars | Maximum control and deterministic dependencies, but each supported language requires another dependency and loader. |
| Chonkie `CodeChunker` | Viable high-level Tree-sitter integration, but its advanced chunker is evolving, may exceed requested sizes for semantic coherence, and adds a broader RAG dependency. |
| LlamaIndex `CodeSplitter` | Not recommended. It adds a large framework dependency, historically uses the unmaintained `py-tree-sitter-languages`, and has reported ineffective line and overlap settings. |
| LangChain language splitters | Not AST-aware. They use language-specific text separator lists and can still split syntax. |
| Python `ast` | Strong for Python only, but unsuitable for a multi-language indexer. |
| New AST chunking packages | Promising, but too new to own the core index format and chunking contract. |

Sources:

- [Chonkie CodeChunker](https://docs.chonkie.ai/oss/chunkers/code-chunker)
- [py-tree-sitter-languages maintenance status](https://github.com/grantjenks/py-tree-sitter-languages)
- [LlamaIndex CodeSplitter issue](https://github.com/run-llama/llama_index/issues/18710)
- [LangChain code splitter](https://docs.langchain.com/oss/python/integrations/splitters/code_splitter)

### Markdown

`markdown-it-py` is the recommended Markdown parser. It is CommonMark-aware and exposes block tokens with source line maps. It can distinguish headings, paragraphs, lists, block quotes, tables, and fenced code without rendering the document back to Markdown.

Source: [markdown-it-py](https://github.com/executablebooks/markdown-it-py)

## Recommended Architecture

Introduce a chunker strategy registry and a configuration-driven router:

```text
file path + repository
          |
          v
configurable routing rules
          |
          +-- code       -> TreeSitterCodeChunker
          +-- markdown   -> MarkdownChunker
          +-- structured -> future JSON/XML/YAML chunkers
          +-- default    -> PlainTextChunker
```

`chunk_file()` remains the orchestration entry point. It reads the file, resolves repository metadata, selects a chunker, and converts strategy-specific drafts into the shared `Chunk` representation.

## Proposed Configuration

Add a `chunking` section to `workspace.yaml`:

```yaml
chunking:
  default_profile: text

  profiles:
    code:
      strategy: tree_sitter
      target_size: 1800
      hard_max_size: 2800
      size_unit: bytes
      overlap_nodes: 0
      attach_leading_comments: true
      preserve_decorators: true
      include_parent_signature: true
      on_parse_error: text

    markdown:
      strategy: markdown
      target_size: 1800
      hard_max_size: 2800
      overlap_blocks: 1
      preserve_fenced_code: true
      preserve_tables: true
      preserve_lists: true

    text:
      strategy: text
      target_size: 1100
      overlap_chars: 180

  rules:
    - extensions: [".md", ".mdx"]
      profile: markdown

    - extensions: [".py"]
      profile: code
      language: python

    - extensions: [".js", ".jsx"]
      profile: code
      language: javascript

    - extensions: [".ts"]
      profile: code
      language: typescript

    - extensions: [".tsx"]
      profile: code
      language: tsx

    - extensions: [".cs"]
      profile: code
      language: csharp

    - extensions: [".sh"]
      profile: code
      language: bash
```

Rules should also support path globs and optional repository selectors:

```yaml
    - glob: "**/generated/**"
      profile: text

    - repo: legacy-app
      extensions: [".js"]
      profile: text
```

Resolve rules in this order:

1. Repository and path glob.
2. Path glob.
3. Extension.
4. Default profile.

Reject unknown strategies, missing profiles, invalid sizes, unsupported configured languages, and ambiguous rules while loading the configuration.

## Implementation Plan

### 1. Introduce the chunker contract

Create `tools/dsl_indexer/chunkers/` with:

- `base.py`: `Chunker` protocol, `ChunkContext`, and `ChunkDraft`.
- `router.py`: configuration rule resolution.
- `tree_sitter.py`: code strategy.
- `markdown.py`: Markdown strategy.
- `text.py`: existing fixed-size behavior.
- `registry.py`: strategy registration and lookup.

A `ChunkDraft` should contain:

```text
content
line_start
line_end
section
strategy
language
node_type
symbol_path
```

Strategy implementations decide boundaries. Shared code adds repository and path metadata, estimates tokens, validates ranges, and creates stable IDs.

### 2. Add typed chunking configuration

Extend `tools/workspace_config.py` with dataclasses for:

- Chunking configuration.
- Named profiles.
- Routing rules.
- Strategy-specific settings.

When the `chunking` section is absent, load built-in defaults. Retain a `legacy_text` strategy for workspaces that need the previous boundaries during migration.

### 3. Implement AST-aware code chunking

The code chunker should:

1. Parse UTF-8 source using the configured Tree-sitter language.
2. Collect syntax diagnostics.
3. Identify semantic units such as imports, classes, functions, interfaces, methods, enums, and top-level statements.
4. Attach decorators, attributes, docstrings, and immediately preceding comments to their declarations.
5. Group adjacent small units until the target size is reached.
6. Keep complete declarations intact when they fit below the hard maximum.
7. Recursively split oversized classes and functions at child syntax boundaries.
8. Retain the parent signature or symbol path when splitting a declaration.
9. Use a line-aware fallback when no safe child boundary exists.
10. Fall back to the configured text strategy when parsing fails beyond an allowed error threshold.

Do not apply arbitrary character overlap to code by default. Parent signatures, symbol paths, and leading comments provide more meaningful context. Keep semantic-node overlap configurable for evaluation.

Tree-sitter ranges are byte-based and end-exclusive. Tests and implementation must explicitly handle UTF-8 multibyte characters, CRLF, an end position at column zero, and files without a trailing newline.

### 4. Implement structure-aware Markdown chunking

The Markdown chunker should:

1. Parse the document into source-mapped block tokens.
2. Maintain the full heading hierarchy, such as `API > Authentication > Refresh tokens`.
3. Treat paragraphs, fenced code, lists, block quotes, and tables as semantic blocks.
4. Pack adjacent blocks in the same section until the target size is reached.
5. Overlap complete blocks rather than character tails.
6. Avoid splitting a fence, table row group, or list item unless it exceeds the hard maximum.
7. Delegate oversized fenced code to the configured code chunker when its language is supported.
8. Split oversized prose by paragraph, then line, then character boundary.
9. Preserve the original source rather than rendering parsed tokens.

MDX requires dedicated tests because JSX is not plain CommonMark. Start by preserving JSX as raw blocks. Add a Tree-sitter MDX strategy if fixture results show poor boundaries.

### 5. Preserve and extend chunk metadata

Keep all current fields and add optional metadata:

- `chunk_strategy`.
- `language`.
- `node_type`.
- `symbol_path`.
- `heading_path`.
- `parse_error_count`.

For code, use the symbol path as the human-readable `section`. For Markdown, use the heading path. This maintains compatibility with current search results and citation formatting.

Initially store extended metadata in `chunks.jsonl`. Add fields to the zvec schema only when they need to be returned or filtered during vector search.

### 6. Invalidate indexes when chunking changes

The current manifest only detects changes to source files. Chunking configuration and implementation changes must also invalidate the index.

Create and store a `chunking_fingerprint` from:

- The resolved chunking configuration.
- The internal chunker schema version.
- Parser and library versions.
- Grammar versions where available.

Compare the fingerprint in `_schema_invalidation_reason()`. A change must force a complete rechunk, BM25 rebuild, vector rebuild, and manifest refresh. Increment `INDEX_VERSION` for the initial migration.

The content-hash embedding cache can continue reusing embeddings where the resulting chunk text is unchanged.

### 7. Add observability

Extend build metadata and `docs_status()` with:

- Chunking fingerprint.
- Chunker schema version.
- Counts by strategy and language.
- Parser fallback count.
- Parse diagnostic count.
- Average and percentile chunk sizes.

Log a concise warning for each fallback and a summary at the end of the build. Do not silently treat configured code as plain text.

### 8. Test the strategies

Add golden fixtures for:

- Python decorators, async functions, nested classes, and docstrings.
- JavaScript imports, functions, classes, and object exports.
- TypeScript interfaces, types, generics, and declarations.
- TSX components, hooks, and embedded JSX.
- C# namespaces, attributes, classes, and methods.
- Bash functions and top-level commands.
- Markdown nested headings, long lists, tables, fences, and block quotes.
- MDX JSX components and fenced code.
- Malformed and partially edited source.
- Unicode, CRLF, empty files, and missing trailing newlines.
- Oversized declarations and Markdown blocks.

Test these invariants:

- Identical input and configuration produce identical chunks and IDs.
- Line citations are exact.
- No chunks are empty.
- No source regions are silently lost.
- Hard size limits are respected after fallback.
- Declarations remain intact when below the hard limit.
- Parser errors do not abort an index build.
- Unknown extensions use the configured default.
- Incremental builds rechunk only affected files.
- Chunking configuration changes trigger a full rebuild.

### 9. Evaluate retrieval quality

Create a small benchmark of symbol, behavior, and exact-identifier queries. Compare the current and proposed strategies using:

- Recall at 5 and 10.
- Mean reciprocal rank.
- Chunk count.
- Average and p95 chunk size.
- Duplicate-content ratio.
- Index and build duration.
- Percentage of code chunks aligned to declaration boundaries.
- Citation accuracy.

Record baseline and new results in a checked-in report so the default change is evidence-based.

### 10. Roll out in stages

1. Add the router and new strategies behind explicit `workspace.yaml` configuration.
2. Run the retrieval benchmark and tune the built-in profiles.
3. Make Tree-sitter code chunking and structure-aware Markdown chunking the generated defaults in `workspace.example.yaml`.
4. Document parser installation, offline setup, configuration, fallbacks, and migration behavior.
5. Remove the legacy strategy only in a later breaking release.

## Acceptance Criteria

- Chunker selection is controlled by validated `workspace.yaml` rules.
- Python, JavaScript, TypeScript, TSX, C#, and Bash receive syntax-aware chunks by default.
- Markdown chunks preserve heading hierarchy and structural blocks.
- Unsupported and malformed files fall back predictably without aborting builds.
- Source text and line citations remain exact.
- Chunking changes reliably invalidate existing indexes.
- Incremental builds and embedding-cache reuse continue to work.
- Existing CLI and MCP response contracts remain compatible.
- Retrieval evaluation shows no regression in identifier queries and an improvement in structural code queries.
