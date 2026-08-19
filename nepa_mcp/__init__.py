"""Installable runtime for the NEPA MCP server collection."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("nepa-mcp")
except PackageNotFoundError:  # Source checkout before installation.
    __version__ = "0.1.0"

__all__ = ["__version__"]
