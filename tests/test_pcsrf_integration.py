"""
Integration tests for the PCSRF MCP server.

These load ``pcsrf/server.py`` through a real ``fastmcp.Client`` and exercise
the full tool -> api -> formatter -> Markdown path, with only the ArcGIS network
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
SERVER_DIR = ROOT / "pcsrf"
SIMPLE_GEOMETRY = {
    "rings": [[[-121.0, 46.0], [-120.0, 46.0], [-120.0, 47.0], [-121.0, 47.0], [-121.0, 46.0]]],
    "spatialReference": {"wkid": 4326},
}

_TOOL_NAMES = {
    "get_noaa_all_species_ranges_in_roi",
    "get_noaa_critical_habitat_20210904_in_roi",
    "get_atlantic_salmon_efh_hapc_in_roi",
    "get_pcsrf_projects_in_roi",
}


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_pcsrf_int_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_pcsrf_int_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_pcsrf_int_server"] = module
    spec.loader.exec_module(module)
    return module


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


def _ch_poly_feature(*, unit="Unit A", area=999.0):
    return {
        "attributes": {
            "COMNAME": "Test salmon",
            "SCIENAME": "Testus salmonus",
            "LISTENTITY": "Test salmon DPS",
            "LISTSTATUS": "Threatened",
            "UNIT": unit,
            "AREASqKm": area,
            "HABTYPE": "Estuary",
        },
        "geometry": SIMPLE_GEOMETRY,
    }


class TestToolRegistration:
    def test_all_four_tools_registered(self):
        module = _load_server()

        async def _names():
            async with Client(module.mcp) as client:
                return {t.name for t in await client.list_tools()}

        assert _TOOL_NAMES.issubset(asyncio.run(_names()))


class TestSpeciesRangesTool:
    def test_returns_markdown_with_species(self):
        module = _load_server()
        _install_mock_query(
            {
                "species ranges": [
                    {
                        "attributes": {
                            "COMNAME": "Chinook salmon",
                            "SCIENAME": "Oncorhynchus tshawytscha",
                            "LISTENTITY": "Chinook salmon ESU",
                            "LISTSTATUS": "Threatened",
                        }
                    }
                ]
            }
        )
        result = asyncio.run(
            _call(
                module,
                "get_noaa_all_species_ranges_in_roi",
                {"latitude": 46.5, "longitude": -120.5, "buffer_miles": 25},
            )
        )
        text = _text(result)
        assert "NOAA ESA-Listed Species Ranges" in text
        assert "Chinook salmon ESU" in text

    def test_empty_is_graceful(self):
        module = _load_server()
        _install_mock_query({})
        result = asyncio.run(
            _call(module, "get_noaa_all_species_ranges_in_roi", {"latitude": 46.5, "longitude": -120.5})
        )
        assert "No NOAA ESA-listed species ranges found within the ROI." in _text(result)


class TestCriticalHabitatTool:
    def test_polygon_area_labeled_within_roi(self):
        module = _load_server()
        _install_mock_query({"polygons": [_ch_poly_feature()]})
        result = asyncio.run(
            _call(module, "get_noaa_critical_habitat_20210904_in_roi", {"latitude": 46.5, "longitude": -120.5})
        )
        text = _text(result)
        assert "NOAA Critical Habitat" in text
        assert "Test salmon DPS" in text
        assert "within ROI" in text
        # Source feature-area total is disclosed alongside the clipped area.
        assert "Source feature-area total (not clipped to ROI)" in text

    def test_line_length_is_legacy_labeled(self):
        module = _load_server()
        _install_mock_query(
            {"lines": [{"attributes": {"LISTENTITY": "Test salmon DPS", "UNIT": "River", "Shape__Length": 1.0}}]}
        )
        result = asyncio.run(
            _call(module, "get_noaa_critical_habitat_20210904_in_roi", {"latitude": 46.5, "longitude": -120.5})
        )
        text = _text(result)
        assert "legacy estimate; not ROI-clipped" in text


class TestEFHTool:
    def test_area_acres_within_roi(self):
        module = _load_server()
        _install_mock_query(
            {
                "EFH": [
                    {
                        "attributes": {
                            "GNIS_Name": "Penobscot River",
                            "TYPE": "EFH",
                            "REGION": "GAR",
                            "Shape__Area": 5000.0,
                        },
                        "geometry": SIMPLE_GEOMETRY,
                    }
                ]
            }
        )
        result = asyncio.run(
            _call(module, "get_atlantic_salmon_efh_hapc_in_roi", {"latitude": 44.8, "longitude": -68.8})
        )
        text = _text(result)
        assert "Essential Fish Habitat" in text
        assert "Penobscot River" in text
        assert "Area within ROI:" in text
        assert "acres" in text


class TestProjectsTool:
    def test_projects_grouped_and_funding_summed(self):
        module = _load_server()
        _install_mock_query(
            {
                "projects": [
                    {
                        "attributes": {
                            "PROJECT_NAME": "Riparian Restoration",
                            "STATUS": "Completed",
                            "PCSRF_FUNDS": 100000.0,
                            "DESCRIPTION": "Planting native vegetation.",
                        }
                    }
                ]
            }
        )
        result = asyncio.run(_call(module, "get_pcsrf_projects_in_roi", {"latitude": 46.5, "longitude": -120.5}))
        text = _text(result)
        assert "PCSRF Salmon Recovery Projects" in text
        assert "Riparian Restoration" in text
        assert "$100,000.00" in text
        assert "### Completed" in text

    def test_empty_projects_is_graceful(self):
        module = _load_server()
        _install_mock_query({})
        result = asyncio.run(_call(module, "get_pcsrf_projects_in_roi", {"latitude": 46.5, "longitude": -120.5}))
        assert "No PCSRF projects found within the ROI." in _text(result)


class TestInputValidationThroughTool:
    def test_out_of_range_latitude_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, "get_pcsrf_projects_in_roi", {"latitude": 999, "longitude": -120.5}))

    def test_zero_buffer_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(
                _call(module, "get_pcsrf_projects_in_roi", {"latitude": 46.5, "longitude": -120.5, "buffer_miles": 0})
            )
