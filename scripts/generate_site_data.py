"""Generate site metadata and inventory data from project and server sources."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "docs" / "assets" / "js" / "site-data.js"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastmcp import Client  # noqa: E402

from nepa_mcp.loader import load_server_module  # noqa: E402
from nepa_mcp.registry import SERVER_SPECS  # noqa: E402


# Presentation metadata for the site. Source agencies mirror the README's server
# inventory table; accents key each server to a colour in the site stylesheet.
# Everything else on the site is derived from the live MCP contract below.
SERVER_PRESENTATION: dict[str, dict[str, str]] = {
    "blm": {"agency": "Bureau of Land Management", "accent": "amber"},
    "census": {"agency": "U.S. Census Bureau", "accent": "indigo"},
    "cfr": {"agency": "Federal Register / GPO", "accent": "slate"},
    "efh": {"agency": "NOAA Fisheries", "accent": "sky"},
    "epa_aqs": {"agency": "U.S. Environmental Protection Agency", "accent": "emerald"},
    "esa_ranges": {"agency": "NOAA Fisheries", "accent": "sky"},
    "fema_nfhl": {"agency": "Federal Emergency Management Agency", "accent": "rose"},
    "gbif": {"agency": "Global Biodiversity Information Facility", "accent": "lime"},
    "gis": {"agency": "Esri geometry service", "accent": "violet"},
    "ipac": {"agency": "U.S. Fish and Wildlife Service", "accent": "amber"},
    "map_composer": {"agency": "Eight federal GIS publishers", "accent": "teal"},
    "nepa_assist": {"agency": "U.S. Environmental Protection Agency", "accent": "emerald"},
    "noaa": {"agency": "NOAA Fisheries", "accent": "sky"},
    "nrhp": {"agency": "National Park Service", "accent": "orange"},
    "padus": {"agency": "U.S. Geological Survey", "accent": "cyan"},
    "pcsrf": {"agency": "NOAA Fisheries", "accent": "sky"},
    "tigerweb_counties": {"agency": "U.S. Census Bureau", "accent": "indigo"},
    "tribal": {"agency": "U.S. Census Bureau", "accent": "orange"},
    "usace": {"agency": "U.S. Army Corps of Engineers", "accent": "stone"},
}

# Distinct source agencies and publishers named in the README's inventory. Kept
# here so the site never has to hardcode a headline count in markup.
FEDERAL_AGENCY_COUNT = 12

# Verified invariants. The generator fails loudly rather than quietly shipping a
# page whose headline numbers drifted away from the code.
EXPECTED_SERVER_COUNT = 19
EXPECTED_TOOL_COUNT = 46
EXPECTED_LAYER_COUNT = 32
EXPECTED_PROFILE_SIZES = {
    "screening": 12,
    "biological": 6,
    "water": 11,
    "lands": 14,
    "full": 32,
}


@dataclass
class ToolRecord:
    server: str
    name: str
    purpose: str
    parameters: list[dict[str, Any]] = field(default_factory=list)


def _purpose(server_name: str, tool_name: str, description: str | None) -> str:
    """Return the concise first paragraph of a tool's MCP description."""
    if not description or not description.strip():
        raise ValueError(f"{server_name}.{tool_name} has no MCP description")
    first_paragraph = description.strip().split("\n\n", maxsplit=1)[0]
    return " ".join(first_paragraph.split())


def _type_label(schema: dict[str, Any]) -> str:
    """Render a readable type label for one JSON Schema property."""
    if "type" in schema:
        label = str(schema["type"])
        return "number" if label == "integer" else label

    variants = schema.get("anyOf") or schema.get("oneOf") or []
    labels = [
        str(variant["type"])
        for variant in variants
        if isinstance(variant, dict) and variant.get("type") and variant["type"] != "null"
    ]
    if labels:
        unique = list(dict.fromkeys("number" if item == "integer" else item for item in labels))
        return " | ".join(unique)
    if "enum" in schema:
        return "enum"
    return "any"


def _default_label(schema: dict[str, Any]) -> str:
    """Render a tool parameter's default value the way a caller would write it."""
    if "default" not in schema:
        return ""
    default = schema["default"]
    if default is None:
        return "null"
    if isinstance(default, bool):
        return "true" if default else "false"
    if isinstance(default, str):
        return f'"{default}"'
    return json.dumps(default)


