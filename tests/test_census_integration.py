"""
Integration tests for the Census MCP server.

These load ``census/server.py`` through a real ``fastmcp.Client`` and exercise
the full tool -> api -> formatter -> Markdown path, with only the network layer
(``requests`` and the ArcGIS buffer helper) mocked. This mirrors the loading
approach in ``test_mcp_contracts.py`` and the USACE integration template.

The server requires a ``CENSUS_API_KEY``; we set a deterministic test value
before loading, matching ``_set_test_credentials`` in ``test_mcp_contracts.py``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

import pytest
from fastmcp import Client

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "census"
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}

TOOL_NAME = "get_acs_socioeconomic_indicators_in_roi"

DEFAULT_VALUE_MAP = {
    "DP03_0062E": "55000",
    "DP03_0088E": "30000",
    "DP03_0128PE": "12.5",
    "DP03_0134PE": "15.0",
    "DP03_0009PE": "6.2",
    "DP03_0008E": "300000",
    "DP03_0004E": "280000",
}
BERNALILLO = {"NAME": "Bernalillo County", "GEOID": "35001"}


def _set_test_credentials() -> None:
    os.environ.setdefault("CENSUS_API_KEY", "test-census-key")


def _load_server():
    _set_test_credentials()
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_census_int_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_census_int_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_census_int_server"] = module
    spec.loader.exec_module(module)
    return module


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _install_mock_network(module, counties, value_map=None):
    """Patch the network on the api module that ``server.py`` actually imports."""
    api = sys.modules.get("src.apis.simplified_census_api", module)
    value_map = {**DEFAULT_VALUE_MAP, **(value_map or {})}

    def fake_get(url, params=None, timeout=None, **_kwargs):
        params = params or {}
        low = url.lower()
        if "tigerweb" in low:
            return _FakeResponse({"features": [{"attributes": a} for a in counties]})
        if url.endswith("variables.json"):
            return _FakeResponse({"variables": {}})
        requested = params.get("get", "").split(",") if params.get("get") else []
        headers = requested + ["state", "county"]
        values = [value_map.get(var, "-888888888") for var in requested] + ["35", "001"]
        return _FakeResponse([headers, values])

    from nepa_mcp_common.arcgis import ArcGISService

    ArcGISService.create_roi_buffer = staticmethod(lambda *_a, **_k: SIMPLE_GEOMETRY)
    api.requests.get = fake_get


async def _call(module, tool_name, args):
    async with Client(module.mcp) as client:
        return await client.call_tool(tool_name, args)


def _text(result) -> str:
    parts = []
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


class TestToolRegistration:
    def test_tool_registered(self):
        module = _load_server()

        async def _names():
            async with Client(module.mcp) as client:
                return {t.name for t in await client.list_tools()}

        assert TOOL_NAME in asyncio.run(_names())


class TestSocioeconomicTool:
    def test_returns_markdown_with_county_indicators(self):
        module = _load_server()
        _install_mock_network(module, [BERNALILLO])
        result = asyncio.run(_call(module, TOOL_NAME, {"latitude": 34.5, "longitude": -106.5, "buffer_miles": 25}))
        text = _text(result)
        assert "Bernalillo County, NM" in text
        assert "Median household income: $55,000" in text
        assert "U.S. Census Bureau ACS 5-Year Estimates" in text

    def test_empty_roi_is_graceful(self):
        module = _load_server()
        _install_mock_network(module, [])
        result = asyncio.run(_call(module, TOOL_NAME, {"latitude": 34.5, "longitude": -106.5}))
        assert "No counties found in the region of interest." in _text(result)

    def test_missing_api_key_returns_error_message(self, monkeypatch):
        module = _load_server()
        monkeypatch.delenv("CENSUS_API_KEY", raising=False)
        _install_mock_network(module, [BERNALILLO])
        result = asyncio.run(_call(module, TOOL_NAME, {"latitude": 34.5, "longitude": -106.5}))
        assert "CENSUS_API_KEY" in _text(result)


class TestInputValidationThroughTool:
    def test_out_of_range_latitude_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, TOOL_NAME, {"latitude": 999, "longitude": -106.5}))

    def test_zero_buffer_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, TOOL_NAME, {"latitude": 34.5, "longitude": -106.5, "buffer_miles": 0}))
