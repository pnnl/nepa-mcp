"""
Integration tests for the EFH MCP server.

These load ``efh/server.py`` through a real ``fastmcp.Client`` and exercise the
full tool -> api -> formatter -> Markdown path, with only the ArcGIS network
layer mocked. This mirrors the loading approach in ``test_usace_integration.py``.
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
SERVER_DIR = ROOT / "efh"
SIMPLE_GEOMETRY = {
    "rings": [[[-121.0, 46.0], [-120.0, 46.0], [-120.0, 47.0], [-121.0, 47.0], [-121.0, 46.0]]],
    "spatialReference": {"wkid": 4326},
}

_TOOL_NAMES = {
    "get_efh_hapc",
    "get_efh_areas",
    "get_efh_salmon",
    "get_efh_hms_cps_groundfish",
}


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_efh_int_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_efh_int_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_efh_int_server"] = module
    spec.loader.exec_module(module)
    return module


def _efh_feature(*, geometry=SIMPLE_GEOMETRY, acres=999.0, truncated=False):
    feature = {
        "attributes": {
            "SITENAME_L": "Pacific Coast Groundfish",
            "LIFESTAGE": "ALL",
            "TYPE": "EFH",
            "FMC": "PFMC",
            "ZONE": "ALL",
            "ACRES": acres,
        }
    }
    if geometry is not None:
        feature["geometry"] = geometry
    return feature


def _install_mock_query(feature_map, warnings=None, truncated=False):
    def query_features(url, _layer_id, _geometry, *, service_name=None, **_kwargs):
        for key, feats in feature_map.items():
            if key in (service_name or "") or key in url:
                return ArcGISFeatureQueryResult(features=feats, warnings=warnings or [], truncated=truncated)
        return ArcGISFeatureQueryResult(features=[], warnings=warnings or [])

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


class TestHapcTool:
    def test_returns_markdown_with_hapc(self):
        module = _load_server()
        _install_mock_query({"HAPC": [{"attributes": {"HAPC_Siten": "Estuaries", "FisheryM_5": "PFMC"}}]})
        result = asyncio.run(_call(module, "get_efh_hapc", {"latitude": 46.5, "longitude": -120.5, "buffer_miles": 25}))
        text = _text(result)
        assert "Habitat Areas of Particular Concern" in text
        assert "Estuaries" in text

    def test_empty_result_is_graceful(self):
        module = _load_server()
        _install_mock_query({})
        result = asyncio.run(_call(module, "get_efh_hapc", {"latitude": 46.5, "longitude": -120.5}))
        assert "No Habitat Areas of Particular Concern found within the ROI." in _text(result)


class TestSalmonTool:
    def test_returns_watershed_table(self):
        module = _load_server()
        _install_mock_query(
            {
                "salmon": [
                    {
                        "attributes": {
                            "HUC_8": 17110006,
                            "HUC_8_Name": "Puget Sound",
                            "State": "WA",
                            "ChinookEFH": "Yes",
                            "Coho_EFH": "Yes",
                            "Pink_EFH": "No",
                            "All_EFH": "Yes",
                        }
                    }
                ]
            }
        )
        result = asyncio.run(_call(module, "get_efh_salmon", {"latitude": 46.5, "longitude": -120.5}))
        text = _text(result)
        assert "Puget Sound" in text
        assert "Salmon Essential Fish Habitat" in text


class TestHmsToolAreaClipping:
    def test_shows_area_within_roi_and_source_label(self):
        module = _load_server()
        _install_mock_query({"species": [_efh_feature()]})
        result = asyncio.run(_call(module, "get_efh_hms_cps_groundfish", {"latitude": 46.5, "longitude": -120.5}))
        text = _text(result)
        assert "Area within ROI:" in text
        assert "Source feature-area total (not clipped to ROI):" in text
        assert "Pacific Coast Groundfish" in text

    def test_truncated_result_shows_partial_area(self):
        module = _load_server()
        _install_mock_query({"species": [_efh_feature()]}, truncated=True)
        result = asyncio.run(_call(module, "get_efh_hms_cps_groundfish", {"latitude": 46.5, "longitude": -120.5}))
        text = _text(result)
        assert "Partial area within ROI:" in text


class TestInputValidationThroughTool:
    def test_out_of_range_latitude_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, "get_efh_hapc", {"latitude": 999, "longitude": -120.5}))

    def test_zero_buffer_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, "get_efh_hapc", {"latitude": 46.5, "longitude": -120.5, "buffer_miles": 0}))
