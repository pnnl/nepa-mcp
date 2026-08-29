"""Failure and partial-data tests for the NRCS soils server."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "nrcs_soils"
GEOMETRY = {
    "rings": [[[-121.62, 37.72], [-121.61, 37.72], [-121.61, 37.73], [-121.62, 37.72]]],
    "spatialReference": {"wkid": 4326},
}


def _load_api():
    for name in list(sys.modules):
        if name == "src" or name.startswith("src.") or name.startswith("_nrcs_resilience_"):
            sys.modules.pop(name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location(
        "_nrcs_resilience_api", SERVER_DIR / "src" / "apis" / "nrcs_soils_api.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_nrcs_resilience_api"] = module
    spec.loader.exec_module(module)
    return module


def _patch_geometry(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", staticmethod(lambda *_a, **_k: GEOMETRY))
    monkeypatch.setattr(api, "esri_polygon_to_wgs84_wkt", lambda *_a, **_k: "POLYGON((-1 0,0 0,0 1,-1 0))")
    monkeypatch.setattr(
        api,
        "clipped_union_area_from_esri_geometries",
        lambda *_a, **_k: api.ClippedAreaResult(
            area_square_meters=10_000.0,
            status=api.SpatialAreaStatus.OK,
            complete=True,
        ),
    )


def test_geometry_failure_is_not_reported_as_no_hit(monkeypatch):
    api = _load_api()

    def fail(*_args, **_kwargs):
        raise RuntimeError("private upstream detail")

    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", staticmethod(fail))
    result = api.get_soil_mapunits_in_roi(37.7, -121.6)
    text = api.format_soil_mapunits_summary(result)

    assert result["data_unavailable"] is True
    assert "unavailable, not a no-hit finding" in result["error"]
    assert "private upstream detail" not in text


def test_sda_failure_is_not_reported_as_empty(monkeypatch):
    api = _load_api()
    _patch_geometry(api, monkeypatch)

    def fail(_query):
        raise api.UpstreamServiceError("database internals")

    monkeypatch.setattr(api, "_post_sda_query", fail)
    result = api.get_soil_mapunits_in_roi(37.7, -121.6)

    assert result["data_unavailable"] is True
    assert "not a no-hit finding" in result["warnings"][0]
    assert "database internals" not in result["error"]


def test_successful_empty_response_warns_about_coverage(monkeypatch):
    api = _load_api()
    _patch_geometry(api, monkeypatch)
    monkeypatch.setattr(
        api,
        "_post_sda_query",
        lambda _query: {"Table": [["mukey", "musym", "muname", "farmlndcl", "areasymbol", "saverest", "area_sqm"]]},
    )

    result = api.get_soil_mapunits_in_roi(37.7, -121.6)

    assert result["data_unavailable"] is False
    assert result["mapunit_count"] == 0
    assert any("not an absence of soil constraints" in warning for warning in result["warnings"])


def test_constraint_detail_failure_preserves_mapunit_context(monkeypatch):
    api = _load_api()
    base = {
        "center": {"latitude": 37.7, "longitude": -121.6},
        "buffer_miles": 1.0,
        "retrieved_at": "2026-08-28T00:00:00+00:00",
        "roi_area_acres": 10.0,
        "mapped_area_acres": 10.0,
        "coverage_pct": 100.0,
        "mapunit_count": 1,
        "mapunits": [
            {
                "mukey": "1001",
                "symbol": "Aa",
                "name": "Alpha",
                "farmland_classification": "Not prime farmland",
                "survey_area_symbol": "CA001",
                "survey_version_date": "2026-08-01",
                "area_square_meters": 40468.0,
                "area_acres": 10.0,
                "roi_percentage": 100.0,
            }
        ],
        "warnings": [],
        "truncated": False,
        "partial": False,
        "data_unavailable": False,
    }
    monkeypatch.setattr(api, "get_soil_mapunits_in_roi", lambda *_a, **_k: base)
    monkeypatch.setattr(
        api,
        "_post_sda_query",
        lambda _query: (_ for _ in ()).throw(api.UpstreamServiceError("failure")),
    )

    result = api.summarize_soil_constraints_for_siting(37.7, -121.6)

    assert result["mapunit_count"] == 1
    assert result["partial"] is True
    assert result["indicators"] == {}
    assert any("details were unavailable" in warning for warning in result["warnings"])
