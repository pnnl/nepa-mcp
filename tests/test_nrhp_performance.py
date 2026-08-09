"""
Performance / scaling tests for the NRHP API layer.

These are hermetic (ArcGIS mocked) and assert algorithmic behavior at larger
synthetic feature counts: cross-layer de-duplication collapses duplicate
NRIS_Refnum records, and parsing/sorting stays bounded in time. They do not hit
the network, so they are deterministic in CI.
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


def _load_nrhp_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "nrhp"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location("_nrhp_perf_api", server_dir / "src" / "apis" / "nrhp_api.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_nrhp_perf_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


class TestDeduplicationScaling:
    def test_full_overlap_between_layers_collapses(self, monkeypatch):
        api = _load_nrhp_api()
        _patch_roi(api, monkeypatch)
        # Same 1000 refnums appear in both polygon (1) and point (0) layers.
        shared = [{"attributes": {"NRIS_Refnum": str(i), "RESNAME": f"Site {i}", "State": "NM"}} for i in range(1000)]

        def query_features(url, layer_id, _geometry, *, service_name=None, **_k):
            return ArcGISFeatureQueryResult(features=list(shared), warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_nrhp_properties_in_roi(35.6, -105.9)
        # Polygon layer provides all; point layer duplicates are dropped.
        assert result["total"] == 1000
        assert all(p["geometry_type"] == "Historic Places (Polygons)" for p in result["properties"])

    def test_disjoint_layers_sum(self, monkeypatch):
        api = _load_nrhp_api()
        _patch_roi(api, monkeypatch)

        def query_features(url, layer_id, _geometry, *, service_name=None, **_k):
            if layer_id == 1:
                feats = [{"attributes": {"NRIS_Refnum": f"P{i}", "RESNAME": f"Poly {i}"}} for i in range(500)]
            else:
                feats = [{"attributes": {"NRIS_Refnum": f"T{i}", "RESNAME": f"Point {i}"}} for i in range(500)]
            return ArcGISFeatureQueryResult(features=feats, warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_nrhp_properties_in_roi(35.6, -105.9)
        assert result["total"] == 1000


class TestParsingThroughput:
    def test_large_feature_set_parses_quickly(self, monkeypatch):
        api = _load_nrhp_api()
        _patch_roi(api, monkeypatch)
        features = [{"attributes": {"NRIS_Refnum": str(i), "RESNAME": f"Site {i}", "State": "NM"}} for i in range(5000)]

        def query_features(url, layer_id, _geometry, *, service_name=None, **_k):
            if layer_id == 1:
                return ArcGISFeatureQueryResult(features=features, warnings=[])
            return ArcGISFeatureQueryResult(features=[], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        start = time.perf_counter()
        result = api.get_nrhp_properties_in_roi(35.6, -105.9)
        elapsed = time.perf_counter() - start
        assert result["total"] == 5000
        # Pure in-memory parse + sort of 5k features should be well under a second.
        assert elapsed < 1.0

    def test_formatter_bounded_on_large_result(self, monkeypatch):
        api = _load_nrhp_api()
        _patch_roi(api, monkeypatch)
        features = [{"attributes": {"NRIS_Refnum": str(i), "RESNAME": f"Site {i}", "State": "NM"}} for i in range(3000)]

        def query_features(url, layer_id, _geometry, *, service_name=None, **_k):
            if layer_id == 1:
                return ArcGISFeatureQueryResult(features=features, warnings=[])
            return ArcGISFeatureQueryResult(features=[], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_nrhp_properties_in_roi(35.6, -105.9)
        start = time.perf_counter()
        out = api.format_nrhp_summary(result)
        elapsed = time.perf_counter() - start
        assert "Total NRHP Properties:** 3000" in out
        assert elapsed < 1.0
