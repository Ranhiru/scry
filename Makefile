WORKSPACE := $(CURDIR)
UV        := $(shell command -v uv 2>/dev/null)
SERVER    := $(WORKSPACE)/tools/mcp_docs_server
BIN_DIR   ?= $(HOME)/.local/bin

.PHONY: setup build build-keyword-only build-vector-only link check install-cli uninstall-cli

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

build-vector-only:
	$(UV) --directory $(SERVER) run python $(WORKSPACE)/tools/dsl_indexer/index.py build --skip-keyword

install-cli:
	@mkdir -p "$(BIN_DIR)"
	@ln -sf "$(WORKSPACE)/tools/workspace-docs" "$(BIN_DIR)/workspace-docs"
	@echo "Installed workspace-docs to $(BIN_DIR)/workspace-docs"

uninstall-cli:
	@rm -f "$(BIN_DIR)/workspace-docs"
	@echo "Removed $(BIN_DIR)/workspace-docs"

link:
	@failed=false; \
	if command -v claude >/dev/null 2>&1; then \
		if CLAUDECODE= claude mcp list >/dev/null 2>&1; then \
			if CLAUDECODE= claude mcp get workspace-docs >/dev/null 2>&1; then \
				if [ "$(OVERRIDE)" = "1" ]; then \
					echo "Relinking MCP server for Claude (OVERRIDE=1): removing existing config first..."; \
					CLAUDECODE= claude mcp remove workspace-docs >/dev/null 2>&1 || true; \
				else \
					echo "WARN: workspace-docs already exists for Claude. Use 'make link OVERRIDE=1' to recreate it."; \
				fi; \
			fi; \
			if [ "$(OVERRIDE)" = "1" ] || ! CLAUDECODE= claude mcp get workspace-docs >/dev/null 2>&1; then \
				echo "Linking MCP server for Claude..."; \
				if ! CLAUDECODE= claude mcp add workspace-docs \
					--scope user --transport stdio -- \
					$(UV) --directory $(SERVER) run server.py; then \
					echo "WARN: failed to add workspace-docs for Claude"; \
					failed=true; \
				fi; \
			fi; \
		else \
			echo "WARN: Claude MCP is not initialized. Run 'claude mcp list' once to initialize, then retry make link."; \
		fi; \
	else \
		echo "WARN: claude not found, skipping"; \
	fi; \
	if command -v codex >/dev/null 2>&1; then \
		if codex mcp list >/dev/null 2>&1; then \
			if codex mcp get workspace-docs >/dev/null 2>&1; then \
				if [ "$(OVERRIDE)" = "1" ]; then \
					echo "Relinking MCP server for Codex (OVERRIDE=1): removing existing config first..."; \
					codex mcp remove workspace-docs >/dev/null 2>&1 || true; \
				else \
					echo "WARN: workspace-docs already exists for Codex. Use 'make link OVERRIDE=1' to recreate it."; \
				fi; \
			fi; \
			if [ "$(OVERRIDE)" = "1" ] || ! codex mcp get workspace-docs >/dev/null 2>&1; then \
				echo "Linking MCP server for Codex..."; \
				if ! codex mcp add workspace-docs -- \
					$(UV) --directory $(SERVER) run server.py; then \
					echo "WARN: failed to add workspace-docs for Codex"; \
					failed=true; \
				fi; \
			fi; \
		else \
			echo "WARN: Codex MCP is not initialized. Run 'codex mcp list' once to initialize, then retry make link."; \
		fi; \
	else \
		echo "WARN: codex not found, skipping"; \
	fi; \
	$$failed && exit 1 || true
