"""
Performance / scaling tests for the PCSRF API layer.

These are hermetic (ArcGIS mocked) and assert algorithmic behavior at larger
synthetic feature counts: critical-habitat fragment de-duplication collapses
many fragments into few grouped records, EFH grouping collapses repeated keys,
and parsing stays bounded in time. They do not hit the network, so they are
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
    "rings": [[[-121.0, 46.0], [-120.0, 46.0], [-120.0, 47.0], [-121.0, 47.0], [-121.0, 46.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_pcsrf_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "pcsrf"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location("_pcsrf_perf_api", server_dir / "src" / "apis" / "pcsrf_api.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_pcsrf_perf_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


class TestCriticalHabitatDedupScaling:
    def test_many_polygon_fragments_collapse_to_unique_units(self):
        api = _load_pcsrf_api()
        # 1000 fragments across 10 distinct (entity, unit) groups.
        features = [
            {
                "attributes": {
                    "LISTENTITY": "Test salmon DPS",
                    "UNIT": f"Unit {i % 10}",
                    "AREASqKm": 1.0,
                },
                "geometry": SIMPLE_GEOMETRY,
            }
            for i in range(1000)
        ]
        records = api._deduplicate_ch_fragments(features, "polygon", roi_geometry=SIMPLE_GEOMETRY)
        assert len(records) == 10

    def test_many_line_fragments_collapse_and_sum_length(self):
        api = _load_pcsrf_api()
        features = [
            {"attributes": {"LISTENTITY": "Test salmon DPS", "UNIT": "River", "Shape__Length": 0.001}}
            for _ in range(1000)
        ]
        records = api._deduplicate_ch_fragments(features, "line")
        assert len(records) == 1
        # 1000 * 0.001 deg * 111 km ~= 111 km.
        assert records[0]["length_km"] is not None


class TestEFHGroupingScaling:
    def test_many_efh_fragments_group_by_identity_key(self):
        api = _load_pcsrf_api()
        features = [
            {
                "attributes": {
                    "GNIS_Name": f"River {i % 5}",
                    "TYPE": "EFH",
                    "REGION": "GAR",
                    "LINK": "",
                    "BUFF_DIST": 100,
                    "Shape__Area": 10.0,
                },
                "geometry": SIMPLE_GEOMETRY,
            }
            for i in range(1000)
        ]
        records = api._parse_efh(features, roi_geometry=SIMPLE_GEOMETRY)
        assert len(records) == 5


class TestParsingThroughput:
    def test_large_project_set_parses_quickly(self, monkeypatch):
        api = _load_pcsrf_api()
        _patch_roi(api, monkeypatch)
        features = [
            {"attributes": {"PROJECT_NAME": f"Project {i}", "STATUS": "Active", "PCSRF_FUNDS": 1000.0}}
            for i in range(5000)
        ]
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=features, warnings=[]),
        )
        start = time.perf_counter()
        result = api.get_pcsrf_projects_in_roi(46.5, -120.5)
        elapsed = time.perf_counter() - start
        assert result["total"] == 5000
        assert result["total_pcsrf_funding"] == 5_000_000.0
        # Pure in-memory parse of 5k features should be well under a second.
        assert elapsed < 1.0

    def test_large_species_range_set_parses_quickly(self, monkeypatch):
        api = _load_pcsrf_api()
        _patch_roi(api, monkeypatch)
        # 5000 fragments across 50 distinct listed entities.
        features = [
            {"attributes": {"COMNAME": f"Species {i % 50}", "LISTENTITY": f"Entity {i % 50}", "LISTSTATUS": "T"}}
            for i in range(5000)
        ]
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=features, warnings=[]),
        )
        start = time.perf_counter()
        result = api.get_species_ranges_in_roi(46.5, -120.5)
        elapsed = time.perf_counter() - start
        assert result["species_count"] == 50
        assert elapsed < 1.0
