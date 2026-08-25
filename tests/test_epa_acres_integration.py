"""
Integration tests for the EPA ACRES MCP server.

These load ``epa_acres/server.py`` through a real ``fastmcp.Client`` and
exercise the full tool -> api -> formatter -> Markdown path, with only the
ArcGIS network layer mocked. This mirrors the loading approach in
``test_padus_integration.py``.
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
SERVER_DIR = ROOT / "epa_acres"
SIMPLE_GEOMETRY = {
    "rings": [[[-80.1, 40.3], [-79.9, 40.3], [-79.9, 40.5], [-80.1, 40.5], [-80.1, 40.3]]],
    "spatialReference": {"wkid": 4326},
}

_TOOL_NAME = "get_epa_acres_properties_in_roi"


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_epa_acres_int_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_epa_acres_int_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_epa_acres_int_server"] = module
    spec.loader.exec_module(module)
    return module


def _install_mock_query(module, features, warnings=None):
    from nepa_mcp_common.arcgis import ArcGISService

    ArcGISService.create_roi_buffer = staticmethod(lambda *_a, **_k: SIMPLE_GEOMETRY)
    ArcGISService.query_features = staticmethod(
        lambda *_a, **_k: ArcGISFeatureQueryResult(features=features, warnings=warnings or [])
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

    def test_pagination_schema_is_bounded_and_documented(self):
        module = _load_server()

        async def _tool():
            async with Client(module.mcp) as client:
                return next(tool for tool in await client.list_tools() if tool.name == _TOOL_NAME)

        properties = asyncio.run(_tool()).inputSchema["properties"]
        assert properties["max_results"]["minimum"] == 1
        assert properties["max_results"]["maximum"] == 100
        assert properties["max_results"]["default"] == 100
        assert properties["result_offset"]["minimum"] == 0
        assert properties["result_offset"]["maximum"] == 9999
        assert properties["result_offset"]["default"] == 0


class TestPropertiesTool:
    def test_returns_markdown_with_record(self, monkeypatch):
        module = _load_server()
        _install_mock_query(
            module,
            [
                {
                    "attributes": {
                        "registry_id": "110038700607",
                        "primary_name": "FORMER BROOKS ARMORED CAR",
                        "city_name": "PITTSBURGH",
                        "state_code": "PA",
                        "epa_region": "Region 03",
                        "pgm_sys_id": "15332",
                        "latitude": 40.430555,
                        "longitude": -79.980113,
                    }
                }
            ],
        )
        result = asyncio.run(_call(module, _TOOL_NAME, {"latitude": 40.44, "longitude": -79.99, "buffer_miles": 25}))
        text = _text(result)
        assert "**Total ACRES Properties:** 1" in text
        assert "FORMER BROOKS ARMORED CAR" in text
        assert "FRS Registry ID 110038700607" in text
        assert "ACRES ID 15332" in text
        assert "EPA Envirofacts Brownfields ArcGIS layer" in text

    def test_empty_result_is_graceful(self, monkeypatch):
        module = _load_server()
        _install_mock_query(module, [])
        result = asyncio.run(_call(module, _TOOL_NAME, {"latitude": 40.44, "longitude": -79.99}))
        text = _text(result)
        assert "**Total ACRES Properties:** 0" in text
        assert "not a complete inventory of brownfields or contaminated sites" in text

    def test_second_page_returns_later_nearest_first_records(self, monkeypatch):
        module = _load_server()
        features = [
            {
                "attributes": {
                    "registry_id": str(110000000000 + index),
                    "primary_name": f"SITE {index}",
                    "state_code": "PA",
                    "latitude": 40.44 + index / 1000,
                    "longitude": -79.99,
                }
            }
            for index in range(5)
        ]
        _install_mock_query(module, features)
        result = asyncio.run(
            _call(
                module,
                _TOOL_NAME,
                {
                    "latitude": 40.44,
                    "longitude": -79.99,
                    "buffer_miles": 25,
                    "max_results": 2,
                    "result_offset": 2,
                },
            )
        )
        text = _text(result)
        assert "Property Details (3–4 of 5)" in text
        assert "SITE 2" in text
        assert "SITE 3" in text
        assert "SITE 0" not in text
        assert "result_offset=4" in text


class TestInputValidationThroughTool:
    def test_out_of_range_latitude_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, _TOOL_NAME, {"latitude": 999, "longitude": -79.99}))

    def test_zero_buffer_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, _TOOL_NAME, {"latitude": 40.44, "longitude": -79.99, "buffer_miles": 0}))

    def test_invalid_pagination_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(
                _call(
                    module,
                    _TOOL_NAME,
                    {"latitude": 40.44, "longitude": -79.99, "max_results": 0},
                )
            )
        with pytest.raises(Exception):
            asyncio.run(
                _call(
                    module,
                    _TOOL_NAME,
                    {"latitude": 40.44, "longitude": -79.99, "result_offset": -1},
                )
            )
