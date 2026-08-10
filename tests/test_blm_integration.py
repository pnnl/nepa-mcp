"""
Integration tests for the BLM MCP server.

These load ``blm/server.py`` through a real ``fastmcp.Client`` and exercise
the full tool -> api -> formatter -> Markdown path, with only the ArcGIS network
layer mocked.
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
SERVER_DIR = ROOT / "blm"
SIMPLE_GEOMETRY = {
    "rings": [[[-112.0, 38.0], [-111.0, 38.0], [-111.0, 39.0], [-112.0, 39.0], [-112.0, 38.0]]],
    "spatialReference": {"wkid": 4326},
}

_TOOL_NAMES = {
    "get_blm_land_use_plans_in_roi",
    "get_blm_wilderness_areas_in_roi",
    "get_blm_national_monuments_in_roi",
}


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_blm_int_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_blm_int_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_blm_int_server"] = module
    spec.loader.exec_module(module)
    return module


def _install_mock_query(module, feature_map, warnings=None):
    def query_features(url, _layer_id, _geometry, *, service_name=None, **_kwargs):
        for key, feats in feature_map.items():
            if key in (service_name or "") or key in url:
                return ArcGISFeatureQueryResult(features=feats, warnings=warnings or [])
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
    def test_all_three_tools_registered(self):
        module = _load_server()

        async def _names():
            async with Client(module.mcp) as client:
                return {t.name for t in await client.list_tools()}

        assert _TOOL_NAMES.issubset(asyncio.run(_names()))


class TestLandUsePlansTool:
    def test_returns_markdown_with_plan(self, monkeypatch):
        module = _load_server()
        _install_mock_query(
            module,
            {"land use plans": [{"attributes": {"LUPName": "Grand Staircase RMP", "AdminSt": "UT", "RODyear": 2020}}]},
        )
        result = asyncio.run(
            _call(module, "get_blm_land_use_plans_in_roi", {"latitude": 38.5, "longitude": -111.5, "buffer_miles": 25})
        )
        text = _text(result)
        assert "BLM Land Use Plans within ROI" in text
        assert "Grand Staircase RMP" in text
        assert "43 CFR 1610.5" in text

    def test_empty_result_is_graceful(self, monkeypatch):
        module = _load_server()
        _install_mock_query(module, {})
        result = asyncio.run(_call(module, "get_blm_land_use_plans_in_roi", {"latitude": 38.5, "longitude": -111.5}))
        assert "No BLM land use plans found in the ROI." in _text(result)


class TestWildernessTool:
    def test_returns_wilderness_area(self, monkeypatch):
        module = _load_server()
        _install_mock_query(
            module,
            {"wilderness": [{"attributes": {"NLCS_NAME": "Paria Canyon Wilderness", "ADMIN_ST": "AZ"}}]},
        )
        result = asyncio.run(_call(module, "get_blm_wilderness_areas_in_roi", {"latitude": 38.5, "longitude": -111.5}))
        text = _text(result)
        assert "Paria Canyon Wilderness" in text
        assert "Wilderness Act of 1964" in text


class TestNationalMonumentsTool:
    def test_returns_monument(self, monkeypatch):
        module = _load_server()
        _install_mock_query(
            module,
            {"national monuments": [{"attributes": {"NCA_NAME": "Grand Staircase-Escalante NM", "STATE_ADMN": "UT"}}]},
        )
        result = asyncio.run(
            _call(module, "get_blm_national_monuments_in_roi", {"latitude": 38.5, "longitude": -111.5})
        )
        text = _text(result)
        assert "Grand Staircase-Escalante NM" in text
        assert "Extraordinary Circumstances" in text


class TestInputValidationThroughTool:
    def test_out_of_range_latitude_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, "get_blm_land_use_plans_in_roi", {"latitude": 999, "longitude": -111.5}))

    def test_zero_buffer_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(
                _call(
                    module,
                    "get_blm_land_use_plans_in_roi",
                    {"latitude": 38.5, "longitude": -111.5, "buffer_miles": 0},
                )
            )
