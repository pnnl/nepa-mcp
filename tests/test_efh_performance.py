"""
Performance / scaling tests for the EFH API layer.

These are hermetic (ArcGIS mocked) and assert algorithmic behavior at larger
synthetic feature counts: deduplication reduces many fragments to few unique
records, area-union clipping stays bounded, and parsing stays fast. They do not
hit the network, so they are deterministic in CI.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-121.0, 46.0], [-120.0, 46.0], [-120.0, 47.0], [-121.0, 47.0], [-121.0, 46.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_efh_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "efh"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location("_efh_perf_api", server_dir / "src" / "apis" / "efh_api.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_efh_perf_api"] = module
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


def _efh_feature(species, *, geometry=SIMPLE_GEOMETRY, acres=10.0):
    feature = {
        "attributes": {
            "SITENAME_L": species,
            "LIFESTAGE": "ALL",
            "TYPE": "EFH",
            "FMC": "PFMC",
            "ZONE": "ALL",
            "ACRES": acres,
        }
    }
    if geometry is not None:
        feature["geometry"] = geometry
    return feature


class TestDeduplicationScaling:
    def test_many_duplicate_fragments_collapse_to_unique(self, monkeypatch):
        api = _load_efh_api()
        _patch_roi(api, monkeypatch)
        # 1000 fragments across 5 distinct species, all sharing one ROI geometry.
        names = [f"Species {i}" for i in range(5)]
        features = [_efh_feature(names[i % 5]) for i in range(1000)]
        _patch_features(api, monkeypatch, features)
        result = api.get_hms_cps_groundfish_efh_in_roi(46.5, -120.5)
        assert result["total"] == 5
        # Source acres sum straight; 200 fragments per species * 10 acres.
        for entry in result["efh_areas"]:
            assert entry["source_acres"] == 2000.0

    def test_many_duplicate_hapc_collapse(self, monkeypatch):
        api = _load_efh_api()
        _patch_roi(api, monkeypatch)
        features = [{"attributes": {"HAPC_Siten": "Estuaries", "FisheryM_5": "PFMC"}} for _ in range(1000)]
        _patch_features(api, monkeypatch, features)
        result = api.get_hapc_in_roi(46.5, -120.5)
        assert result["total"] == 1

    def test_many_salmon_watersheds_dedup_by_huc(self, monkeypatch):
        api = _load_efh_api()
        _patch_roi(api, monkeypatch)
        features = [{"attributes": {"HUC_8": i % 10, "HUC_8_Name": f"Watershed {i % 10}"}} for i in range(1000)]
        _patch_features(api, monkeypatch, features)
        result = api.get_salmon_efh_in_roi(46.5, -120.5)
        assert result["total"] == 10


class TestParsingThroughput:
    def test_large_dedup_and_clip_is_bounded(self, monkeypatch):
        api = _load_efh_api()
        _patch_roi(api, monkeypatch)
        # 5000 fragments across 50 species; area clipping unions per group.
        features = [_efh_feature(f"Species {i % 50}") for i in range(5000)]
        _patch_features(api, monkeypatch, features)
        start = time.perf_counter()
        result = api.get_hms_cps_groundfish_efh_in_roi(46.5, -120.5)
        elapsed = time.perf_counter() - start
        assert result["total"] == 50
        # In-memory dedup + union of identical geometry should be well bounded.
        assert elapsed < 5.0

    def test_large_hapc_parse_is_fast(self, monkeypatch):
        api = _load_efh_api()
        _patch_roi(api, monkeypatch)
        features = [{"attributes": {"HAPC_Siten": f"Site {i}", "FisheryM_5": "PFMC"}} for i in range(5000)]
        _patch_features(api, monkeypatch, features)
        start = time.perf_counter()
        result = api.get_hapc_in_roi(46.5, -120.5)
        elapsed = time.perf_counter() - start
        assert result["total"] == 5000
        assert elapsed < 1.0
