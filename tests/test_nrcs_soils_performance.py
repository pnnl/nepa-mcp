"""Bounded-output and local aggregation checks for NRCS soil screening."""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "nrcs_soils"


def _load_api():
    for name in list(sys.modules):
        if name == "src" or name.startswith("src.") or name.startswith("_nrcs_perf_"):
            sys.modules.pop(name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_nrcs_perf_api", SERVER_DIR / "src" / "apis" / "nrcs_soils_api.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_nrcs_perf_api"] = module
    spec.loader.exec_module(module)
    return module


def _mapunit(index: int):
    return {
        "mukey": str(100000 + index),
        "symbol": f"M{index}",
        "name": f"Map unit {index}",
        "farmland_classification": "Not prime farmland",
        "survey_area_symbol": "ZZ001",
        "survey_version_date": "2026-08-01",
        "area_square_meters": 4046.8564224,
        "area_acres": 1.0,
        "roi_percentage": 0.2,
    }


def test_mapunit_output_is_bounded_for_large_results():
    api = _load_api()
    data = {
        "center": {"latitude": 40.0, "longitude": -100.0},
        "buffer_miles": 10.0,
        "retrieved_at": "2026-08-28T00:00:00+00:00",
        "roi_area_acres": 500.0,
        "mapped_area_acres": 500.0,
        "coverage_pct": 100.0,
        "mapunit_count": 500,
        "mapunits": [_mapunit(index) for index in range(500)],
        "warnings": [],
        "truncated": False,
        "partial": False,
        "data_unavailable": False,
    }

    start = time.perf_counter()
    text = api.format_soil_mapunits_summary(data)
    elapsed = time.perf_counter() - start

    assert text.count("- **M") == 50
    assert "Additional map units are not shown" in text
    assert len(text) < 30_000
    assert elapsed < 1.0


def test_weighted_distribution_scales_linearly():
    api = _load_api()
    mapunits = {item["mukey"]: item for item in (_mapunit(index) for index in range(500))}
    components = [
        {
            "mukey": key,
            "component_percentage": 50.0,
            "hydrologic_group": "C",
        }
        for key in mapunits
        for _ in range(10)
    ]

    start = time.perf_counter()
    result = api._weighted_distribution(mapunits, components, "hydrologic_group")
    elapsed = time.perf_counter() - start

    assert result == {"C": 2500.0}
    assert elapsed < 1.0
