"""MCP-contract integration tests for the NRCS soils server."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest
from fastmcp import Client

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "nrcs_soils"
TOOL_NAMES = {
    "get_nrcs_ssurgo_mapunits_in_roi",
    "analyze_nrcs_ssurgo_soil_constraints",
    "get_nrcs_ssurgo_farmland_classification_in_roi",
}


def _load_server():
    for name in list(sys.modules):
        if name == "src" or name.startswith("src.") or name.startswith("_nrcs_integration_"):
            sys.modules.pop(name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_nrcs_integration_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_nrcs_integration_server"] = module
    spec.loader.exec_module(module)
    return module


def _base_data():
    return {
        "center": {"latitude": 37.727, "longitude": -121.616},
        "buffer_miles": 1.0,
        "retrieved_at": "2026-08-28T00:00:00+00:00",
        "roi_area_acres": 100.0,
        "mapped_area_acres": 100.0,
        "unmapped_area_acres": 0.0,
        "coverage_pct": 100.0,
        "mapunit_count": 1,
        "mapunits": [
            {
                "mukey": "1001",
                "symbol": "Aa",
                "name": "Alpha loam",
                "farmland_classification": "All areas are prime farmland",
                "survey_area_symbol": "CA001",
                "survey_version_date": "2026-08-01",
                "area_square_meters": 404685.64224,
                "area_acres": 100.0,
                "roi_percentage": 100.0,
            }
        ],
        "warnings": [],
        "truncated": False,
        "partial": False,
        "skipped_records": 0,
        "data_unavailable": False,
    }


async def _call(module, tool_name, args):
    async with Client(module.mcp) as client:
        return await client.call_tool(tool_name, args)


def _text(result) -> str:
    return "\n".join(getattr(block, "text", "") for block in result.content if getattr(block, "text", ""))


def test_three_tools_are_registered():
    module = _load_server()

    async def names():
        async with Client(module.mcp) as client:
            return {tool.name for tool in await client.list_tools()}

    assert asyncio.run(names()) == TOOL_NAMES


def test_mapunit_tool_formats_api_result(monkeypatch):
    module = _load_server()
    monkeypatch.setattr(module, "get_soil_mapunits_in_roi", lambda *_a, **_k: _base_data())

    result = asyncio.run(_call(module, "get_nrcs_ssurgo_mapunits_in_roi", {"latitude": 37.727, "longitude": -121.616}))
    text = _text(result)

    assert "Alpha loam" in text
    assert "100.00%" in text
    assert "soil-survey screening" in text.lower()
    assert "wetland delineation" in text.lower()


def test_farmland_tool_formats_exact_class(monkeypatch):
    module = _load_server()
    data = _base_data()
    data["classifications"] = {
        "All areas are prime farmland": {"area_acres": 100.0, "roi_percentage": 100.0, "mapunit_count": 1}
    }
    monkeypatch.setattr(module, "get_farmland_classification_in_roi", lambda *_a, **_k: data)

    result = asyncio.run(
        _call(
            module,
            "get_nrcs_ssurgo_farmland_classification_in_roi",
            {"latitude": 37.727, "longitude": -121.616},
        )
    )

    assert "All areas are prime farmland" in _text(result)
    assert "AD-1006" in _text(result)


def test_constraint_tool_returns_non_scored_summary(monkeypatch):
    module = _load_server()
    data = _base_data()
    data["components"] = []
    data["indicators"] = {
        "hydrologic_group_estimated_acres": {"D": 100.0},
        "drainage_class_estimated_acres": {"Poorly drained": 100.0},
        "representative_slope_pct_min": 12.0,
        "representative_slope_pct_max": 12.0,
        "steepest_component": {
            "name": "Alpha",
            "component_percentage": 100.0,
            "mukey": "1001",
            "representative_slope_pct": 12.0,
        },
        "shallowest_restriction": None,
        "surface_k_factor_min": None,
        "surface_k_factor_max": None,
        "farmland_classification_acres": {"All areas are prime farmland": 100.0},
    }
    monkeypatch.setattr(module, "summarize_soil_constraints_for_siting", lambda *_a, **_k: data)

    result = asyncio.run(
        _call(module, "analyze_nrcs_ssurgo_soil_constraints", {"latitude": 37.727, "longitude": -121.616})
    )
    text = _text(result)

    assert "Hydrologic Soil Groups" in text
    assert "not suitability ratings" in text
    assert "No composite constructability or suitability score" in text


def test_tool_rejects_buffer_above_soil_limit():
    module = _load_server()

    with pytest.raises(Exception):
        asyncio.run(
            _call(
                module,
                "get_nrcs_ssurgo_mapunits_in_roi",
                {"latitude": 37.727, "longitude": -121.616, "buffer_miles": 10.1},
            )
        )
