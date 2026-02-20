WORKSPACE := $(CURDIR)
UV        := $(shell command -v uv 2>/dev/null)
SERVER    := $(WORKSPACE)/tools/mcp_docs_server

.PHONY: setup build build-keyword-only link check

check:
	@ok=true; \
	command -v git >/dev/null 2>&1       || { echo "MISSING: git";    ok=false; }; \
	command -v python3 >/dev/null 2>&1   || { echo "MISSING: python3"; ok=false; }; \
	command -v uv >/dev/null 2>&1        || { echo "MISSING: uv  (curl -LsSf https://astral.sh/uv/install.sh | sh)"; ok=false; }; \
	command -v claude >/dev/null 2>&1    || echo "OPTIONAL: claude not found (link target will skip it)"; \
	command -v codex >/dev/null 2>&1     || echo "OPTIONAL: codex not found (link target will skip it)"; \
	$$ok && echo "All prerequisites found." || { echo "Install missing tools and retry."; exit 1; }

setup: check
	bash setup.sh

build:
	$(UV) --directory $(SERVER) run python $(WORKSPACE)/tools/dsl_indexer/index.py build

build-keyword-only:
	python3 tools/dsl_indexer/index.py build --skip-vectors

link:
	@if command -v claude >/dev/null 2>&1; then \
		echo "Linking MCP server for Claude..."; \
		CLAUDECODE= claude mcp add workspace-docs \
			--scope user --transport stdio -- \
			$(UV) --directory $(SERVER) run server.py; \
	else \
		echo "WARN: claude not found, skipping"; \
	fi
	@if command -v codex >/dev/null 2>&1; then \
		echo "Linking MCP server for Codex..."; \
		codex mcp add workspace-docs -- \
			$(UV) --directory $(SERVER) run server.py; \
	else \
		echo "WARN: codex not found, skipping"; \
	fi
