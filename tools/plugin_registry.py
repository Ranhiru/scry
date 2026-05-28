"""Plugin discovery for the MCP server.

A plugin lives under `tools/plugins/<name>/plugin.py` and exposes a `Plugin`
class with `name: str` and `register(mcp, cfg)`. Discovery iterates the
`plugins` mapping in workspace.yaml, importing the matching module for each
entry that has `enabled: true`.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Iterator, Protocol, runtime_checkable

from workspace_config import WorkspaceConfig

PLUGINS_PARENT = Path(__file__).resolve().parent
if str(PLUGINS_PARENT) not in sys.path:
    sys.path.insert(0, str(PLUGINS_PARENT))


@runtime_checkable
class Plugin(Protocol):
    name: str

    def register(self, mcp, cfg: WorkspaceConfig) -> None:
        ...


def discover_plugins(cfg: WorkspaceConfig) -> Iterator[Plugin]:
    for plugin_name, plugin_cfg in cfg.plugins.items():
        if not plugin_cfg.enabled:
            continue
        module_name = f"plugins.{plugin_name}.plugin"
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            print(
                f"[plugin_registry] failed to load {plugin_name!r}: {exc}",
                file=sys.stderr,
            )
            continue
        plugin_cls = getattr(module, "Plugin", None)
        if plugin_cls is None:
            print(
                f"[plugin_registry] {module_name} has no `Plugin` class",
                file=sys.stderr,
            )
            continue
        yield plugin_cls()
