"""
Integration tests for the USACE MCP server.

These load ``usace/server.py`` through a real ``fastmcp.Client`` and exercise
the full tool -> api -> formatter -> Markdown path, with only the ArcGIS network
layer mocked. This mirrors the loading approach in ``test_mcp_contracts.py``.
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
SERVER_DIR = ROOT / "usace"
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}

_TOOL_NAMES = {
    "get_usace_regulatory_district",
    "get_usace_wetland_regions_in_roi",
    "get_usace_wetland_subregions_in_roi",
    "analyze_usace_jurisdiction",
}


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_usace_int_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_usace_int_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_usace_int_server"] = module
    spec.loader.exec_module(module)
    return module


def _install_mock_query(module, feature_map, warnings=None):
    def query_features(url, _layer_id, _geometry, *, service_name=None, **_kwargs):
        for key, feats in feature_map.items():
            if key in (service_name or "") or key in url:
                return ArcGISFeatureQueryResult(features=feats, warnings=warnings or [])
        return ArcGISFeatureQueryResult(features=[], warnings=warnings or [])

    # Patch on the ArcGISService used by the api module.
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


class TestToolRegistration:
    def test_all_four_tools_registered(self):
        module = _load_server()

        async def _names():
            async with Client(module.mcp) as client:
                return {t.name for t in await client.list_tools()}

        assert _TOOL_NAMES.issubset(asyncio.run(_names()))


class TestRegulatoryDistrictTool:
    def test_returns_markdown_with_district(self, monkeypatch):
        module = _load_server()
        _install_mock_query(
            module,
            {"Regulatory Boundary": [{"attributes": {"ERO_FORMALNAME": "Albuquerque District", "DIST_ABBR": "SPA"}}]},
        )
        result = asyncio.run(
            _call(module, "get_usace_regulatory_district", {"latitude": 34.5, "longitude": -106.5, "buffer_miles": 25})
        )
        text = _text(result)
        assert "USACE Regulatory Districts" in text
        assert "Albuquerque District" in text

    def test_empty_result_is_graceful(self, monkeypatch):
        module = _load_server()
        _install_mock_query(module, {})
        result = asyncio.run(_call(module, "get_usace_regulatory_district", {"latitude": 34.5, "longitude": -106.5}))
        assert "No USACE districts found in ROI." in _text(result)


class TestWetlandRegionTool:
    def test_returns_region_and_supplement(self, monkeypatch):
        module = _load_server()
        _install_mock_query(module, {"Wetland Regions": [{"attributes": {"REGION": "Arid West"}}]})
        result = asyncio.run(_call(module, "get_usace_wetland_regions_in_roi", {"latitude": 34.5, "longitude": -106.5}))
        text = _text(result)
        assert "Arid West" in text
        assert "usace.contentdm.oclc.org" in text


class TestComprehensiveTool:
    def test_combines_all_sections(self, monkeypatch):
        module = _load_server()
        _install_mock_query(
            module,
            {
                "Regulatory Boundary": [{"attributes": {"ERO_FORMALNAME": "Albuquerque District"}}],
                "Wetland Regions": [{"attributes": {"REGION": "Arid West"}}],
                "Wetland Subregions": [{"attributes": {"ADS_SUB_NM": "Sub A", "ADS_REGSUP": "AW"}}],
            },
        )
        result = asyncio.run(_call(module, "analyze_usace_jurisdiction", {"latitude": 34.5, "longitude": -106.5}))
        text = _text(result)
        assert "USACE Jurisdictional Analysis" in text
        assert "Albuquerque District" in text
        assert "Arid West" in text
        assert "Section 404 Compliance Notes:" in text


class TestInputValidationThroughTool:
    def test_out_of_range_latitude_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, "get_usace_regulatory_district", {"latitude": 999, "longitude": -106.5}))

    def test_zero_buffer_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(
                _call(
                    module, "get_usace_regulatory_district", {"latitude": 34.5, "longitude": -106.5, "buffer_miles": 0}
                )
            )
