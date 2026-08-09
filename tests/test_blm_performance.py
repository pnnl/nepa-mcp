"""
Performance / scaling tests for the BLM API layer.

These are hermetic (ArcGIS mocked) and assert algorithmic behavior at larger
synthetic feature counts: parsing and sorting stay linear-ish and bounded in
time. They do not hit the network, so they are deterministic in CI.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-112.0, 38.0], [-111.0, 38.0], [-111.0, 39.0], [-112.0, 39.0], [-112.0, 38.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_blm_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "blm"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location("_blm_perf_api", server_dir / "src" / "apis" / "blm_api.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_blm_perf_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


def _patch_features(api, monkeypatch, features):
    monkeypatch.setattr(
        api.ArcGISService,
        "query_features",
        lambda *_a, **_k: ArcGISFeatureQueryResult(features=features, warnings=[]),
    )


class TestParsingThroughput:
    def test_large_land_use_plan_set_parses_quickly(self, monkeypatch):
        api = _load_blm_api()
        _patch_roi(api, monkeypatch)
        features = [{"attributes": {"LUPName": f"Plan {i}"}} for i in range(5000)]
        _patch_features(api, monkeypatch, features)
        start = time.perf_counter()
        result = api.get_blm_land_use_plans_in_roi(38.5, -111.5)
        elapsed = time.perf_counter() - start
        assert result["total"] == 5000
        # Pure in-memory parse + sort of 5k features should be well under a second.
        assert elapsed < 1.0

    def test_large_wilderness_set_parses_quickly(self, monkeypatch):
        api = _load_blm_api()
        _patch_roi(api, monkeypatch)
        features = [{"attributes": {"NLCS_NAME": f"Wilderness {i}", "DESIG_DATE": 946684800000}} for i in range(5000)]
        _patch_features(api, monkeypatch, features)
        start = time.perf_counter()
        result = api.get_blm_wilderness_areas_in_roi(38.5, -111.5)
        elapsed = time.perf_counter() - start
        assert result["total"] == 5000
        assert elapsed < 2.0

    def test_large_monument_set_parses_quickly(self, monkeypatch):
        api = _load_blm_api()
        _patch_roi(api, monkeypatch)
        features = [{"attributes": {"NCA_NAME": f"NM {i}"}} for i in range(5000)]
        _patch_features(api, monkeypatch, features)
        start = time.perf_counter()
        result = api.get_blm_national_monuments_in_roi(38.5, -111.5)
        elapsed = time.perf_counter() - start
        assert result["total"] == 5000
        assert elapsed < 1.0


class TestSortingCorrectnessAtScale:
    def test_plans_returned_sorted_by_name(self, monkeypatch):
        api = _load_blm_api()
        _patch_roi(api, monkeypatch)
        # Reverse-ordered input; expect ascending sorted output.
        features = [{"attributes": {"LUPName": f"Plan {i:04d}"}} for i in range(1000, 0, -1)]
        _patch_features(api, monkeypatch, features)
        result = api.get_blm_land_use_plans_in_roi(38.5, -111.5)
        names = [p["plan_name"] for p in result["land_use_plans"]]
        assert names == sorted(names)
