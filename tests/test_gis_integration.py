"""
Integration tests for the GIS MCP server.

These load ``gis/server.py`` through a real ``fastmcp.Client`` and exercise the
full tool -> api -> formatter path, with only the ArcGIS buffer layer mocked.
This mirrors the loading approach in ``test_usace_integration.py``.

Registered tool names on this server:
    summarize_roi_buffer, get_roi_geojson, calculate_roi_area
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from fastmcp import Client

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "gis"
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}

_TOOL_NAMES = {
    "summarize_roi_buffer",
    "get_roi_geojson",
    "calculate_roi_area",
}


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_gis_int_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_gis_int_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_gis_int_server"] = module
    spec.loader.exec_module(module)
    return module


def _install_mock_buffer(geometry=SIMPLE_GEOMETRY):
    from nepa_mcp_common.arcgis import ArcGISService

    ArcGISService.create_roi_buffer = staticmethod(lambda *_a, **_k: geometry)


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
    def test_all_three_tools_registered(self):
        module = _load_server()

        async def _names():
            async with Client(module.mcp) as client:
                return {t.name for t in await client.list_tools()}

        assert _TOOL_NAMES.issubset(asyncio.run(_names()))


class TestCalculateAreaTool:
    def test_returns_area_markdown(self):
        module = _load_server()
        _install_mock_buffer()
        result = asyncio.run(
            _call(module, "calculate_roi_area", {"latitude": 34.5, "longitude": -106.5, "buffer_miles": 25})
        )
        text = _text(result)
        assert "ROI Area Calculation" in text
        assert "square miles" in text
        assert "acres" in text

    def test_uses_default_buffer(self):
        module = _load_server()
        _install_mock_buffer()
        result = asyncio.run(_call(module, "calculate_roi_area", {"latitude": 34.5, "longitude": -106.5}))
        assert "Buffer: 25.0 miles" in _text(result)


class TestGeojsonTool:
    def test_returns_valid_geojson(self):
        module = _load_server()
        _install_mock_buffer()
        result = asyncio.run(
            _call(module, "get_roi_geojson", {"latitude": 34.5, "longitude": -106.5, "buffer_miles": 25})
        )
        payload = json.loads(_text(result))
        assert payload["type"] == "FeatureCollection"
        assert len(payload["features"]) == 2
        assert payload["metadata"]["center"] == {"latitude": 34.5, "longitude": -106.5}


class TestSummaryTool:
    def test_returns_summary_markdown(self):
        module = _load_server()
        _install_mock_buffer()
        result = asyncio.run(
            _call(
                module,
                "summarize_roi_buffer",
                {"latitude": 34.5, "longitude": -106.5, "buffer_miles": 25, "project_name": "Demo"},
            )
        )
        text = _text(result)
        assert "Region of Interest (ROI) Summary" in text
        assert "Project: Demo" in text
        assert "Extent:" in text


class TestInputValidationThroughTool:
    def test_out_of_range_latitude_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, "calculate_roi_area", {"latitude": 999, "longitude": -106.5}))

    def test_zero_buffer_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, "calculate_roi_area", {"latitude": 34.5, "longitude": -106.5, "buffer_miles": 0}))

    def test_buffer_above_max_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, "get_roi_geojson", {"latitude": 34.5, "longitude": -106.5, "buffer_miles": 250}))
