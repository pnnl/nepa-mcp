"""
Integration tests for the esa_ranges MCP server.

These load ``esa_ranges/server.py`` through a real ``fastmcp.Client`` and
exercise the full tool -> api -> formatter -> Markdown path, with only the
ArcGIS network layer mocked. This mirrors the loading approach in
``test_usace_integration.py``.
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
SERVER_DIR = ROOT / "esa_ranges"
SIMPLE_GEOMETRY = {
    "rings": [[[-121.0, 46.0], [-120.0, 46.0], [-120.0, 47.0], [-121.0, 47.0], [-121.0, 46.0]]],
    "spatialReference": {"wkid": 4326},
}

_TOOL_NAME = "get_esa_species_ranges_in_roi"

# Layer ids from esa_ranges/src/core/constants.py.
_LAYER2_ID = 2  # ESA_RANGES_LAYER_ID (CA + southern OR)
_LAYER1_ID = 1  # ESA_RANGES_FISH_LAYER_ID (WA/ID/OR + transboundary)


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_esa_int_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_esa_int_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_esa_int_server"] = module
    spec.loader.exec_module(module)
    return module


def _install_mock_query(module, layer_features, warnings=None, truncated=False):
    def query_features(_url, layer_id, _geometry, **_kwargs):
        feats = layer_features.get(layer_id, [])
        return ArcGISFeatureQueryResult(
            features=feats,
            warnings=warnings or [],
            truncated=truncated and bool(feats),
        )

    from nepa_mcp_common.arcgis import ArcGISService

    ArcGISService.create_roi_buffer = staticmethod(lambda *_a, **_k: SIMPLE_GEOMETRY)
    ArcGISService.query_features = staticmethod(query_features)


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


def _layer2_feature(*, listentity="STUCR", huc12="170200160601", area=999.0):
    return {
        "attributes": {
            "listentity": listentity,
            "liststatus": "T",
            "sciename": "3",
            "comname": "ST",
            "taxon": "3",
            "leadoffice": "WCR",
            "areasqkm": area,
            "huc12": huc12,
            "huc12_name": "Parsons Canyon-Columbia River",
            "feature_access": "AC",
        },
        "geometry": SIMPLE_GEOMETRY,
    }


class TestToolRegistration:
    def test_tool_registered(self):
        module = _load_server()

        async def _names():
            async with Client(module.mcp) as client:
                return {t.name for t in await client.list_tools()}

        assert _TOOL_NAME in asyncio.run(_names())


class TestSpeciesRangeTool:
    def test_returns_markdown_with_entity_and_area(self):
        module = _load_server()
        _install_mock_query(module, {_LAYER2_ID: [_layer2_feature()], _LAYER1_ID: []})
        result = asyncio.run(_call(module, _TOOL_NAME, {"latitude": 46.47, "longitude": -119.30, "buffer_miles": 5}))
        text = _text(result)
        assert "NOAA ESA Species Ranges" in text
        assert "Steelhead (Upper Columbia River DPS)" in text
        assert "Area within ROI" in text
        assert "Section 7" in text

    def test_empty_result_is_graceful(self):
        module = _load_server()
        _install_mock_query(module, {_LAYER2_ID: [], _LAYER1_ID: []})
        result = asyncio.run(_call(module, _TOOL_NAME, {"latitude": 46.47, "longitude": -119.30, "buffer_miles": 5}))
        assert "No NOAA ESA-listed species ranges found within the ROI." in _text(result)

    def test_default_buffer_applies(self):
        module = _load_server()
        _install_mock_query(module, {_LAYER2_ID: [_layer2_feature()], _LAYER1_ID: []})
        result = asyncio.run(_call(module, _TOOL_NAME, {"latitude": 46.47, "longitude": -119.30}))
        assert "**Buffer:** 25.0 miles" in _text(result)

    def test_truncation_surfaces_partial_area(self):
        module = _load_server()
        _install_mock_query(module, {_LAYER2_ID: [_layer2_feature()], _LAYER1_ID: []}, truncated=True)
        result = asyncio.run(_call(module, _TOOL_NAME, {"latitude": 46.47, "longitude": -119.30, "buffer_miles": 5}))
        text = _text(result)
        assert "Partial area within ROI" in text
        assert "may be understated" in text


class TestInputValidationThroughTool:
    def test_out_of_range_latitude_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, _TOOL_NAME, {"latitude": 999, "longitude": -119.30}))

    def test_zero_buffer_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, _TOOL_NAME, {"latitude": 46.47, "longitude": -119.30, "buffer_miles": 0}))
