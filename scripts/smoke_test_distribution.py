"""Smoke-test the installed NEPA MCP distribution over real stdio clients."""

from __future__ import annotations

import argparse
import asyncio
from importlib.metadata import version

from fastmcp import Client

from nepa_mcp.aggregate import child_server_config
from nepa_mcp.registry import SERVER_SPECS


EXPECTED_SERVER_COUNT = 20
EXPECTED_TOOL_COUNT = 47


async def inspect_servers() -> tuple[int, int]:
    """Start every installed server and count its advertised MCP tools."""
    tool_count = 0
    for spec in SERVER_SPECS:
        async with Client(child_server_config(spec.name)) as client:
            tools = await client.list_tools()
        tool_count += len(tools)
        print(f"{spec.name}: {len(tools)} tools")
    return len(SERVER_SPECS), tool_count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-version")
    args = parser.parse_args()

    installed_version = version("nepa-mcp")
    if args.expected_version and installed_version != args.expected_version:
        raise SystemExit(f"installed version {installed_version!r} does not match {args.expected_version!r}")

    server_count, tool_count = asyncio.run(inspect_servers())
    if server_count != EXPECTED_SERVER_COUNT:
        raise SystemExit(f"expected {EXPECTED_SERVER_COUNT} servers, found {server_count}")
    if tool_count != EXPECTED_TOOL_COUNT:
        raise SystemExit(f"expected {EXPECTED_TOOL_COUNT} tools, found {tool_count}")

    print(f"nepa-mcp {installed_version}: {server_count} servers and {tool_count} tools passed")


if __name__ == "__main__":
    main()
