"""Load one flat server in an isolated process and run it over stdio."""

from __future__ import annotations

import importlib.util
import sys
from types import ModuleType

from nepa_mcp.config import load_credentials
from nepa_mcp.registry import server_directory, server_entrypoint


def _clear_local_imports() -> None:
    for module_name in tuple(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)


def load_server_module(name: str) -> ModuleType:
    """Import one server while preserving its private top-level ``src`` package."""
    _clear_local_imports()
    directory = server_directory(name)
    entrypoint = server_entrypoint(name)
    directory_text = str(directory)
    # A previous load can leave this directory behind another server's src/.
    if directory_text in sys.path:
        sys.path.remove(directory_text)
    sys.path.insert(0, directory_text)

    module_name = f"_nepa_mcp_server_{name}"
    spec = importlib.util.spec_from_file_location(module_name, entrypoint)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load server module from {entrypoint}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def run_server(name: str) -> None:
    load_credentials()
    module = load_server_module(name)
    module.mcp.run(transport="stdio", show_banner=False)
