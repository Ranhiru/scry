WORKSPACE := $(CURDIR)
UV        := $(shell command -v uv 2>/dev/null)
SERVER    := $(WORKSPACE)/tools/mcp_docs_server
BIN_DIR   ?= $(HOME)/.local/bin

# Derive the CLI name from workspace.yaml (top-level `name:`). Falls back to
# `scry` if the config is missing or malformed.
CLI_NAME := $(shell awk -F': *' '/^name:/ {gsub(/[ \t"]+/,"",$$2); print $$2; exit}' $(WORKSPACE)/workspace.yaml 2>/dev/null)
ifeq ($(strip $(CLI_NAME)),)
CLI_NAME := scry
endif

.PHONY: setup build build-keyword-only build-vector-only link check install-cli uninstall-cli test

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
	$(UV) --directory $(SERVER) run python $(WORKSPACE)/tools/dsl_indexer/index.py build --skip-vectors

build-vector-only:
	$(UV) --directory $(SERVER) run python $(WORKSPACE)/tools/dsl_indexer/index.py build --skip-keyword

test:
	cd $(WORKSPACE) && $(UV) run --project $(SERVER) --group dev python -m pytest -q

install-cli:
	@mkdir -p "$(BIN_DIR)"
	@ln -sf "$(WORKSPACE)/tools/docs-cli" "$(BIN_DIR)/$(CLI_NAME)"
	@echo "Installed $(CLI_NAME) to $(BIN_DIR)/$(CLI_NAME)"

uninstall-cli:
	@rm -f "$(BIN_DIR)/$(CLI_NAME)"
	@echo "Removed $(BIN_DIR)/$(CLI_NAME)"

link:
	@failed=false; \
	if command -v claude >/dev/null 2>&1; then \
		if CLAUDECODE= claude mcp list >/dev/null 2>&1; then \
			if CLAUDECODE= claude mcp get $(CLI_NAME) >/dev/null 2>&1; then \
				if [ "$(OVERRIDE)" = "1" ]; then \
					echo "Relinking MCP server for Claude (OVERRIDE=1): removing existing config first..."; \
					CLAUDECODE= claude mcp remove $(CLI_NAME) >/dev/null 2>&1 || true; \
				else \
					echo "WARN: $(CLI_NAME) already exists for Claude. Use 'make link OVERRIDE=1' to recreate it."; \
				fi; \
			fi; \
			if [ "$(OVERRIDE)" = "1" ] || ! CLAUDECODE= claude mcp get $(CLI_NAME) >/dev/null 2>&1; then \
				echo "Linking MCP server for Claude..."; \
				if ! CLAUDECODE= claude mcp add $(CLI_NAME) \
					--scope user --transport stdio -- \
					$(UV) --directory $(SERVER) run server.py; then \
					echo "WARN: failed to add $(CLI_NAME) for Claude"; \
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
			if codex mcp get $(CLI_NAME) >/dev/null 2>&1; then \
				if [ "$(OVERRIDE)" = "1" ]; then \
					echo "Relinking MCP server for Codex (OVERRIDE=1): removing existing config first..."; \
					codex mcp remove $(CLI_NAME) >/dev/null 2>&1 || true; \
				else \
					echo "WARN: $(CLI_NAME) already exists for Codex. Use 'make link OVERRIDE=1' to recreate it."; \
				fi; \
			fi; \
			if [ "$(OVERRIDE)" = "1" ] || ! codex mcp get $(CLI_NAME) >/dev/null 2>&1; then \
				echo "Linking MCP server for Codex..."; \
				if ! codex mcp add $(CLI_NAME) -- \
					$(UV) --directory $(SERVER) run server.py; then \
					echo "WARN: failed to add $(CLI_NAME) for Codex"; \
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
