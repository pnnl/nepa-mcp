#!/usr/bin/env python3
"""Ad-hoc stress harness for exercising one MCP server end-to-end (live upstream calls).

Usage:
    uv run python tests/stress_harness.py <server_name> [--case NAME]

Loads .env, imports <server_name>/server.py in isolation (same path juggling as the
contract tests), lists tools, and invokes each tool via the FastMCP in-process client
against real coordinates. Prints a compact PASS/FAIL/EMPTY line per tool plus a snippet
of the returned text so an agent can eyeball correctness.

This file is a throwaway test aid, not part of the shipped server surface.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


# Representative real-world ROIs (lat, lon) chosen to hit each dataset's coverage.
CASES = {
    # Sacramento River delta area — West Coast, near salmon/EFH/NOAA WCR coverage, has counties/tribal
    "west_coast": {"latitude": 38.5, "longitude": -121.5, "buffer_miles": 10.0},
    # New Orleans — Gulf coast, FEMA flood zones, USACE, Atlantic-ish
    "gulf": {"latitude": 29.95, "longitude": -90.07, "buffer_miles": 10.0},
    # rural Wyoming — BLM land, wilderness, low population
    "blm_country": {"latitude": 43.0, "longitude": -108.5, "buffer_miles": 15.0},
    # Washington DC — dense, historic places, air quality monitors
    "urban_east": {"latitude": 38.9, "longitude": -77.03, "buffer_miles": 8.0},
    # Off the coast of Maine — Atlantic salmon EFH (pcsrf_efh)
    "maine": {"latitude": 44.8, "longitude": -68.2, "buffer_miles": 15.0},
}

# Non-geo servers / tool-specific argument overrides keyed by tool name.
# Anything not listed falls back to the geo CASE args (filtered to the tool's schema).
TOOL_ARG_OVERRIDES = {
    # cfr (non-geo)
    "cfr_resolve_citation": {"citation": "43 CFR 46.215"},
    "cfr_browse_structure": {"title": 43, "part": 46},
    "cfr_history": {"citation": "43 CFR 46.215"},
    "cfr_compare_versions": {"citation": "43 CFR 46.215", "date_a": "2020-01-01", "date_b": "2024-01-01"},
    "cfr_rulemaking": {"cfr_title": 43, "cfr_part": 46},
    "cfr_resolve_fr_citation": {"citation": "90 FR 29498"},
    "cfr_resolve_executive_order": {"eo_number": 14008},
}


def load_server(server_name: str):
    server_dir = ROOT / server_name
    server_path = server_dir / "server.py"
    module_name = f"_stress_{server_name}"

    # Isolate this server's local `src` package.
    for m in list(sys.modules):
        if m == "src" or m.startswith("src.") or m.startswith("_stress_"):
            sys.modules.pop(m, None)
    sys.path[:] = [p for p in sys.path if p != str(server_dir)]
    sys.path.insert(0, str(server_dir))

    spec = importlib.util.spec_from_file_location(module_name, server_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def build_args(schema: dict, case: dict, tool_name: str) -> dict:
    props = (schema or {}).get("properties", {}) or {}
    if tool_name in TOOL_ARG_OVERRIDES:
        override = TOOL_ARG_OVERRIDES[tool_name]
        # keep only keys the tool actually accepts
        return {k: v for k, v in override.items() if k in props}
    # geo tool: pass whatever geo fields it declares
    args = {}
    for k, v in case.items():
        if k in props:
            args[k] = v
    # some tools use radius_miles instead of buffer_miles
    if "radius_miles" in props and "radius_miles" not in args and "buffer_miles" in case:
        args["radius_miles"] = case["buffer_miles"]
    return args


async def run(server_name: str, case_name: str) -> int:
    from fastmcp import Client

    module = load_server(server_name)
    case = CASES[case_name]
    failures = 0

    async with Client(module.mcp) as client:
        tools = await client.list_tools()
        print(f"\n=== {server_name}: {len(tools)} tools | case={case_name} {case} ===")
        for tool in tools:
            args = build_args(tool.inputSchema, case, tool.name)
            t0 = time.monotonic()
            try:
                result = await client.call_tool(tool.name, args)
                dt = time.monotonic() - t0
                # FastMCP returns content blocks; grab text
                text = ""
                for block in getattr(result, "content", []) or []:
                    text += getattr(block, "text", "") or ""
                if not text and getattr(result, "data", None) is not None:
                    text = json.dumps(result.data)[:4000]
                text = text.strip()
                status = "EMPTY" if not text else "PASS"
                # crude "looks like an error message but returned as text" detector
                low = text.lower()
                if any(s in low[:400] for s in ("traceback", "exception:", "error:", "failed:")):
                    status = "SOFT-ERR"
                snippet = " ".join(text.split())[:280]
                print(f"[{status:8}] {tool.name} ({dt:5.1f}s) args={args}")
                print(f"           -> {snippet}")
                if status in ("EMPTY", "SOFT-ERR"):
                    failures += 1
            except Exception as exc:  # noqa: BLE001
                dt = time.monotonic() - t0
                print(f"[{'HARD-ERR':8}] {tool.name} ({dt:5.1f}s) args={args}")
                print(f"           -> {type(exc).__name__}: {exc}")
                traceback.print_exc()
                failures += 1
    print(f"=== {server_name}: {failures} problem tool(s) ===")
    return failures


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("server")
    ap.add_argument("--case", default="west_coast", choices=list(CASES))
    args = ap.parse_args()
    _load_dotenv()
    rc = asyncio.run(run(args.server, args.case))
    sys.exit(1 if rc else 0)


if __name__ == "__main__":
    main()
