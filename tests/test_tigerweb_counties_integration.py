"""
Integration tests for the tigerweb_counties MCP server.

These load ``tigerweb_counties/server.py`` through a real ``fastmcp.Client`` and
exercise the full tool -> api -> formatter -> Markdown path, with only the
ArcGIS network layer mocked.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest
from fastmcp import Client

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "tigerweb_counties"
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}

_TOOL_NAME = "get_tigerweb_counties_in_roi"


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_counties_int_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_counties_int_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_counties_int_server"] = module
    spec.loader.exec_module(module)
    return module


def _install_mock_query(monkeypatch, features, warnings=None):
    from nepa_mcp_common.arcgis import ArcGISService

    monkeypatch.setattr(ArcGISService, "create_roi_buffer", staticmethod(lambda *_a, **_k: SIMPLE_GEOMETRY))
    monkeypatch.setattr(
        ArcGISService,
        "query_features",
        staticmethod(lambda *_a, **_k: ArcGISFeatureQueryResult(features=features, warnings=warnings or [])),
    )


async def _call(module, tool_name, args):
    async with Client(module.mcp) as client:
        result = await client.call_tool(tool_name, args)
    return result


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

        assert _TOOL_NAME in asyncio.run(_names())


class TestCountiesTool:
    def test_returns_markdown_with_county(self, monkeypatch):
        module = _load_server()
        _install_mock_query(
            monkeypatch,
            [{"attributes": {"NAME": "Bernalillo County", "STATE": "35", "GEOID": "35001"}}],
        )
        result = asyncio.run(_call(module, _TOOL_NAME, {"latitude": 34.5, "longitude": -106.5, "buffer_miles": 25}))
        text = _text(result)
        assert "Counties within ROI" in text
        assert "Bernalillo County" in text
        assert "35001" in text

    def test_empty_result_is_graceful(self, monkeypatch):
        module = _load_server()
        _install_mock_query(monkeypatch, [])
        result = asyncio.run(_call(module, _TOOL_NAME, {"latitude": 34.5, "longitude": -106.5}))
        assert "No counties found within the ROI." in _text(result)

    def test_default_buffer_is_applied(self, monkeypatch):
        module = _load_server()
        _install_mock_query(monkeypatch, [])
        result = asyncio.run(_call(module, _TOOL_NAME, {"latitude": 34.5, "longitude": -106.5}))
        assert "Buffer: 25.0 miles" in _text(result)


class TestInputValidationThroughTool:
    def test_out_of_range_latitude_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, _TOOL_NAME, {"latitude": 999, "longitude": -106.5}))

    def test_zero_buffer_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, _TOOL_NAME, {"latitude": 34.5, "longitude": -106.5, "buffer_miles": 0}))
