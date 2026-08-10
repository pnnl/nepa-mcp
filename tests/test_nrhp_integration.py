"""
Integration tests for the NRHP MCP server.

These load ``nrhp/server.py`` through a real ``fastmcp.Client`` and exercise the
full tool -> api -> formatter -> Markdown path, with only the ArcGIS network
layer mocked. This mirrors the USACE integration test loading approach.
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
SERVER_DIR = ROOT / "nrhp"
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}

_TOOL_NAME = "get_nrhp_properties_in_roi"


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_nrhp_int_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_nrhp_int_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_nrhp_int_server"] = module
    spec.loader.exec_module(module)
    return module


def _install_mock_query(feature_map, warnings=None):
    def query_features(url, _layer_id, _geometry, *, service_name=None, **_kwargs):
        for key, feats in feature_map.items():
            if key in (service_name or "") or key in url:
                return ArcGISFeatureQueryResult(features=feats, warnings=warnings or [])
        return ArcGISFeatureQueryResult(features=[], warnings=warnings or [])

    from nepa_mcp_common.arcgis import ArcGISService

    ArcGISService.create_roi_buffer = staticmethod(lambda *_a, **_k: SIMPLE_GEOMETRY)
    ArcGISService.query_features = staticmethod(query_features)


def _feature(refnum, name, **overrides):
    attrs = {
        "NRIS_Refnum": refnum,
        "RESNAME": name,
        "ResType": "Building",
        "City": "Santa Fe",
        "County": "Santa Fe",
        "State": "NM",
        "CertDate": "1975",
        "Is_NHL": "",
        "STATUS": "Listed",
        "NARA_URL": "",
        "IS_EXTANT": "Y",
    }
    attrs.update(overrides)
    return {"attributes": attrs}


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


class TestPropertyTool:
    def test_returns_markdown_with_property(self):
        module = _load_server()
        _install_mock_query(
            {"Polygons": [_feature("111", "Palace of the Governors", Is_NHL="X", NARA_URL="https://nara/111")]}
        )
        result = asyncio.run(_call(module, _TOOL_NAME, {"latitude": 35.6, "longitude": -105.9, "buffer_miles": 25}))
        text = _text(result)
        assert "National Register of Historic Places" in text
        assert "Palace of the Governors" in text
        assert "🏛️ **NHL**" in text
        assert "Total NRHP Properties:** 1" in text

    def test_empty_result_is_graceful(self):
        module = _load_server()
        _install_mock_query({})
        result = asyncio.run(_call(module, _TOOL_NAME, {"latitude": 35.6, "longitude": -105.9}))
        text = _text(result)
        assert "No NRHP-listed properties were identified within the ROI buffer." in text

    def test_dedup_across_layers_through_tool(self):
        module = _load_server()
        _install_mock_query(
            {
                "Polygons": [_feature("999", "Polygon Name")],
                "Points": [_feature("999", "Point Name")],
            }
        )
        result = asyncio.run(_call(module, _TOOL_NAME, {"latitude": 35.6, "longitude": -105.9}))
        text = _text(result)
        assert "Total NRHP Properties:** 1" in text
        assert "Polygon Name" in text
        assert "Point Name" not in text


class TestInputValidationThroughTool:
    def test_out_of_range_latitude_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, _TOOL_NAME, {"latitude": 999, "longitude": -105.9}))

    def test_zero_buffer_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, _TOOL_NAME, {"latitude": 35.6, "longitude": -105.9, "buffer_miles": 0}))
