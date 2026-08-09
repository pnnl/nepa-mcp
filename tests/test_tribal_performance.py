"""
Performance / scaling tests for the tribal API layer.

These are hermetic (ArcGIS mocked) and assert algorithmic behavior at larger
synthetic feature counts: all features are retained (no deduplication), sorting
scales, and parsing stays bounded in time. They do not hit the network, so they
are deterministic in CI.
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


def _load_tribal_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "tribal"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location("_tribal_perf_api", server_dir / "src" / "apis" / "tribal_api.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_tribal_perf_api"] = module
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


class TestRetentionScaling:
    def test_all_features_retained_no_dedup(self, monkeypatch):
        api = _load_tribal_api()
        _patch_roi(api, monkeypatch)
        # 200 identical-named features per layer; tribal API keeps them all.
        features = [{"attributes": {"NAME": "Same Name"}} for _ in range(200)]
        _patch_features(api, monkeypatch, features)
        result = api.get_tribal_lands_in_roi(34.5, -106.5)
        # 200 per layer across all 6 layers, none collapsed.
        assert result["total"] == 200 * len(api.TRIBAL_LAYERS)

    def test_large_feature_set_parses_quickly(self, monkeypatch):
        api = _load_tribal_api()
        _patch_roi(api, monkeypatch)
        features = [{"attributes": {"NAME": f"Land {i}", "AREALAND": i * 1000}} for i in range(5000)]
        _patch_features(api, monkeypatch, features)
        start = time.perf_counter()
        result = api.get_tribal_lands_in_roi(34.5, -106.5)
        elapsed = time.perf_counter() - start
        # 5000 features returned per layer across all layers.
        assert result["total"] == 5000 * len(api.TRIBAL_LAYERS)
        # In-memory parse + sort should be well under a couple seconds.
        assert elapsed < 2.0

    def test_results_remain_sorted_at_scale(self, monkeypatch):
        api = _load_tribal_api()
        _patch_roi(api, monkeypatch)
        features = [{"attributes": {"NAME": f"Land {i:04d}"}} for i in range(1000, 0, -1)]
        _patch_features(api, monkeypatch, features)
        result = api.get_tribal_lands_in_roi(34.5, -106.5)
        names = [land["name"].lower() for land in result["tribal_lands"]]
        assert names == sorted(names)
