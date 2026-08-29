"""Unit tests for USDA-NRCS SSURGO retrieval, aggregation, and formatting."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "nrcs_soils"
SIMPLE_GEOMETRY = {
    "rings": [[[-121.62, 37.72], [-121.61, 37.72], [-121.61, 37.73], [-121.62, 37.72]]],
    "spatialReference": {"wkid": 4326},
}
SQ_METERS_PER_ACRE = 4046.8564224


def _load_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_nrcs_unit_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_nrcs_unit_api", SERVER_DIR / "src" / "apis" / "nrcs_soils_api.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_nrcs_unit_api"] = module
    spec.loader.exec_module(module)
    return module


def _mapunit_payload():
    return {
        "Table": [
            ["mukey", "musym", "muname", "farmlndcl", "areasymbol", "saverest", "area_sqm"],
            [
                "1001",
                "Aa",
                "Alpha loam",
                "All areas are prime farmland",
                "CA001",
                "8/1/2026 12:00:00 AM",
                str(60 * SQ_METERS_PER_ACRE),
            ],
            [
                "1002",
                "Bb",
                "Beta clay",
                "Not prime farmland",
                "CA001",
                "8/1/2026 12:00:00 AM",
                str(40 * SQ_METERS_PER_ACRE),
            ],
        ],
    }


def _constraint_payload():
    return {
        "Table": [
            ["mukey", "cokey", "compname", "comppct_r", "majcompflag", "hydgrp", "drainagecl", "slope_r"],
            ["1001", "2001", "Alpha", "80", "Yes", "B", "Well drained", "5"],
            ["1001", "2002", "Wet inclusion", "20", "No", "D", "Poorly drained", "2"],
            ["1002", "2003", "Beta", "100", "Yes", "C", "Moderately well drained", "12"],
        ],
        "Table1": [
            ["cokey", "reskind", "resdept_l", "resdept_r", "resdept_h"],
            ["2003", "Paralithic bedrock", "60", "80", "100"],
        ],
        "Table2": [
            ["cokey", "chkey", "hzname", "hzdept_r", "hzdepb_r", "kffact", "kwfact"],
            ["2001", "3001", "A", "0", "20", ".24", ".24"],
            ["2003", "3002", "Ap", "0", "18", ".37", ".32"],
        ],
    }


def _install_success(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", staticmethod(lambda *_a, **_k: SIMPLE_GEOMETRY))
    monkeypatch.setattr(api, "esri_polygon_to_wgs84_wkt", lambda *_a, **_k: "POLYGON((-1 0,0 0,0 1,-1 0))")
    monkeypatch.setattr(
        api,
        "clipped_union_area_from_esri_geometries",
        lambda *_a, **_k: api.ClippedAreaResult(
            area_square_meters=100 * SQ_METERS_PER_ACRE,
            status=api.SpatialAreaStatus.OK,
            complete=True,
        ),
    )

    def fake_query(query):
        if "FROM mupolygon AS mp" in query:
            return _mapunit_payload()
        payload = _constraint_payload()
        if "FROM component" in query and "SELECT cokey FROM component" not in query:
            return {"Table": payload["Table"]}
        if "FROM corestrictions" in query:
            return {"Table": payload["Table1"]}
        if "FROM chorizon" in query:
            return {"Table": payload["Table2"]}
        raise AssertionError(f"Unexpected query: {query}")

    monkeypatch.setattr(api, "_post_sda_query", fake_query)


def test_mapunits_have_clipped_areas_and_source_versions(monkeypatch):
    api = _load_api()
    _install_success(api, monkeypatch)

    result = api.get_soil_mapunits_in_roi(37.727, -121.616, 1.0)

    assert result["mapunit_count"] == 2
    assert result["coverage_pct"] == pytest.approx(100.0)
    assert result["mapunits"][0]["area_acres"] == pytest.approx(60.0)
    assert result["mapunits"][0]["roi_percentage"] == pytest.approx(60.0)
    assert result["mapunits"][0]["survey_area_symbol"] == "CA001"
    assert result["data_unavailable"] is False


def test_farmland_summary_preserves_exact_classes(monkeypatch):
    api = _load_api()
    _install_success(api, monkeypatch)

    result = api.get_farmland_classification_in_roi(37.727, -121.616)
    text = api.format_farmland_classification_summary(result)

    assert result["classifications"]["All areas are prime farmland"]["area_acres"] == pytest.approx(60.0)
    assert "All areas are prime farmland: 60.00 acres" in text
    assert "1 map unit)" in text
    assert "does not determine Farmland Protection Policy Act" in text
    assert "not geotechnical advice" in text
    assert "wetland delineation" in text


def test_constraint_summary_keeps_component_and_horizon_context(monkeypatch):
    api = _load_api()
    _install_success(api, monkeypatch)

    result = api.summarize_soil_constraints_for_siting(37.727, -121.616)
    indicators = result["indicators"]
    text = api.format_soil_constraints_summary(result)

    assert indicators["hydrologic_group_estimated_acres"] == {"B": 48.0, "C": 40.0, "D": 12.0}
    assert indicators["drainage_class_estimated_acres"]["Poorly drained"] == pytest.approx(12.0)
    assert indicators["representative_slope_pct_min"] == 2.0
    assert indicators["representative_slope_pct_max"] == 12.0
    assert indicators["shallowest_restriction"]["depth_representative_cm"] == 80.0
    assert indicators["surface_k_factor_min"] == 0.24
    assert indicators["surface_k_factor_max"] == 0.37
    assert "Potential Siting Attention Indicators (not suitability ratings)" in text
    assert "No composite constructability or suitability score is produced" in text
    assert "Paralithic bedrock at 80 cm" in text


def test_mapunit_formatter_pages_bounded_details(monkeypatch):
    api = _load_api()
    _install_success(api, monkeypatch)
    result = api.get_soil_mapunits_in_roi(37.727, -121.616)

    text = api.format_soil_mapunits_summary(result, max_results=1, result_offset=1)

    assert "Map Unit Details (2–2 of 2)" in text
    assert "Beta clay" in text
    assert "Alpha loam" not in text


def test_table_parser_rejects_malformed_rows():
    api = _load_api()

    with pytest.raises(Exception, match="malformed Table rows"):
        api._table_rows({"Table": [["a", "b"], ["only-one"]]}, "Table")


def test_tiny_nonzero_distribution_is_not_rendered_as_zero_percent():
    api = _load_api()

    lines = api._format_distribution({"D": 0.004}, 100.0)

    assert lines == ["  D: 0.00 estimated acres; less than 0.01% of ROI"]


def test_empty_restrictions_do_not_hide_horizon_k_factors(monkeypatch):
    api = _load_api()
    _install_success(api, monkeypatch)
    payload = _constraint_payload()
    payload["Table1"] = [["cokey", "reskind", "resdept_l", "resdept_r", "resdept_h"]]

    def fake_query(query):
        if "FROM mupolygon AS mp" in query:
            return _mapunit_payload()
        if "FROM component" in query and "SELECT cokey FROM component" not in query:
            return {"Table": payload["Table"]}
        if "FROM corestrictions" in query:
            return {"Table": payload["Table1"]}
        if "FROM chorizon" in query:
            return {"Table": payload["Table2"]}
        raise AssertionError(f"Unexpected query: {query}")

    monkeypatch.setattr(api, "_post_sda_query", fake_query)
    result = api.summarize_soil_constraints_for_siting(37.727, -121.616)

    assert result["indicators"]["shallowest_restriction"] is None
    assert result["indicators"]["surface_k_factor_min"] == pytest.approx(0.24)
    assert result["indicators"]["surface_k_factor_max"] == pytest.approx(0.37)
