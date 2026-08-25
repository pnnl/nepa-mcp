"""
Performance / scaling tests for the PADUS API layer.

These are hermetic (ArcGIS mocked) and assert algorithmic behavior at larger
synthetic feature counts: parsing, sorting, and acreage aggregation stay
linear-ish and bounded in time. They do not hit the network, so they are
deterministic in CI.
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


def _load_padus_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "padus"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location("_padus_perf_api", server_dir / "src" / "apis" / "padus_api.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_padus_perf_api"] = module
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
    def test_large_feature_set_parses_quickly(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        features = [
            {"attributes": {"Category": "Fee", "Own_Type": "FED", "Own_Name": f"Owner {i}", "GIS_Acres": i}}
            for i in range(5000)
        ]
        _patch_features(api, monkeypatch, features)
        start = time.perf_counter()
        result = api.get_padus_in_roi(34.5, -106.5)
        elapsed = time.perf_counter() - start
        assert result["total_records"] == 5000
        # Pure in-memory parse+sort of 5k features should be well under a second.
        assert elapsed < 1.0

    def test_format_summary_bounded_on_large_input(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        features = [
            {
                "attributes": {
                    "Category": f"C{i % 7}",
                    "Own_Type": f"T{i % 20}",
                    "Own_Name": f"Owner {i}",
                    "GIS_Acres": i,
                }
            }
            for i in range(5000)
        ]
        _patch_features(api, monkeypatch, features)
        data = api.get_padus_in_roi(34.5, -106.5)
        start = time.perf_counter()
        out = api.format_padus_summary(data)
        elapsed = time.perf_counter() - start
        # Top-10 slice keeps the rendered list short regardless of input size.
        assert "Top 10 Largest Intersecting Source Features by Full Mapped Acreage (not clipped to ROI):" in out
        assert elapsed < 1.0


class TestAcreagePresentation:
    def test_source_acreage_is_not_aggregated_as_roi_area(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        # 300 fee records of 10 acres each, 200 designation records of 5 acres each.
        features = [{"attributes": {"Category": "Fee", "Own_Type": "FED", "GIS_Acres": 10}} for _ in range(300)]
        features += [
            {"attributes": {"Category": "Designation", "Own_Type": "DESG", "GIS_Acres": 5}} for _ in range(200)
        ]
        _patch_features(api, monkeypatch, features)
        data = api.get_padus_in_roi(34.5, -106.5)
        out = api.format_padus_summary(data)
        assert data["total_records"] == 500
        assert "Federal (FED): 300 records" in out
        assert "Designation (DESG): 200 records" in out
        assert "Fee: 300 records" in out
        assert "Designation: 200 records" in out
        assert "3,000 acres" not in out
        assert "1,000 acres" not in out
