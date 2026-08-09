"""
Performance / scaling tests for the NOAA critical habitat API layer.

These are hermetic (ArcGIS mocked) and assert algorithmic behavior at larger
synthetic feature counts: de-duplication collapses many diced fragments to a
few unique listed entities, unit aggregation stays correct at scale, and
parsing stays bounded in time. They do not hit the network, so they are
deterministic in CI.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "noaa"
SIMPLE_GEOMETRY = {
    "rings": [[[-121.0, 46.0], [-120.0, 46.0], [-120.0, 47.0], [-121.0, 47.0], [-121.0, 46.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_noaa_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    sys.path.insert(0, str(SERVER_DIR))
    try:
        spec = importlib.util.spec_from_file_location("_noaa_perf_api", SERVER_DIR / "src" / "apis" / "noaa_api.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_noaa_perf_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SERVER_DIR))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


class TestDeduplicationScaling:
    def test_many_polygon_fragments_collapse_to_unique_entities(self):
        api = _load_noaa_api()
        # 1000 fragments across 5 distinct listed entities, no geometry so we
        # isolate the grouping cost from the clip cost.
        features = [
            {"attributes": {"listentity": f"Entity {i % 5}", "unit": f"Unit {i % 20}", "areasqkm": 1.0}}
            for i in range(1000)
        ]
        deduped = api._deduplicate_fragments(features, 2, "polygon")
        assert len(deduped) == 5
        # Each entity saw 4 distinct unit labels (20 units / 5 entities).
        assert all(h["unit_count"] == 4 for h in deduped)

    def test_many_line_fragments_sum_length(self):
        api = _load_noaa_api()
        features = [
            {"attributes": {"listentity": "Salmon DPS", "unit": f"Reach {i}", "lengthkm": 1.0}} for i in range(1000)
        ]
        deduped = api._deduplicate_fragments(features, 1, "line")
        assert len(deduped) == 1
        assert deduped[0]["length_km"] == 1000.0


class TestParsingThroughput:
    def test_large_line_feature_set_parses_quickly(self, monkeypatch):
        api = _load_noaa_api()
        _patch_roi(api, monkeypatch)
        # Lines skip geometry clipping, so this measures pure parse throughput.
        features = [{"attributes": {"listentity": f"Entity {i}", "lengthkm": 1.0}} for i in range(5000)]
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda _u, layer_id, _g, **_k: ArcGISFeatureQueryResult(
                features=features if layer_id == 1 else [], warnings=[]
            ),
        )
        start = time.perf_counter()
        result = api.get_noaa_critical_habitat_in_roi(46.5, -120.5, 5.0)
        elapsed = time.perf_counter() - start
        assert result["total"] == 5000
        assert elapsed < 1.0

    def test_clipping_many_polygon_fragments_is_bounded(self, monkeypatch):
        api = _load_noaa_api()
        _patch_roi(api, monkeypatch)
        # 200 diced fragments for a single entity, each carrying geometry so the
        # union-and-clip path runs; should still complete quickly.
        features = [
            {
                "attributes": {"listentity": "Whale DPS", "unit": f"Unit {i}", "areasqkm": 1.0},
                "geometry": SIMPLE_GEOMETRY,
            }
            for i in range(200)
        ]
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda _u, layer_id, _g, **_k: ArcGISFeatureQueryResult(
                features=features if layer_id == 2 else [], warnings=[]
            ),
        )
        start = time.perf_counter()
        result = api.get_noaa_critical_habitat_in_roi(46.5, -120.5, 5.0)
        elapsed = time.perf_counter() - start
        assert result["total"] == 1
        assert result["habitats"][0]["area_status"] == "ok"
        assert elapsed < 5.0
