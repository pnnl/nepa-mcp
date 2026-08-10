"""
Performance / scaling tests for the USACE API layer.

These are hermetic (ArcGIS mocked) and assert algorithmic behavior at larger
synthetic feature counts: deduplication reduces many fragments to few unique
records, and parsing stays linear-ish and bounded in time. They do not hit the
network, so they are deterministic in CI.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_usace_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "usace"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location("_usace_perf_api", server_dir / "src" / "apis" / "usace_api.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_usace_perf_api"] = module
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


class TestDeduplicationScaling:
    def test_many_duplicate_districts_collapse_to_unique(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)
        # 500 fragments across 5 distinct districts.
        names = [f"District {i}" for i in range(5)]
        features = [{"attributes": {"ERO_FORMALNAME": names[i % 5]}} for i in range(500)]
        _patch_features(api, monkeypatch, features)
        result = api.get_usace_regulatory_district(34.5, -106.5)
        assert result["total_districts"] == 5

    def test_many_duplicate_regions_collapse(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)
        features = [{"attributes": {"REGION": "Arid West"}} for _ in range(1000)]
        _patch_features(api, monkeypatch, features)
        result = api.get_wetland_regions_in_roi(34.5, -106.5)
        assert result["total_regions"] == 1

    def test_many_subregions_dedup(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)
        features = [{"attributes": {"ADS_SUB_NM": f"Sub {i % 10}", "ADS_REGSUP": "AW"}} for i in range(1000)]
        _patch_features(api, monkeypatch, features)
        result = api.get_wetland_subregions_in_roi(34.5, -106.5)
        assert result["total_subregions"] == 10


class TestParsingThroughput:
    def test_large_feature_set_parses_quickly(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)
        features = [{"attributes": {"ERO_FORMALNAME": f"District {i}"}} for i in range(5000)]
        _patch_features(api, monkeypatch, features)
        start = time.perf_counter()
        result = api.get_usace_regulatory_district(34.5, -106.5)
        elapsed = time.perf_counter() - start
        assert result["total_districts"] == 5000
        # Pure in-memory parse of 5k features should be well under a second.
        assert elapsed < 1.0

    def test_comprehensive_analysis_bounded(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)
        features = [{"attributes": {"ERO_FORMALNAME": f"District {i}", "REGION": "Arid West"}} for i in range(1000)]
        _patch_features(api, monkeypatch, features)
        start = time.perf_counter()
        api.analyze_usace_jurisdiction(34.5, -106.5)
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0