def _parameters(schema: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Flatten a tool's input schema into ordered, display-ready parameters."""
    if not schema:
        return []
    required = set(schema.get("required") or ())
    parameters: list[dict[str, Any]] = []
    for name, property_schema in (schema.get("properties") or {}).items():
        if not isinstance(property_schema, dict):
            continue
        description = " ".join(str(property_schema.get("description") or "").split())
        parameters.append(
            {
                "name": name,
                "type": _type_label(property_schema),
                "required": name in required,
                "default": _default_label(property_schema),
                "description": description,
                "choices": [str(choice) for choice in property_schema.get("enum") or ()],
            }
        )
    # Required parameters first, then the schema's own declaration order.
    parameters.sort(key=lambda parameter: not parameter["required"])
    return parameters


async def discover() -> tuple[list[ToolRecord], dict[str, Any]]:
    """Discover every server's tools, and Map Composer's layers, in one pass.

    Each server carries its own top-level ``src`` package, and the loader only
    prepends a server directory to ``sys.path`` the first time it sees it. Read
    Map Composer's module attributes while its directory is still the active
    one rather than importing it a second time later.
    """
    records: list[ToolRecord] = []
    map_composer: dict[str, Any] | None = None
    for server in SERVER_SPECS:
        module = load_server_module(server.name)
        async with Client(module.mcp) as client:
            tools = sorted(await client.list_tools(), key=lambda tool: tool.name)
        records.extend(
            ToolRecord(
                server=server.name,
                name=tool.name,
                purpose=_purpose(server.name, tool.name, tool.description),
                parameters=_parameters(tool.inputSchema),
            )
            for tool in tools
        )
        if server.name == "map_composer":
            map_composer = collect_map_composer(module)

    if map_composer is None:
        raise ValueError("the map_composer server is missing from SERVER_SPECS")
    return records, map_composer


def collect_map_composer(module: Any) -> dict[str, Any]:
    """Read the Map Composer layer catalog and profile membership from source."""
    metadata: dict[str, dict[str, str]] = module.LAYER_METADATA
    source_urls: dict[str, str] = module.LAYER_SOURCE_URLS
    profiles: dict[str, list[str]] = module.LAYER_PROFILES
    default_layers: list[str] = list(module.DEFAULT_LAYERS)

    missing = [layer for layer in default_layers if layer not in metadata]
    if missing:
        raise ValueError(f"layers missing from LAYER_METADATA: {', '.join(missing)}")
    missing_source_urls = [layer for layer in default_layers if layer not in source_urls]
    if missing_source_urls:
        raise ValueError(f"layers missing from LAYER_SOURCE_URLS: {', '.join(missing_source_urls)}")
    unknown_source_urls = [layer for layer in source_urls if layer not in default_layers]
    if unknown_source_urls:
        raise ValueError(f"unknown layers in LAYER_SOURCE_URLS: {', '.join(unknown_source_urls)}")

    for profile, layer_ids in profiles.items():
        unknown = [layer for layer in layer_ids if layer not in default_layers]
        if unknown:
            raise ValueError(f"profile {profile!r} references unknown layers: {', '.join(unknown)}")

    layers = [
        {
            "id": layer_id,
            "category": metadata[layer_id]["category"],
            "title": metadata[layer_id]["title"],
            "source": metadata[layer_id]["source"],
            "sourceUrl": source_urls[layer_id],
            "sourceLinkLabel": "Geometry service" if layer_id == "roi" else "Source service",
            "geometry": metadata[layer_id]["geometry"],
            "reviewUse": metadata[layer_id]["review_use"],
            "profiles": sorted(profile for profile, layer_ids in profiles.items() if layer_id in layer_ids),
        }
        for layer_id in default_layers
    ]

    categories = list(dict.fromkeys(layer["category"] for layer in layers))
    return {
        "layers": layers,
        "categories": categories,
        "profiles": [{"id": profile, "count": len(layer_ids)} for profile, layer_ids in profiles.items()],
    }


def build_site_data() -> dict[str, Any]:
    """Assemble the complete site payload from the live server contracts."""
    tools, map_composer = asyncio.run(discover())

    unknown_presentation = [server.name for server in SERVER_SPECS if server.name not in SERVER_PRESENTATION]
    if unknown_presentation:
        raise ValueError("add SERVER_PRESENTATION entries for: " + ", ".join(unknown_presentation))

    tool_counts: dict[str, int] = {}
    for tool in tools:
        tool_counts[tool.server] = tool_counts.get(tool.server, 0) + 1

    servers = [
        {
            "name": server.name,
            "description": server.description,
            "agency": SERVER_PRESENTATION[server.name]["agency"],
            "accent": SERVER_PRESENTATION[server.name]["accent"],
            "credentials": list(server.credentials),
            "toolCount": tool_counts.get(server.name, 0),
        }
        for server in SERVER_SPECS
    ]

    _verify(servers, tools, map_composer)

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    license_id = str(project["license"])

    return {
        "generatedFrom": "pyproject.toml, nepa_mcp.registry, and each server's live MCP tools/list contract",
        "release": {
            "version": str(project["version"]),
            "license": license_id,
            "licenseName": license_id.replace("-", " ", 1),
            "description": str(project["description"]),
            "repository": str(project["urls"]["Repository"]),
        },
        "counts": {
            "servers": len(servers),
            "tools": len(tools),
            "layers": len(map_composer["layers"]),
            "agencies": FEDERAL_AGENCY_COUNT,
            "profiles": len(map_composer["profiles"]),
            "capabilities": len(tools) + len(map_composer["layers"]),
            "credentialFreeServers": sum(1 for server in servers if not server["credentials"]),
        },
        "servers": servers,
        "tools": [
            {
                "server": tool.server,
                "name": tool.name,
                "purpose": tool.purpose,
                "parameters": tool.parameters,
            }
            for tool in tools
        ],
        "mapComposer": map_composer,
    }


def _verify(
    servers: list[dict[str, Any]],
    tools: list[ToolRecord],
    map_composer: dict[str, Any],
) -> None:
    """Fail when the discovered inventory drifts from the documented figures."""
    problems: list[str] = []
    if len(servers) != EXPECTED_SERVER_COUNT:
        problems.append(f"expected {EXPECTED_SERVER_COUNT} servers, discovered {len(servers)}")
    if len(tools) != EXPECTED_TOOL_COUNT:
        problems.append(f"expected {EXPECTED_TOOL_COUNT} tools, discovered {len(tools)}")

    layer_count = len(map_composer["layers"])
    if layer_count != EXPECTED_LAYER_COUNT:
        problems.append(f"expected {EXPECTED_LAYER_COUNT} layers, discovered {layer_count}")

    profile_sizes = {profile["id"]: profile["count"] for profile in map_composer["profiles"]}
    if profile_sizes != EXPECTED_PROFILE_SIZES:
        problems.append(f"expected profiles {EXPECTED_PROFILE_SIZES}, discovered {profile_sizes}")

    for tool in tools:
        if not tool.purpose:
            problems.append(f"{tool.server}.{tool.name} has no purpose text")

    if problems:
        raise ValueError(
            "site data does not match the documented inventory:\n  - "
            + "\n  - ".join(problems)
            + "\nUpdate the site copy and this script's expected figures together."
        )


def render_site_data() -> str:
    """Render the payload as a deterministic classic-script data file."""
    payload = json.dumps(build_site_data(), indent=2, sort_keys=False, ensure_ascii=False)
    # Guard the closing script tag in case a description ever contains one.
    payload = payload.replace("</", "<\\/")
    return (
        "/**\n"
        " * NEPA MCP Toolkit - site data\n"
        " *\n"
        " * Generated from project metadata, the server registry, and each server's\n"
        " * live MCP tools/list contract. Do not edit manually. Regenerate with\n"
        " * `uv run python scripts/generate_site_data.py`; add `--check` to verify.\n"
        " */\n"
        "\n"
        "/* eslint-disable */\n"
        f"var SITE_DATA = {payload};\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit nonzero instead of writing when the committed site data is stale",
    )
    args = parser.parse_args(argv)

    logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)
    rendered = render_site_data()
    if args.check:
        current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.is_file() else None
        if current != rendered:
            print(
                f"{OUTPUT_PATH.relative_to(ROOT)} is stale; regenerate it with "
                "`uv run python scripts/generate_site_data.py`",
                file=sys.stderr,
            )
            return 1
        print(f"{OUTPUT_PATH.relative_to(ROOT)} is current")
        return 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
